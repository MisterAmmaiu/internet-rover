import subprocess
import socket
import threading
import time
import signal
import sys
import os

########################
### GLOBAL VARIABLES ###
########################

# Socket stuff
SOCK_ROVER = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK_ROVER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
SOCK_ROVER.settimeout(1)
SOCK_CONTROLLER = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK_CONTROLLER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
SOCK_CONTROLLER.settimeout(1)
# Addresses
BIND_ROVER = ("0.0.0.0", 3658)
BIND_CONTROLLER = ("0.0.0.0", 3659)
ADDRESS_ROVER = ("127.0.0.1", 12345)
ADDRESS_CONTROLLER = ("127.0.0.1", 12345)
ADDRESS_CHANGE_ROVER = False
ADDRESS_CHANGE_CONTROLLER = False
# Gstream
CMD_RELAY_VIDEO = "gst-launch-1.0 -v udpsrc port=3660 ! application/x-rtp,encoding-name=H264 ! udpsink bind-port=3659 host=$HOSTNAME$ port=$PORT$ >/dev/null"
CMD_KILL_VIDEO = "sudo pkill gst-launch-1.0"
# Status
KEEP_RUNNING = True
FORWARD_VIDEO = False



##########################
### UTILITY FUNCTIONS ####
##########################

# Simply closes the given socket
def unbindSocket(sock):
    sock.close()

# Binds the given socket to the given (IP, port)
def bindSocket(sock, addressCombo):
    sock.bind(addressCombo)
   
# Returns the GStream relay command populated with the given address = (hostname, port)
def getBuiltGStreamRelayCommand(address):
    hostname, port = address
    return CMD_RELAY_VIDEO.replace("$HOSTNAME$", str(hostname)).replace("$PORT$", str(port))

# Stops an existing GStream process
def stopVideo():
    global FORWARD_VIDEO
    FORWARD_VIDEO = False
    os.system(CMD_KILL_VIDEO)
    
# Sets FORWARD_VIDEO to true which permits the starting of the GStreamer process
def startVideo():
    global FORWARD_VIDEO
    FORWARD_VIDEO = True
    
# Just a wrapper for stopVideo() and startVideo()
def restartVideo():
    stopVideo()
    startVideo()



#################
### FUNCTIONS ###
#################

# Listens to the rover's socket, waiting for messages. Currently only ever
# expected to receive "IT'S ME" as heartbeat, to which the server will
# respond with "HI" if there's a controller ready. "Z" could be received
# if the rover somehow exiting its state machine, but that would only occur
# due to a bug.
def threadFunctionRoverListener():
    global KEEP_RUNNING, SOCK_ROVER, ADDRESS_ROVER, ADDRESS_CHANGE_ROVER
    while (KEEP_RUNNING):
        try:
            data, addr = SOCK_ROVER.recvfrom(10)
        except socket.timeout:
            continue
        msg = data.decode()
        if msg == "IT'S ME":
            if addr != ADDRESS_ROVER:
                ADDRESS_ROVER = addr
                ADDRESS_CHANGE_ROVER = True
                # Only send start signal to rover if there's a controller ready
                if ADDRESS_CONTROLLER != ("127.0.0.1", 12345):
                    SOCK_ROVER.sendto(b'HI', ADDRESS_ROVER)
        elif msg == "Z":
            # For now just end video
            stopVideo()
            ADDRESS_ROVER = ("127.0.0.1", 12345)
            print("Rover shut itself down")
        else:
            print("Received unknown message from Rover: " + msg)
ROVER_THREAD = threading.Thread(target=threadFunctionRoverListener)
  
# Listens to the controller's socket, waiting for messages.
# On receiving...
# "HEARTBEAT" : if new source, respond with HELLO to notify of registration, send HI to extant Rover
# "Z"         : stop video, reset addresses for controller/rover, send partial shutdown to rover
# "*"         : forward directly to rover (should be a controller)
def threadFunctionControllerListener():
    global KEEP_RUNNING, SOCK_CONTROLLER, SOCK_ROVER, ADDRESS_CONTROLLER, ADDRESS_ROVER, ADDRESS_CHANGE_CONTROLLER
    while (KEEP_RUNNING):
        try:
            data, addr = SOCK_CONTROLLER.recvfrom(10)
        except socket.timeout:
            continue
        msg = data.decode()
        if msg == "HEARTBEAT":
            if addr != ADDRESS_CONTROLLER:
                ADDRESS_CONTROLLER = addr
                ADDRESS_CHANGE_CONTROLLER = True
                SOCK_CONTROLLER.sendto(b'HELLO', ADDRESS_CONTROLLER)
                if ADDRESS_ROVER != ("127.0.0.1", 12345):
                    SOCK_ROVER.sendto(b'HI', ADDRESS_ROVER)
        elif msg == "Z":
            stopVideo()
            ADDRESS_CONTROLLER = ("127.0.0.1", 12345)
            SOCK_ROVER.sendto(b'Z', ADDRESS_ROVER) # Rover will return to initial heartbeat-only state, waiting for "HI"
            SOCK_ROVER.sendto(b'Z', ADDRESS_ROVER)
            SOCK_ROVER.sendto(b'Z', ADDRESS_ROVER)
            ADDRESS_ROVER = ("127.0.0.1", 12345)
            print("Video stream ended by Controller")
        else:
            # Forward everything else to the Rover
            SOCK_ROVER.sendto(data, ADDRESS_ROVER)
CONTROLLER_THREAD = threading.Thread(target=threadFunctionControllerListener)

# This will start the GStream process and block until it exits.
# It will then start GStream again unless FORWARD_VIDEO is false.
# The functions stopVideo(), startVideo(), and restartVideo() are
# made to abstract this logic.
def threadFunctionVideoListener():
    global ADDRESS_CONTROLLER, FORWARD_VIDEO
    while (KEEP_RUNNING):
        if (FORWARD_VIDEO):
            os.system(getBuiltGStreamRelayCommand(ADDRESS_CONTROLLER))
VIDEO_THREAD = threading.Thread(target=threadFunctionVideoListener)

# Used to cleanly shut down all threads and unbind all sockets
def cleanExit(threads, sockets):
    print("Waiting for child threads...")
    stopVideo()
    for thrd in threads:
        if thrd.is_alive():
            thrd.join()
    print("Unbinding sockets...")
    for sckt in sockets:
        unbindSocket(sckt)
    print("Exited cleanly")
    sys.exit(0)

# Handles CTRL+C stop for development
def signal_handler(sig, frame):
    global KEEP_RUNNING, ROVER_THREAD, CONTROLLER_THREAD, SOCK_ROVER, SOCK_CONTROLLER
    KEEP_RUNNING = False
    print("Received CTRL+C, exiting...")
    cleanExit([ROVER_THREAD, CONTROLLER_THREAD], [SOCK_ROVER, SOCK_CONTROLLER])
signal.signal(signal.SIGINT, signal_handler)



######################
### MAIN EXECUTION ###
######################

# Bind sockets
print("Binding sockets...")
bindSocket(SOCK_ROVER, BIND_ROVER)
bindSocket(SOCK_CONTROLLER, BIND_CONTROLLER)

# Start listener threads
print("Starting listener threads...")
ROVER_THREAD.start()
CONTROLLER_THREAD.start()
VIDEO_THREAD.start()

# Polling loop
while (KEEP_RUNNING):
    if ADDRESS_CHANGE_ROVER:
        # This doesn't really do anything for now
        print("Address of rover changed")
        ADDRESS_CHANGE_ROVER = False
    if ADDRESS_CHANGE_CONTROLLER:
        print("Address of controller changed")
        # Restart video so it forwards to the next address
        restartVideo()
        # Give GStreamer a second to use the socket before rebinding to it
        # (GStreamer forwards on the same controller port, and when it starts
        # it redefines the port for only sending, so you have to wait for it
        # to start and then redefine the port again as a shared port for
        # sending and receiving, or at least that's my theory)
        time.sleep(1)
        # Redefine/rebind the controller port after GStreamer has modified it
        SOCK_CONTROLLER = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        SOCK_CONTROLLER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        SOCK_CONTROLLER.settimeout(1)
        bindSocket(SOCK_CONTROLLER, BIND_CONTROLLER)
        print("Restarted gstream forwarding")
        ADDRESS_CHANGE_CONTROLLER = False

# Normal exit point
cleanExit([ROVER_THREAD, CONTROLLER_THREAD], [SOCK_ROVER, SOCK_CONTROLLER])