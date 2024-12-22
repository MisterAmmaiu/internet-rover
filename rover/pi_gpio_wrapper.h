#include <pigpio.h>     // GPIO, PWM


// Properly initializes the GPIO pins and PWM
int initCircuitry();

// Propery un-initializes the GPIO pins and PWM
int uninitCircuitry();

// Drive all wheels forward
int driveForward();

// Drive all wheels backward
int driveBackward();

// Drive left wheels backward, right wheels forward
int driveLeft();

// Drive left wheels forward, right wheels backward
int driveRight();

// Stop all wheels
int driveStop();