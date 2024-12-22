#include "pi_gpio_wrapper.h"

// GPIO pins
#define LEFT_DIR_1 27
#define LEFT_DIR_2 22
#define RIGHT_DIR_1 23
#define RIGHT_DIR_2 24
#define PWM 18

int initCircuitry()
{
  gpioInitialise();
  if (gpioSetMode(LEFT_DIR_1, PI_OUTPUT))
    return -1;
  if (gpioSetMode(LEFT_DIR_2, PI_OUTPUT))
    return -1;
  if (gpioSetMode(RIGHT_DIR_1, PI_OUTPUT))
    return -1;
  if (gpioSetMode(RIGHT_DIR_2, PI_OUTPUT))
    return -1;
  if (gpioHardwarePWM(PWM, PI_HW_PWM_MIN_FREQ, 1000000))
    return -1;
  return 0;
}

int uninitCircuitry()
{
  if (gpioWrite(LEFT_DIR_1, 0))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 0))
    return -1;
  if (gpioHardwarePWM(PWM, PI_HW_PWM_MIN_FREQ, 0))
    return -1;
  gpioTerminate();
  return 0;
}

int driveForward()
{
  if (gpioWrite(LEFT_DIR_1, 1))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 1))
    return -1;
  return 0;
}

int driveBackward()
{
  if (gpioWrite(LEFT_DIR_1, 0))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 1))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 1))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 0))
    return -1;
  return 0;
}

int driveLeft()
{
  if (gpioWrite(LEFT_DIR_1, 0))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 1))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 1))
    return -1;
  return 0;
}

int driveRight()
{
  if (gpioWrite(LEFT_DIR_1, 1))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 1))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 0))
    return -1;
  return 0;
}

int driveStop()
{
  if (gpioWrite(LEFT_DIR_1, 0))
    return -1;
  if (gpioWrite(LEFT_DIR_2, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_1, 0))
    return -1;
  if (gpioWrite(RIGHT_DIR_2, 0))
    return -1;
  return 0;
}