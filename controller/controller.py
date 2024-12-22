import subprocess
import socket
import threading
import time
import signal
import sys
import select
import argparse
from pynput import keyboard
from collections import deque

# Set up command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument("server", help="the hostname of the relay server i.e. myserver.com")
args = parser.parse_args()



########################
### GLOBAL VARIABLES ###
########################

RUN = True
# Socket stuff
SERVER = (args.server, 3659)
SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
SOCK.bind(("0.0.0.0", 12345))
# GStream
RECEIVE_VIDEO = "gst-launch-1.0 -v udpsrc port=12345 ! application/x-rtp,encoding-name=H264 ! rtph264depay ! decodebin ! autovideosink"
# Commands
C_FORWARD  = b'F'
C_BACKWARD = b'B'
C_LEFT     = b'L'
C_RIGHT    = b'R'
C_STOP     = b'S'
CURRENT_COMMAND = C_STOP
# Command management/debouncing
PRESSED_CTR = 0
PRESSED_KEYS = set()
PRESSED_COMMANDS = []
# States 
S_START_HB       = 0
S_WAIT_HELLO     = 1
S_START_GSTRM    = 2
S_START_KYBRD    = 3
S_START_CMD_LOOP = 4
S_WAIT_EXIT      = 5
S_EXIT           = 6
STATE = S_START_HB



##########################
### UTILITY FUNCTIONS ####
##########################

# Utility function to convert a keyboard enum to a letter
def getKeyAsByteLetter(key):
    if key == keyboard.Key.up:
        return C_FORWARD
    elif key == keyboard.Key.down:
        return C_BACKWARD
    elif key == keyboard.Key.left:
        return C_LEFT
    elif key == keyboard.Key.right:
        return C_RIGHT

# Sends the given command to the socket and logs it accordingly
def sendCommand(command):
    global SOCK, CURRENT_COMMAND
    if SOCK.fileno() != -1:
        print("Sending "+str(command))
        SOCK.sendto(command, SERVER)
        CURRENT_COMMAND = command
    else:
        print("Unable to send command! Closed socket!")

# Handles CTRL+C event for clean exit
def signal_handler(sig, frame):
    global RUN
    RUN = False
signal.signal(signal.SIGINT, signal_handler)



#########################
### THREAD FUNCTIONS ####
#########################

# Sends out a heartbeat signal every 10 seconds
def threadFunctionHeartbeat():
    global RUN, SOCK
    while (RUN):
        # Make sure it hasn't been closed
        if SOCK.fileno() != -1:
            SOCK.sendto(b'HEARTBEAT', SERVER)
            print("Sent heartbeat")
        time.sleep(10)
   
# Called when a key on the keyboard is pressed   
def handlerOnPress(key):
    global PRESSED_CTR, PRESSED_KEYS, CURRENT_COMMAND, SOCK
    if key in PRESSED_KEYS:
        return
    PRESSED_KEYS.add(key)
    try:
        if key == keyboard.Key.up:
            PRESSED_COMMANDS.append(C_FORWARD)
            sendCommand(C_FORWARD)
        elif key == keyboard.Key.down:
            PRESSED_COMMANDS.append(C_BACKWARD)
            sendCommand(C_BACKWARD)
        elif key == keyboard.Key.left:
            PRESSED_COMMANDS.append(C_LEFT)
            sendCommand(C_LEFT)
        elif key == keyboard.Key.right:
            PRESSED_COMMANDS.append(C_RIGHT)
            sendCommand(C_RIGHT)
        elif key == keyboard.Key.backspace:
            sendCommand(C_STOP)
        if key == keyboard.Key.esc:
            return False  # Stop listener when 'Esc' is pressed
    except AttributeError:
        pass
    
# Called when a key on the keyboard is released
def handlerOnRelease(key):
    global PRESSED_CTR, PRESSED_KEYS, CURRENT_COMMAND, SOCK
    PRESSED_KEYS.discard(key)
    try:
        if key in (keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right):
            PRESSED_COMMANDS.remove(getKeyAsByteLetter(key))
            if len(PRESSED_COMMANDS) == 0:
                sendCommand(C_STOP)
            else:
                sendCommand(PRESSED_COMMANDS[-1])          
    except AttributeError:
        pass

# Starts the keyboard listener on the handlerOnPress and handlerOnRelease functions
# and exits when the ESC key is pressed (manually or by script)
def threadFunctionKeyboardListener():
    print("Waiting for input...")
    with keyboard.Listener(on_press=handlerOnPress, on_release=handlerOnRelease) as listener:
        listener.join()

# Sends out the last sent command every 0.25 seconds to support the
# stop-on-disconnect functionality of the rover
def threadFunctionCommandLoop():
    global RUN, SOCK
    while (RUN):
        # Make sure it hasn't been closed
        if SOCK.fileno() != -1:
            # Send current control
            SOCK.sendto(CURRENT_COMMAND, SERVER)
        time.sleep(0.25)
    
 
 
#######################
### STATE FUNCTIONS ###
#######################

# Handles the S_START_HB state
def handleStateStartHeartbeat(hbThread):
    global STATE
    hbThread.start()
    STATE = S_WAIT_HELLO
  
# Handles the S_WAIT_HELLO state  
def handleStateWaitHello():
    global STATE
    # Wait for hello message or timeout
    ready, _, _ = select.select([SOCK], [], [], 1.0)
    if ready:
        data, addr = SOCK.recvfrom(1024)
        if data.decode() == "HELLO":
            STATE = S_START_GSTRM

# Handles the S_START_GSTRM state    
def handleStateStartGStream():
    global STATE, SOCK
    # Close socket first so that GStreamer can use it
    SOCK.close()
    print("Starting video with command: " + RECEIVE_VIDEO)
    process = subprocess.Popen(RECEIVE_VIDEO, shell=True, stdout=subprocess.DEVNULL)
    # Sleep to let video start before relinquishing control
    time.sleep(1)
    STATE = S_START_KYBRD
    return process

# Handles the S_START_KYBRD state  
def handleStateStartKeyboard(kbThread):
    global STATE, SOCK
    # Redefine socket (Gstream will create it for receiving, so we need to re-create it for shared receiving and sending)
    SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    SOCK.bind(("0.0.0.0", 12345))
    kbThread.start()
    STATE = S_START_CMD_LOOP
    
# Handles the S_START_CMD_LOOP state  
def handleStateStartCommandLoop(clThread):
    global STATE
    clThread.start()
    STATE = S_WAIT_EXIT
 
# Handles the S_WAIT_EXIT state   
def handleStateWaitExit(process):
    global STATE
    # Wait for video to close
    process.wait()
    print("Video exited")
    STATE = S_EXIT
    pass



######################
### MAIN EXECUTION ###
######################

# Declare threads, processes
hbThread = threading.Thread(target=threadFunctionHeartbeat)         
kbThread = threading.Thread(target=threadFunctionKeyboardListener)
clThread = threading.Thread(target=threadFunctionCommandLoop)
process = -1

# Run state machine until CTRL+C or video is closed
while (RUN):
    if STATE == S_START_HB:
        handleStateStartHeartbeat(hbThread)
    elif STATE == S_WAIT_HELLO:
        handleStateWaitHello()
    elif STATE == S_START_GSTRM:
        process = handleStateStartGStream()
    elif STATE == S_START_KYBRD:
        handleStateStartKeyboard(kbThread)
    elif STATE == S_START_CMD_LOOP:
        handleStateStartCommandLoop(clThread)
    elif STATE == S_WAIT_EXIT:
        handleStateWaitExit(process)
    elif STATE == S_EXIT:
        RUN = False # Simply exit the state machine loop
    else:
        print("Got invalid state!")

# Normal exit
print("Began clean exit process")

print("Waiting for heartbeat thread to join...")
if hbThread.is_alive():
    hbThread.join()

print("Waiting for keyboard listener thread to join...")
if kbThread.is_alive():
    kb = keyboard.Controller()
    kb.press(keyboard.Key.esc)
    kbThread.join()

print("Waiting for command loop thread to join...")
if clThread.is_alive():
    clThread.join()

print("Waiting for GStreamer process to exit...")
if process != -1 and process.poll() is None:
    process.wait()

print("Sending shutdown signal to server...")
# Ensure we have the socket (edge clase where it may be closed)
SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
SOCK.bind(("0.0.0.0", 12345))
# Now send data
SOCK.sendto(b'Z', SERVER)
SOCK.sendto(b'Z', SERVER)
SOCK.sendto(b'Z', SERVER)
# Now close socket frfr
SOCK.close()

print("Finished clean exit process!")
sys.exit(0)