#include <stdio.h>            // printf
#include <stdlib.h>
#include <string.h>           // Memset
#include <signal.h>           // CTRL+C Handling
#include <sys/socket.h>       // Sockets
#include <netinet/in.h>       // Sockets
#include <arpa/inet.h>        // Sockets
#include <pthread.h>          // Threading
#include <netdb.h>            // Hostname resolution
#include <unistd.h>           // Sleep
#include "pi_gpio_wrapper.h"  // For wheel control

////////////
// MACROS //
////////////

// Controls
#define FORWARD 'F'
#define BACKWARD 'B'
#define LEFT 'L'
#define RIGHT 'R'
#define STOP 'S'
#define SHUTDOWN 'Z'
// Gstreamer command
#define GSTREAM_COMMAND "gst-launch-1.0 -v libcamerasrc ! video/x-raw,width=640,height=480,framerate=25/1 ! videoconvert ! x264enc tune=zerolatency bitrate=500 speed-preset=superfast ! rtph264pay ! queue max-size-time=0 max-size-buffers=0 max-size-bytes=0 ! udpsink port=3660 buffer-size=65536 sync=false async=false host="



/////////////////////
// STRUCTS & ENUMS //
/////////////////////

struct listenerSocketInfo
{
  int fd;
  struct addrinfo *res;
};
typedef struct listenerSocketInfo listenerSocketInfo;

enum State
{
  START_HB,
  WAIT_HI,
  START_CTRL,
  START_GSTRM,
  LISTEN_CTRL,
  END_GSTRM,
  END_CTRL
};



//////////////////////
// GLOBAL VARIABLES //
//////////////////////

static volatile int keep_running = 1;
char full_gstream_command[350];
const char hostname[53];
const char *port = "3658";
static enum State state = START_HB;
static volatile char control = 'S';
static volatile long long current_time_ms = 0;
static volatile long long stop_time_ms = 0;



///////////////////////
// UTILITY FUNCTIONS //
///////////////////////

// Handles the CTRL+C interrupt to exit cleanly
void interruptHandler(int dummy)
{
  keep_running = 0;
}

// Kills the GStream process and managing thread
int killGStream(pthread_t *gs_thread)
{
  system("sudo pkill gst-launch-1.0");
  if (pthread_join(*gs_thread, NULL) != 0)
    return -1;
  
  // Normal exit
  return 0;
}

// Kills the control listener thread
int killControlListener(pthread_t *cl_thread)
{
  pthread_cancel(*cl_thread);
  if (pthread_join(*cl_thread, NULL) != 0)
    return -1;
  
  // Normal exit
  return 0;
}

// This gets the IP address of the given hostname, sets up a socket
// with that IP adress, and returns the neccesary info to use that
// socket in a struct
int initListenerSocket(struct addrinfo *res, listenerSocketInfo *listSockInfo)
{
  // Set up socket address info for getting IP address of hostname
  struct addrinfo hints;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_INET;      // IPv4
  hints.ai_socktype = SOCK_DGRAM; // UDP

  // Get IP address of hostname (e.g. welsgaming.mywire.org)
  if (getaddrinfo(hostname, port, &hints, &res) != 0)
  {
    perror("getaddrinfo");
    exit(EXIT_FAILURE);
  }

  // Create a UDP Socket
  int listenfd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
  listSockInfo->fd = listenfd;
  listSockInfo->res = res;

  // Normal exit
  return 0;
}

// Gets the current time in MS for use in stop-on-disconnect functionality
long long getcurrent_time_ms()
{
  struct timespec spec;
  clock_gettime(CLOCK_MONOTONIC, &spec); // Use CLOCK_MONOTONIC for measuring intervals
  return (long long)spec.tv_sec * 1000 + spec.tv_nsec / 1000000;
}


//////////////////////
// THREAD FUNCTIONS //
//////////////////////

// Sends out a heartbeat every 10 seconds
void *threadFunctionHeartbeat(void *arg)
{
  pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
  struct listenerSocketInfo *listSockInfo = (struct listenerSocketInfo *)arg;
  while (keep_running)
  {
    sendto(listSockInfo->fd, "IT'S ME", 7, 0, listSockInfo->res->ai_addr, listSockInfo->res->ai_addrlen);
    sleep(10);
  }
  
  return NULL;
}

// Waits for socket message and sets the global control variable
// to the first byte of the socket message (should be F, B, L, R, or S)
void *threadFunctionControlListener(void *arg)
{
  pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
  struct listenerSocketInfo *listSockInfo = (struct listenerSocketInfo *)arg;
  while (keep_running)
  {
    // Wait for next control
    socklen_t len = sizeof(listSockInfo->res->ai_addrlen);
    char buffer[10] = "\0\0\0\0\0\0\0\0\0\0";
    recvfrom(listSockInfo->fd, buffer, sizeof(buffer), 0, (listSockInfo->res->ai_addr), &len); // receive message from server
    control = buffer[0];
    // Update stop time
    stop_time_ms = getcurrent_time_ms() + 1000;
  }
  
  return NULL;
}

// Starts and holds the GStream process
void *threadFunctionGStream(void *arg)
{
  // Set up exit via CTRL+C
  signal(SIGINT, interruptHandler);
  // Start GStreamer
  system(full_gstream_command);
  
  return NULL;
}



/////////////////////
// STATE FUNCTIONS //
/////////////////////

// Handles the START_HB state
int handleStateStartHeartbeat(pthread_t *hb_thread, listenerSocketInfo *listSockInfo)
{
  // Start heartbeat thread
  printf("Starting heartbeat thread...\n");
  if (pthread_create(hb_thread, NULL, threadFunctionHeartbeat, listSockInfo) != 0)
  {
    perror("Failed to create heartbeat thread");
    return -1;
  }

  // Update state
  state = WAIT_HI;
  return 0;
}

// Handles the WAIT_HI state
int handleStateWaitHi(listenerSocketInfo *listSockInfo)
{
  printf("Waiting for HI...\n");

  // Wait for response from socket
  char buffer[10] = "\0\0\0\0\0\0\0\0\0\0";
  socklen_t len = sizeof(listSockInfo->res->ai_addrlen);
  recvfrom(listSockInfo->fd, buffer, sizeof(buffer), 0, (listSockInfo->res->ai_addr), &len);

  // Only go to next state once we get HI message
  if (strcmp(buffer, "HI") == 0)
  {
    state = START_CTRL;
  }

  return 0;
}

// Handles the START_CTRL state
int handleStateStartControl(pthread_t *cl_thread, listenerSocketInfo *listSockInfo)
{
  // Start control listener thread
  printf("Starting control listener thread...\n");
  if (pthread_create(cl_thread, NULL, threadFunctionControlListener, listSockInfo) != 0)
  {
    perror("Failed to create listener thread");
    return -1;
  }

  // Update state
  state = START_GSTRM;
  return 0;
}

// Handles the START_GSTRM state
int handleStateStartGStream(pthread_t *gs_thread)
{
  // Start GStream thread
  printf("Starting GStream thread...\n");
  if (pthread_create(gs_thread, NULL, threadFunctionGStream, NULL) != 0)
  {
    perror("Failed to create GStream thread");
    return -1;
  }
  
  // Update state
  state = LISTEN_CTRL;
  return 0;
}

// Handles the LISTEN_CTRL state
int handleStateListenControl()
{
  // Update current time
  current_time_ms = getcurrent_time_ms();

  // If we have not recieved an update recently enough, automatically stop
  if (stop_time_ms <= current_time_ms)
  {
    if (driveStop())
      return -1;
	else
	  return 0;
  }

  switch (control)
  {
  case FORWARD:
    if (driveForward())
      return -1;
    break;
  case BACKWARD:
    if (driveBackward())
      return -1;
    break;
  case LEFT:
    if (driveLeft())
      return -1;
    break;
  case RIGHT:
    if (driveRight())
      return -1;
    break;
  case STOP:
    if (driveStop())
      return -1;
    break;
  case SHUTDOWN:
    state = END_GSTRM;
    break;
  default:
    break;
  }
  
  return 0;
}

// Handles the END_GSTRM state
int handleStateEndGStream(pthread_t *gs_thread)
{
  if (killGStream(gs_thread))
	return -1;
  state = END_CTRL;
  return 0;
}

// Handles the END_CTRL state
int handleStateEndControl(pthread_t *cl_thread)
{
  if (killControlListener(cl_thread))
	return -1;
  state = WAIT_HI;
  return 0;
}

int main(int argc, char *argv[])
{
  // Set up exit via CTRL+C
  signal(SIGINT, interruptHandler);
  
  // Get hostname from args, setup gstream command
  if (argc != 2)
  {
	printf("Improper usage! Should be \"main myserver.com\"");
  }
  else
  {
	strcpy(hostname, argv[1]);
	strcpy(full_gstream_command, GSTREAM_COMMAND);
	strcat(full_gstream_command, hostname);
  }

  // Initialize physical hardware
  if (initCircuitry())
    return -1;

  // Initialize listener socket
  struct addrinfo res;
  listenerSocketInfo listSockInfo;
  if (initListenerSocket(&res, &listSockInfo))
    return -1;

  // Declare threads
  pthread_t hb_thread;
  pthread_t cl_thread;
  pthread_t gs_thread;

  // Run state machine until CTRL+C
  while (keep_running)
  {
    switch (state)
    {
    case START_HB:
      if (handleStateStartHeartbeat(&hb_thread, &listSockInfo))
        return -1;
      break;
    case WAIT_HI:
      if (handleStateWaitHi(&listSockInfo))
        return -1;
      break;
    case START_CTRL:
      if (handleStateStartControl(&cl_thread, &listSockInfo))
        return -1;
      break;
    case START_GSTRM:
      if (handleStateStartGStream(&gs_thread))
        return -1;
      break;
    case LISTEN_CTRL:
      if (handleStateListenControl())
        return -1;
      break;
	case END_GSTRM:
      if (handleStateEndGStream(&gs_thread))
        return -1;
      break;
	case END_CTRL:
      if (handleStateEndControl(&cl_thread))
        return -1;
      break;
    default:
      break;
    }
  }

  // Un-initialize physical hardware
  uninitCircuitry();

  // Join all threads
  printf("Waiting on GStreamer thread to join...\n");
  if (killGStream(&gs_thread))
  {
	perror("Failed to join GStreamer thread");
    return -1;
  }
  printf("Waiting on control listener thread to join...\n");
  if (killControlListener(&cl_thread))
  {
	perror("Failed to join control listener thread");
    return -1;
  }
  printf("Waiting on heartbeat thread to join...\n");
  if (pthread_join(hb_thread, NULL) != 0)
  {
    perror("Failed to join heartbeat thread");
    return -1;
  }

  // Tell server that we're shutting down
  sendto(listSockInfo.fd, "Z", 1, 0, listSockInfo.res->ai_addr, listSockInfo.res->ai_addrlen);
  sendto(listSockInfo.fd, "Z", 1, 0, listSockInfo.res->ai_addr, listSockInfo.res->ai_addrlen);
  sendto(listSockInfo.fd, "Z", 1, 0, listSockInfo.res->ai_addr, listSockInfo.res->ai_addrlen);
  printf("Sent shutdown confirmation\n");

  return 0;
}
