/******************************************************************************

v8 Added random (Poisson) mode with run summary; overhauled timing logic and refactored sketch for robustness.
v7 change enable and disable so that they apply after every step i.e. if it is in enable
then it always is left in enable after a step and if it is in disable mode then it is always left 
disabled after a step
v6 fixed direction of taps to go down first and then up
v5 added raise and lower function
v4  control settings for automatic mode added

overall contorl flow is based on the previous electromaget version of the Stentor habituation
written by Wallace Marshall with contributions to software from Kyle Barlow, Patrick Harrigan, & Salvador Escobedo

motor control was based on the:  "SparkFun Big Easy Driver Basic Demo"
Toni Klopfenstein @ SparkFun Electronics
February 2015
https://github.com/sparkfun/Big_Easy_Driver

Simple demo sketch to demonstrate how 5 digital pins can drive a bipolar stepper motor,
using the Big Easy Driver (https://www.sparkfun.com/products/12859). Also shows the ability to change
microstep size, and direction of motor movement.

Example based off of demos by Brian Schmalz (designer of the Big Easy Driver).
http://www.schmalzhaus.com/EasyDriver/Examples/EasyDriverExamples.html
******************************************************************************/

// NOTE: This sketch is copied from the legacy Arduino tapper (v8) so NEMESIS can
// continue to control existing rigs while UNIT1 is developed. Keep behavioural
// changes minimal; new hardware enhancements should target the UNIT1 project.

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>

// Typed Constants for Pins & Configuration
const uint8_t PIN_STEP = 2;
const uint8_t PIN_DIR = 3;
const uint8_t PIN_MS1 = 4;
const uint8_t PIN_MS2 = 5;
const uint8_t PIN_MS3 = 6;
const uint8_t PIN_ENABLE = 7;
const uint8_t PIN_GREEN_LED = 8;
const uint8_t PIN_RED_LED = 9;
const uint8_t PIN_BUTTON = 11;
const uint8_t PIN_MODE_SWITCH = 10;

const int LARGE_TAP_STEPS = 9;
const int MANUAL_JOG_STEPS = 9;
const unsigned long DEBOUNCE_MS = 50; // Debounce time for hardware inputs

// Global Variables & Data Structures

// System State Enumeration
enum class Mode { Idle, Periodic, Random };
Mode currentMode = Mode::Idle;
bool motorEnabled = false;
bool configuredModeIsRandom = false; // Remembers which mode to enter

// State Tracking for Non-Blocking Debounce
bool lastSwitchState = HIGH;
bool lastButtonState = HIGH;
unsigned long lastSwitchDebounceTime = 0;
unsigned long lastButtonDebounceTime = 0;

// Session Data Structure
struct Session {
  unsigned long startTime = 0;
  unsigned long nextTapTime = 0;
  int tapCount = 0;
};
Session session;

// Mode-specific Parameters
int stepsize = 4; // Default to 1/8th microstep
double periodicDelayMsFloat = 10000.0;
unsigned long periodicDelayMsBase = 10000;
double periodicDelayMsFraction = 0.0;
double periodicDelayMsAccumulator = 0.0;
float lambda = 0.0; // Taps per millisecond for random mode

// Forward Declarations
void checkHardwareInputs();
void checkSerialInput();
void checkTimedPulse();
void startTimedMode();
void stopTimedMode();
void processHostConfig();
void configurePeriodicMode();
void configureRandomMode();
void enableMotor();
void disableMotor();
void raiseArm();
void lowerArm();
void deliverTap();
void executeTapProfile(int steps, int ms1, int ms2, int ms3);
void printFormattedTime(unsigned long total_ms);
void resetBEDPins();
void printHelp();

// SETUP FUNCTION
void setup() {
  const uint8_t motorPins[] = {PIN_STEP, PIN_DIR, PIN_MS1, PIN_MS2, PIN_MS3, PIN_ENABLE};
  for (uint8_t pin : motorPins) {
    pinMode(pin, OUTPUT);
  }

  pinMode(PIN_GREEN_LED, OUTPUT);
  pinMode(PIN_RED_LED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_MODE_SWITCH, INPUT_PULLUP);

  randomSeed(analogRead(0));

  resetBEDPins();
  Serial.begin(9600);
  Serial.println(F("Begin Stentor Habituation Device operation"));
  printHelp();
}

// MAIN LOOP - Clean and non-blocking
void loop() {
  checkHardwareInputs();
  checkSerialInput();
  checkTimedPulse();
}


// Task-specific functions called by loop()

void checkHardwareInputs() {
  unsigned long currentTime = millis();

  // Check Mode Switch (with independent timer)
  if (currentTime - lastSwitchDebounceTime > DEBOUNCE_MS) {
    bool currentSwitchState = digitalRead(PIN_MODE_SWITCH);
    if (currentSwitchState != lastSwitchState) {
      lastSwitchDebounceTime = currentTime;
      if (currentSwitchState == HIGH) {
        Serial.println(F("EVENT:SWITCH,ON"));
      } else {
        Serial.println(F("EVENT:SWITCH,OFF"));
      }
      if (currentSwitchState == HIGH && currentMode == Mode::Idle) {
        startTimedMode();
      } else if (currentSwitchState == LOW && currentMode != Mode::Idle) {
        stopTimedMode();
      }
      lastSwitchState = currentSwitchState;
    }
  }

  // Check Button (with independent timer)
  if (currentTime - lastButtonDebounceTime > DEBOUNCE_MS) {
    bool currentButtonState = digitalRead(PIN_BUTTON);
    if (currentButtonState != lastButtonState) {
       lastButtonDebounceTime = currentTime;
       if (currentButtonState == LOW) {
         Serial.println(F("Button pressed, delivering manual tap."));
         deliverTap();
       }
       lastButtonState = currentButtonState;
    }
  }
}

void checkSerialInput() {
  if (Serial.available()) {
    char userInput = Serial.read();
    switch(userInput) {
      case 'i': configurePeriodicMode(); break;
      case 'p': configureRandomMode();   break;
      case 'e': enableMotor();           break;
      case 'd': disableMotor();          break;
      case 'C':
      case 'c':
        processHostConfig();
        break;
      case 't':
      case 'T':
        Serial.println(F("Host tap command received."));
        deliverTap();
        break;
      case 'r': raiseArm();              break;
      case 'l': lowerArm();              break;
      case 'h': printHelp();             break;
      case '1': case '2': case '3': case '4': case '5':
        stepsize = userInput - '0';
        Serial.print(F("CONFIG:STEPSIZE="));
        Serial.println(stepsize);
        break;
    }
  }
}

void processHostConfig() {
  char buffer[48];
  size_t len = Serial.readBytesUntil('\n', buffer, sizeof(buffer) - 1);
  buffer[len] = '\0';

  // Trim leading whitespace/separators
  char *cursor = buffer;
  while (*cursor == ' ' || *cursor == ',' || *cursor == ':' || *cursor == '\r') {
    cursor++;
  }
  if (*cursor == '\0') {
    Serial.println(F("CONFIG:ERR,EMPTY"));
    return;
  }

  char modeChar = toupper(*cursor++);
  while (*cursor == ' ' || *cursor == ',' ) { cursor++; }
  if (modeChar == 'C') {
    if (*cursor == '\0') {
      Serial.println(F("CONFIG:ERR,MODE"));
      return;
    }
    modeChar = toupper(*cursor++);
    while (*cursor == ' ' || *cursor == ',' ) { cursor++; }
  }

  char *stepToken = cursor;
  while (*cursor && *cursor != ' ' && *cursor != ',' ) { cursor++; }
  if (*cursor) { *cursor++ = '\0'; }
  while (*cursor == ' ' || *cursor == ',' ) { cursor++; }

  char *valueToken = cursor;
  while (*cursor && *cursor != ' ' && *cursor != ',' ) { cursor++; }
  *cursor = '\0';

  int parsedStep = atoi(stepToken);
  if (parsedStep < 1) parsedStep = 1;
  if (parsedStep > 5) parsedStep = 5;

  double parsedValue = atof(valueToken);
  bool ok = true;

  if (currentMode != Mode::Idle) {
    stopTimedMode();
  }

  if (modeChar == 'P') {
    configuredModeIsRandom = false;
    stepsize = parsedStep;
    if (parsedValue <= 0.0) {
      ok = false;
    }
    if (ok) {
      periodicDelayMsFloat = parsedValue * 1000.0;
      if (periodicDelayMsFloat < 1.0) {
        periodicDelayMsFloat = 1.0;
      }
      periodicDelayMsBase = (unsigned long)periodicDelayMsFloat;
      periodicDelayMsFraction = periodicDelayMsFloat - periodicDelayMsBase;
      periodicDelayMsAccumulator = 0.0;
      Serial.print(F("CONFIG:OK,MODE=P,PERIOD_MS="));
      Serial.println(periodicDelayMsFloat, 4);
    }
  } else if (modeChar == 'R') {
    configuredModeIsRandom = true;
    stepsize = parsedStep;
    if (parsedValue <= 0.0) {
      ok = false;
    }
    if (ok) {
      lambda = parsedValue / 60000.0f;
      Serial.print(F("CONFIG:OK,MODE=R,RATE_PER_MIN="));
      Serial.println(parsedValue, 4);
    }
  } else {
    ok = false;
  }

  if (!ok) {
    Serial.println(F("CONFIG:ERR,PARAM"));
    return;
  }

  // Ensure any running timed mode is stopped before applying new settings
  session.tapCount = 0;
  session.nextTapTime = 0;
  Serial.print(F("CONFIG:STEPSIZE="));
  Serial.println(stepsize);
  Serial.println(F("CONFIG:DONE"));
}

void checkTimedPulse() {
  if (currentMode != Mode::Idle && millis() >= session.nextTapTime) {
    unsigned long tapStart = millis();

    if (session.tapCount == 0) {
      session.startTime = tapStart;
      if (currentMode == Mode::Random) { // Only print for random mode
        Serial.println(F("Run started. First tap delivered at T+ 0m 0s 0ms"));
      }
    }

    deliverTap();
    session.tapCount++;

    if (currentMode == Mode::Random && session.tapCount > 1) {
      Serial.print(F("Random tap delivered at T+ "));
      printFormattedTime(tapStart - session.startTime);
      Serial.println();
    }

    if (currentMode == Mode::Random) {
      float U = random(1, 10001) / 10000.0f;
      unsigned long T = (unsigned long)(-log(U) / lambda);
      if (T == 0UL) {
        T = 1UL;
      }
      session.nextTapTime = tapStart + T;
      Serial.print(F("Next random tap scheduled in "));
      Serial.print(T / 1000.0f, 3);
      Serial.println(F(" seconds.\n"));
    } else { // Periodic Mode
      unsigned long delayMs = periodicDelayMsBase;
      periodicDelayMsAccumulator += periodicDelayMsFraction;
      if (periodicDelayMsAccumulator >= 1.0) {
        unsigned long extra = (unsigned long)periodicDelayMsAccumulator;
        delayMs += extra;
        periodicDelayMsAccumulator -= extra;
      }
      if (delayMs < 1UL) {
        delayMs = 1UL;
      }
      session.nextTapTime = tapStart + delayMs;
    }
  }
}

// Functions for Starting and Stopping Timed Mode

void startTimedMode() {
  digitalWrite(PIN_GREEN_LED, HIGH);
  currentMode = configuredModeIsRandom ? Mode::Random : Mode::Periodic;
  Serial.println(F("--- TIMED MODE ACTIVATED ---"));
  Serial.println(F("Tapping..."));
  Serial.println(F("EVENT:MODE_ACTIVATED"));

  unsigned long tapStart = millis();
  deliverTap();
  session.startTime = tapStart;
  session.tapCount = 1;

  if (currentMode == Mode::Random) {
    float U = random(1, 10001) / 10000.0f;
    unsigned long T = (unsigned long)(-log(U) / lambda);
    if (T == 0UL) {
      T = 1UL;
    }
    session.nextTapTime = tapStart + T;
    Serial.print(F("Next random tap scheduled in "));
    Serial.print(T / 1000.0f, 3);
    Serial.println(F(" seconds.\n"));
  } else {
    periodicDelayMsAccumulator = 0.0;
    unsigned long delayMs = periodicDelayMsBase;
    if (delayMs < 1UL) {
        delayMs = 1UL;
    }
    session.nextTapTime = tapStart + delayMs;
  }
}

void stopTimedMode() {
  currentMode = Mode::Idle;
  digitalWrite(PIN_GREEN_LED, LOW);
  digitalWrite(PIN_RED_LED, LOW);
  Serial.println(F("--- TIMED MODE DEACTIVATED ---"));
  Serial.println(F("EVENT:MODE_DEACTIVATED"));

  if (session.tapCount > 0) {
    unsigned long elapsedTime = millis() - session.startTime;
    Serial.println(F("\n--- RUN SUMMARY ---"));
    Serial.print(F("Mode: "));
    Serial.println(configuredModeIsRandom ? F("Random (Poisson)") : F("Periodic"));
    Serial.print(F("Total Run Time: "));
    printFormattedTime(elapsedTime);
    Serial.println();
    Serial.print(F("Total Taps Delivered: "));
    Serial.println(session.tapCount);
    if (configuredModeIsRandom && elapsedTime > 0) {
      float observedRatePerMin = ((float)session.tapCount * 1000.0f / elapsedTime) * 60.0f;
      Serial.print(F("Observed Average Rate: "));
      Serial.print(observedRatePerMin, 2);
      Serial.println(F(" taps/min"));
    }
    Serial.println(F("---------------------\n"));
  }
}


// Functions for Handling Serial Commands

void configurePeriodicMode() {
  stopTimedMode();
  configuredModeIsRandom = false;
  Serial.println(F("\n--- Configuring Periodic Mode ---"));
  delay(100);
  Serial.println(F("Enter the step size (tap power): 1, 2, 3, 4, or 5"));
  Serial.println(F("where 1=full, 2=half, 3=1/4, 4=1/8, 5=1/16"));
  while (Serial.available() == 0) {}
  stepsize = Serial.parseInt();
  Serial.print(F("Step size set to ")); Serial.println(stepsize);

  delay(100);
  Serial.println(F("Enter the stimulus period in MINUTES:"));
  while (Serial.available() == 0) {}
  float time_minutes = Serial.parseFloat();
  periodicDelayMsFloat = time_minutes * 60.0f * 1000.0f;
  if (periodicDelayMsFloat < 1.0f) {
    periodicDelayMsFloat = 1.0f;
  }
  periodicDelayMsBase = (unsigned long)periodicDelayMsFloat;
  periodicDelayMsFraction = periodicDelayMsFloat - periodicDelayMsBase;
  periodicDelayMsAccumulator = 0.0;
  Serial.print(F("Time period set to ")); Serial.print(time_minutes); Serial.println(F(" minutes."));
  Serial.print(F("Which corresponds to a delay of ")); Serial.print(periodicDelayMsFloat, 4); Serial.println(F(" ms."));
  Serial.println(F("Configuration complete. Use the switch to start/stop.\n"));
}

void configureRandomMode() {
  stopTimedMode();
  configuredModeIsRandom = true;
  Serial.println(F("\n--- Configuring Random (Poisson) Mode ---"));
  delay(100);
  Serial.println(F("Enter the step size (tap power): 1, 2, 3, 4, or 5"));
  Serial.println(F("where 1=full, 2=half, 3=1/4, 4=1/8, 5=1/16"));
  while (Serial.available() == 0) {}
  stepsize = Serial.parseInt();
  Serial.print(F("Step size set to: ")); Serial.println(stepsize);

  delay(100);
  Serial.println(F("Enter the AVERAGE stimulus rate in taps per MINUTE:"));
  while (Serial.available() == 0) {}
  float taps_per_minute = Serial.parseFloat();
  lambda = taps_per_minute / 60000.0f;
  Serial.print(F("Average rate set to ")); Serial.print(taps_per_minute); Serial.println(F(" taps/min."));

  if (taps_per_minute > 0) {
    float avg_delay_ms = (1.0f / taps_per_minute) * 60.0f * 1000.0f;
    Serial.print(F("Which corresponds to an AVERAGE delay of "));
    Serial.print((long)avg_delay_ms);
    Serial.println(F(" ms."));
  }

  Serial.println(F("Configuration complete. Use the switch to start/stop.\n"));
}

void enableMotor() {
  digitalWrite(PIN_ENABLE, LOW);
  Serial.println(F("Motor enabled."));
  motorEnabled = true;
}

void disableMotor() {
  digitalWrite(PIN_ENABLE, HIGH);
  Serial.println(F("Motor disabled."));
  motorEnabled = false;
}

void raiseArm() {
  Serial.println(F("Microstep up."));
  digitalWrite(PIN_DIR, LOW);
  digitalWrite(PIN_MS1, HIGH); digitalWrite(PIN_MS2, HIGH); digitalWrite(PIN_MS3, HIGH);
  digitalWrite(PIN_ENABLE, LOW);
  for (int i = 0; i < MANUAL_JOG_STEPS; i++) { digitalWrite(PIN_STEP, HIGH); delay(1); digitalWrite(PIN_STEP, LOW); delay(1); }
  resetBEDPins();
  Serial.print(F("EVENT:TAP,"));
  Serial.println(millis());
}

void lowerArm() {
  Serial.println(F("Microstep down."));
  digitalWrite(PIN_DIR, HIGH);
  digitalWrite(PIN_MS1, HIGH); digitalWrite(PIN_MS2, HIGH); digitalWrite(PIN_MS3, HIGH);
  digitalWrite(PIN_ENABLE, LOW);
  for (int i = 0; i < MANUAL_JOG_STEPS; i++) { digitalWrite(PIN_STEP, HIGH); delay(1); digitalWrite(PIN_STEP, LOW); delay(1); }
  resetBEDPins();
}

// HELPER FUNCTIONS

void deliverTap() {
  digitalWrite(PIN_ENABLE, LOW);

  switch(stepsize) {
    case 1: executeTapProfile(LARGE_TAP_STEPS, LOW, LOW, LOW); break;    // Full step
    case 2: executeTapProfile(LARGE_TAP_STEPS, HIGH, LOW, LOW); break;   // Half step
    case 3: executeTapProfile(LARGE_TAP_STEPS, LOW, HIGH, LOW); break;   // 1/4th step
    case 4: executeTapProfile(LARGE_TAP_STEPS, HIGH, HIGH, LOW); break;  // 1/8th step
    case 5: executeTapProfile(LARGE_TAP_STEPS, HIGH, HIGH, HIGH); break; // 1/16th step
    default: Serial.println(F("Invalid step size"));
  }

  resetBEDPins();
  Serial.print(F("EVENT:TAP,"));
  Serial.println(millis());
}

void executeTapProfile(int steps, int ms1, int ms2, int ms3) {
  digitalWrite(PIN_MS1, ms1);
  digitalWrite(PIN_MS2, ms2);
  digitalWrite(PIN_MS3, ms3);

  digitalWrite(PIN_DIR, HIGH); // Tap down
  for (int i = 0; i < steps; i++) {
    digitalWrite(PIN_STEP, HIGH); delay(1);
    digitalWrite(PIN_STEP, LOW); delay(1);
  }
  digitalWrite(PIN_DIR, LOW); // Tap up
  for (int i = 0; i < steps; i++) {
    digitalWrite(PIN_STEP, HIGH); delay(1);
    digitalWrite(PIN_STEP, LOW); delay(1);
  }
}

void printFormattedTime(unsigned long total_ms) {
  unsigned long all_seconds = total_ms / 1000;
  unsigned long all_minutes = all_seconds / 60;
  unsigned long display_ms = total_ms % 1000;
  unsigned long display_s = all_seconds % 60;

  Serial.print(all_minutes);
  Serial.print(F("m "));
  Serial.print(display_s);
  Serial.print(F("s "));
  Serial.print(display_ms);
  Serial.print(F("ms"));
}

void resetBEDPins() {
  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_DIR, LOW);
  digitalWrite(PIN_MS1, LOW);
  digitalWrite(PIN_MS2, LOW);
  digitalWrite(PIN_MS3, LOW);
  if (motorEnabled) {
    digitalWrite(PIN_ENABLE, LOW);
  } else {
    digitalWrite(PIN_ENABLE, HIGH);
  }
}

void printHelp() {
  // Using an array of FlashStringHelper pointers saves RAM
  const __FlashStringHelper* helpLines[] = {
    F("\nEnter character for control option:"),
    F("i. Initialize periodic (automatic) mode settings."),
    F("p. Initialize random (Poisson) mode settings."),
    F("e. Enable motor to lock arm."),
    F("d. Disable motor so you can move the arm."),
    F("r. Raise the arm by a step."),
    F("l. Lower the arm by a step."),
    F("h. Print this help menu."),
    F("\nUse the physical switch to start/stop the selected timed mode.\n")
  };

  for (auto msg : helpLines) {
    Serial.println(msg);
  }
}
