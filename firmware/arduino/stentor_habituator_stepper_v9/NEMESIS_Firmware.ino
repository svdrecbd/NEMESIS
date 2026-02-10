/******************************************************************************
 NEMESIS Firmware — Stentor Habituator Tapper
 Maintains backwards compatibility with the legacy Arduino rig while UNIT1
 matures. Supports periodic, Poisson, and host-driven replay ("Replicant")
 modes plus the manual tap and jog commands required by the desktop app.
******************************************************************************/

// NOTE: This sketch mirrors the legacy tapper behaviour so existing hardware
// continues to work during the UNIT1 transition. Keep behavioural changes
// minimal; target new hardware features at UNIT1 instead.

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
const int MIN_STEPSIZE = 1;
const int MAX_STEPSIZE = 5;
const int DEFAULT_STEPSIZE = 4;
const unsigned long SERIAL_BAUD = 9600;
const unsigned long DEBOUNCE_MS = 50; // Debounce time for hardware inputs
const unsigned long SERIAL_CONFIG_TIMEOUT_MS = 5000;
const unsigned long SERIAL_PROMPT_DELAY_MS = 100;
const size_t CONFIG_BUFFER_SIZE = 48;
const uint8_t SERIAL_TIME_PRECISION = 3;
const uint8_t PERIOD_PRECISION = 4;
const unsigned long SERIAL_POLL_DELAY_MS = 1;
const float MIN_INTERVAL_MS = 1.0f;
const unsigned long MS_PER_SEC = 1000UL;
const unsigned long MICROS_PER_MS = 1000UL;
const unsigned long MICROS_PER_SEC = 1000000UL;
const float SECONDS_PER_MIN = 60.0f;
const float MS_PER_MIN = 60000.0f;
const unsigned long MIN_INTERVAL_US = 1000UL;
const float MIN_PERIOD_US_FLOAT = 1.0f;
const float RANDOM_U_DENOM = 10000.0f;
const long RANDOM_U_MIN = 1;
const long RANDOM_U_MAX_EXCLUSIVE = 10001;
const uint8_t ENTROPY_SAMPLE_COUNT = 64;
const uint16_t ENTROPY_JITTER_MASK = 0x7;
const uint32_t ENTROPY_LCG_A = 1664525UL;
const uint32_t ENTROPY_LCG_C = 1013904223UL;
const uint32_t ENTROPY_FALLBACK_SEED = 0x1D872B41UL;
const unsigned long DEFAULT_PERIOD_US = 1000000UL;
const double DEFAULT_PERIOD_US_FLOAT = 1000000.0;
const unsigned long STEP_PULSE_DELAY_MS = 1;

// Global Variables & Data Structures

// System State Enumeration
enum class Mode { Idle, Periodic, Random };
Mode currentMode = Mode::Idle;
bool motorEnabled = false;
bool configuredModeIsRandom = false; // Remembers which mode to enter
bool hostReplayMode = false;         // Host-driven replicant replay
bool hostReplayActive = false;
bool rngSeedLocked = false;
unsigned long lastRandomSeed = 0;

// State Tracking for Non-Blocking Debounce
bool lastSwitchState = HIGH;
bool lastButtonState = HIGH;
unsigned long lastSwitchDebounceTime = 0;
unsigned long lastButtonDebounceTime = 0;

// Session Data Structure
struct Session {
  unsigned long startTimeMs = 0;
  unsigned long startTimeMicros = 0;
  unsigned long nextTapMicros = 0;
  int tapCount = 0;
};
Session session;

// Mode-specific Parameters
int stepsize = DEFAULT_STEPSIZE; // Default to 1/8th microstep
double periodicDelayUsFloat = DEFAULT_PERIOD_US_FLOAT;
unsigned long periodicDelayUsBase = DEFAULT_PERIOD_US;
double periodicDelayUsFraction = 0.0;
double periodicDelayUsAccumulator = 0.0;
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
bool waitForSerialInput(unsigned long timeout_ms);
uint32_t collectEntropySeed();
void applyRandomSeed(unsigned long seed, bool lockSeed);
void seedRngFromEntropy();

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
  // Sync initial hardware states to avoid spurious taps on boot/reset.
  lastSwitchState = digitalRead(PIN_MODE_SWITCH);
  lastButtonState = digitalRead(PIN_BUTTON);
  unsigned long now = millis();
  lastSwitchDebounceTime = now;
  lastButtonDebounceTime = now;

  seedRngFromEntropy();

  resetBEDPins();
  Serial.begin(SERIAL_BAUD);
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
        if (hostReplayMode) {
          if (!hostReplayActive) {
            hostReplayActive = true;
            Serial.println(F("EVENT:MODE_ACTIVATED"));
          }
        } else if (currentMode == Mode::Idle) {
          startTimedMode();
        }
      } else {
        Serial.println(F("EVENT:SWITCH,OFF"));
        if (hostReplayMode) {
          if (hostReplayActive) {
            hostReplayActive = false;
            Serial.println(F("EVENT:MODE_DEACTIVATED"));
          }
        } else if (currentMode != Mode::Idle) {
          stopTimedMode();
        }
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
  char buffer[CONFIG_BUFFER_SIZE];
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

  if (modeChar == 'S') {
    unsigned long parsedSeed = strtoul(stepToken, nullptr, 10);
    if (parsedSeed == 0UL) {
      seedRngFromEntropy();
      Serial.println(F("CONFIG:OK,SEED=AUTO"));
    } else {
      applyRandomSeed(parsedSeed, true);
      Serial.println(F("CONFIG:OK,SEED=FIXED"));
    }
    Serial.print(F("CONFIG:SEED_VALUE="));
    Serial.println(lastRandomSeed);
    Serial.println(F("CONFIG:DONE"));
    return;
  }

  int parsedStep = atoi(stepToken);
  if (parsedStep < MIN_STEPSIZE) parsedStep = MIN_STEPSIZE;
  if (parsedStep > MAX_STEPSIZE) parsedStep = MAX_STEPSIZE;

  double parsedValue = atof(valueToken);
  bool ok = true;

  if (currentMode != Mode::Idle) {
    stopTimedMode();
  }

  if (modeChar == 'P') {
    hostReplayMode = false;
    hostReplayActive = false;
    configuredModeIsRandom = false;
    stepsize = parsedStep;
    if (parsedValue <= 0.0) {
      ok = false;
    }
    if (ok) {
      periodicDelayUsFloat = parsedValue * MICROS_PER_SEC;
      if (periodicDelayUsFloat < MIN_PERIOD_US_FLOAT) {
        periodicDelayUsFloat = MIN_PERIOD_US_FLOAT;
      }
      periodicDelayUsBase = (unsigned long)periodicDelayUsFloat;
      periodicDelayUsFraction = periodicDelayUsFloat - periodicDelayUsBase;
      periodicDelayUsAccumulator = 0.0;
      Serial.print(F("CONFIG:OK,MODE=P,PERIOD_MS="));
      Serial.println(periodicDelayUsFloat / MICROS_PER_MS, PERIOD_PRECISION);
    }
  } else if (modeChar == 'R') {
    hostReplayMode = false;
    hostReplayActive = false;
    configuredModeIsRandom = true;
    stepsize = parsedStep;
    if (parsedValue <= 0.0) {
      ok = false;
    }
    if (ok) {
      lambda = parsedValue / MS_PER_MIN;
      Serial.print(F("CONFIG:OK,MODE=R,RATE_PER_MIN="));
      Serial.println(parsedValue, PERIOD_PRECISION);
    }
  } else if (modeChar == 'H') {
    hostReplayMode = true;
    hostReplayActive = false;
    configuredModeIsRandom = false;
    stepsize = parsedStep;
    Serial.print(F("CONFIG:OK,MODE=H"));
    if (parsedValue > 0.0) {
      Serial.print(F(",TAPS="));
      Serial.println((long)parsedValue);
    } else {
      Serial.println();
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
  session.nextTapMicros = 0;
  Serial.print(F("CONFIG:STEPSIZE="));
  Serial.println(stepsize);
  Serial.println(F("CONFIG:DONE"));
}

void checkTimedPulse() {
  if (currentMode == Mode::Idle) {
    return;
  }
  unsigned long nowMicros = micros();
  if (session.tapCount > 0) {
    long delta = (long)(nowMicros - session.nextTapMicros);
    if (delta < 0) {
      return;
    }
  }

  unsigned long tapStartMicros = nowMicros;
  unsigned long tapStartMs = tapStartMicros / MICROS_PER_MS;

  if (session.tapCount == 0) {
    session.startTimeMs = tapStartMs;
    session.startTimeMicros = tapStartMicros;
    if (currentMode == Mode::Random) {
      Serial.println(F("Run started. First tap delivered at T+ 0m 0s 0ms"));
    }
  }

  deliverTap();
  session.tapCount++;

  if (currentMode == Mode::Random && session.tapCount > 1) {
    Serial.print(F("Random tap delivered at T+ "));
    printFormattedTime(tapStartMs - session.startTimeMs);
    Serial.println();
  }

  if (currentMode == Mode::Random) {
    float U = random(RANDOM_U_MIN, RANDOM_U_MAX_EXCLUSIVE) / RANDOM_U_DENOM;
    double intervalMs = -log(U) / lambda;  // milliseconds
    if (intervalMs < MIN_INTERVAL_MS) {
      intervalMs = MIN_INTERVAL_MS;
    }
    unsigned long intervalUs = (unsigned long)(intervalMs * MICROS_PER_MS);
    if (intervalUs == 0UL) {
      intervalUs = MIN_INTERVAL_US;
    }
    session.nextTapMicros += intervalUs;
    Serial.print(F("Next random tap scheduled in "));
    Serial.print(intervalMs / MS_PER_SEC, SERIAL_TIME_PRECISION);
    Serial.println(F(" seconds.\n"));
  } else {
    unsigned long delayUs = periodicDelayUsBase;
    periodicDelayUsAccumulator += periodicDelayUsFraction;
    if (periodicDelayUsAccumulator >= 1.0) {
      unsigned long extra = (unsigned long)periodicDelayUsAccumulator;
      delayUs += extra;
      periodicDelayUsAccumulator -= extra;
    }
    if (delayUs < MIN_INTERVAL_US) {
      delayUs = MIN_INTERVAL_US;
    }
    session.nextTapMicros += delayUs;
  }
}

// Functions for Starting and Stopping Timed Mode

void startTimedMode() {
  digitalWrite(PIN_GREEN_LED, HIGH);
  currentMode = configuredModeIsRandom ? Mode::Random : Mode::Periodic;
  if (currentMode == Mode::Random && !rngSeedLocked) {
    seedRngFromEntropy();
  }
  Serial.println(F("--- TIMED MODE ACTIVATED ---"));
  Serial.println(F("Tapping..."));
  Serial.println(F("EVENT:MODE_ACTIVATED"));

  unsigned long tapStartMicros = micros();
  unsigned long tapStartMs = tapStartMicros / MICROS_PER_MS;
  deliverTap();
  session.startTimeMs = tapStartMs;
  session.startTimeMicros = tapStartMicros;
  session.tapCount = 1;

  if (currentMode == Mode::Random) {
    float U = random(RANDOM_U_MIN, RANDOM_U_MAX_EXCLUSIVE) / RANDOM_U_DENOM;
    double intervalMs = -log(U) / lambda;
    if (intervalMs < MIN_INTERVAL_MS) {
      intervalMs = MIN_INTERVAL_MS;
    }
    unsigned long intervalUs = (unsigned long)(intervalMs * MICROS_PER_MS);
    if (intervalUs == 0UL) {
      intervalUs = MIN_INTERVAL_US;
    }
    session.nextTapMicros = tapStartMicros + intervalUs;
    Serial.print(F("Next random tap scheduled in "));
    Serial.print(intervalMs / MS_PER_SEC, SERIAL_TIME_PRECISION);
    Serial.println(F(" seconds.\n"));
  } else {
    periodicDelayUsAccumulator = 0.0;
    unsigned long delayUs = periodicDelayUsBase;
    if (delayUs < MIN_INTERVAL_US) {
        delayUs = MIN_INTERVAL_US;
    }
    session.nextTapMicros = tapStartMicros + delayUs;
  }
}

void stopTimedMode() {
  currentMode = Mode::Idle;
  digitalWrite(PIN_GREEN_LED, LOW);
  digitalWrite(PIN_RED_LED, LOW);
  Serial.println(F("--- TIMED MODE DEACTIVATED ---"));
  Serial.println(F("EVENT:MODE_DEACTIVATED"));

  if (session.tapCount > 0) {
    unsigned long elapsedTime = millis() - session.startTimeMs;
    Serial.println(F("\n--- RUN SUMMARY ---"));
    Serial.print(F("Mode: "));
    Serial.println(configuredModeIsRandom ? F("Random (Poisson)") : F("Periodic"));
    Serial.print(F("Total Run Time: "));
    printFormattedTime(elapsedTime);
    Serial.println();
    Serial.print(F("Total Taps Delivered: "));
    Serial.println(session.tapCount);
    if (configuredModeIsRandom && elapsedTime > 0) {
      float observedRatePerMin = ((float)session.tapCount * MS_PER_SEC / elapsedTime) * SECONDS_PER_MIN;
      Serial.print(F("Observed Average Rate: "));
      Serial.print(observedRatePerMin, 2);
      Serial.println(F(" taps/min"));
    }
    Serial.println(F("---------------------\n"));
  }
}


// Functions for Handling Serial Commands

bool waitForSerialInput(unsigned long timeout_ms) {
  unsigned long start = millis();
  while (Serial.available() == 0) {
    if (millis() - start >= timeout_ms) {
      return false;
    }
    delay(SERIAL_POLL_DELAY_MS);
  }
  return true;
}

void configurePeriodicMode() {
  stopTimedMode();
  configuredModeIsRandom = false;
  Serial.println(F("\n--- Configuring Periodic Mode ---"));
  delay(SERIAL_PROMPT_DELAY_MS);
  Serial.println(F("Enter the step size (tap power): 1, 2, 3, 4, or 5"));
  Serial.println(F("where 1=full, 2=half, 3=1/4, 4=1/8, 5=1/16"));
  if (!waitForSerialInput(SERIAL_CONFIG_TIMEOUT_MS)) {
    Serial.println(F("CONFIG:ERR,TIMEOUT"));
    return;
  }
  stepsize = Serial.parseInt();
  Serial.print(F("Step size set to ")); Serial.println(stepsize);

  delay(SERIAL_PROMPT_DELAY_MS);
  Serial.println(F("Enter the stimulus period in MINUTES:"));
  if (!waitForSerialInput(SERIAL_CONFIG_TIMEOUT_MS)) {
    Serial.println(F("CONFIG:ERR,TIMEOUT"));
    return;
  }
  float time_minutes = Serial.parseFloat();
  periodicDelayUsFloat = time_minutes * SECONDS_PER_MIN * MICROS_PER_SEC;
  if (periodicDelayUsFloat < MIN_PERIOD_US_FLOAT) {
    periodicDelayUsFloat = MIN_PERIOD_US_FLOAT;
  }
  periodicDelayUsBase = (unsigned long)periodicDelayUsFloat;
  periodicDelayUsFraction = periodicDelayUsFloat - periodicDelayUsBase;
  periodicDelayUsAccumulator = 0.0;
  Serial.print(F("Time period set to ")); Serial.print(time_minutes); Serial.println(F(" minutes."));
  Serial.print(F("Which corresponds to a delay of "));
  Serial.print(periodicDelayUsFloat / MICROS_PER_MS, PERIOD_PRECISION);
  Serial.println(F(" ms."));
  Serial.println(F("Configuration complete. Use the switch to start/stop.\n"));
}

void configureRandomMode() {
  stopTimedMode();
  configuredModeIsRandom = true;
  Serial.println(F("\n--- Configuring Random (Poisson) Mode ---"));
  delay(SERIAL_PROMPT_DELAY_MS);
  Serial.println(F("Enter the step size (tap power): 1, 2, 3, 4, or 5"));
  Serial.println(F("where 1=full, 2=half, 3=1/4, 4=1/8, 5=1/16"));
  if (!waitForSerialInput(SERIAL_CONFIG_TIMEOUT_MS)) {
    Serial.println(F("CONFIG:ERR,TIMEOUT"));
    return;
  }
  stepsize = Serial.parseInt();
  Serial.print(F("Step size set to: ")); Serial.println(stepsize);

  delay(SERIAL_PROMPT_DELAY_MS);
  Serial.println(F("Enter the AVERAGE stimulus rate in taps per MINUTE:"));
  if (!waitForSerialInput(SERIAL_CONFIG_TIMEOUT_MS)) {
    Serial.println(F("CONFIG:ERR,TIMEOUT"));
    return;
  }
  float taps_per_minute = Serial.parseFloat();
  lambda = taps_per_minute / MS_PER_MIN;
  Serial.print(F("Average rate set to ")); Serial.print(taps_per_minute); Serial.println(F(" taps/min."));

  if (taps_per_minute > 0) {
    float avg_delay_ms = (1.0f / taps_per_minute) * SECONDS_PER_MIN * MS_PER_SEC;
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
  for (int i = 0; i < MANUAL_JOG_STEPS; i++) { digitalWrite(PIN_STEP, HIGH); delay(STEP_PULSE_DELAY_MS); digitalWrite(PIN_STEP, LOW); delay(STEP_PULSE_DELAY_MS); }
  resetBEDPins();
  Serial.print(F("EVENT:TAP,"));
  Serial.println((double)micros() / MICROS_PER_MS, SERIAL_TIME_PRECISION);
}

void lowerArm() {
  Serial.println(F("Microstep down."));
  digitalWrite(PIN_DIR, HIGH);
  digitalWrite(PIN_MS1, HIGH); digitalWrite(PIN_MS2, HIGH); digitalWrite(PIN_MS3, HIGH);
  digitalWrite(PIN_ENABLE, LOW);
  for (int i = 0; i < MANUAL_JOG_STEPS; i++) { digitalWrite(PIN_STEP, HIGH); delay(STEP_PULSE_DELAY_MS); digitalWrite(PIN_STEP, LOW); delay(STEP_PULSE_DELAY_MS); }
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
  Serial.println((double)micros() / MICROS_PER_MS, SERIAL_TIME_PRECISION);
}

void executeTapProfile(int steps, int ms1, int ms2, int ms3) {
  digitalWrite(PIN_MS1, ms1);
  digitalWrite(PIN_MS2, ms2);
  digitalWrite(PIN_MS3, ms3);

  digitalWrite(PIN_DIR, HIGH); // Tap down
  for (int i = 0; i < steps; i++) {
    digitalWrite(PIN_STEP, HIGH); delay(STEP_PULSE_DELAY_MS);
    digitalWrite(PIN_STEP, LOW); delay(STEP_PULSE_DELAY_MS);
  }
  digitalWrite(PIN_DIR, LOW); // Tap up
  for (int i = 0; i < steps; i++) {
    digitalWrite(PIN_STEP, HIGH); delay(STEP_PULSE_DELAY_MS);
    digitalWrite(PIN_STEP, LOW); delay(STEP_PULSE_DELAY_MS);
  }
}

void printFormattedTime(unsigned long total_ms) {
  unsigned long all_seconds = total_ms / MS_PER_SEC;
  unsigned long all_minutes = all_seconds / static_cast<unsigned long>(SECONDS_PER_MIN);
  unsigned long display_ms = total_ms % MS_PER_SEC;
  unsigned long display_s = all_seconds % static_cast<unsigned long>(SECONDS_PER_MIN);

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
    F("\nUse the physical switch to start/stop the selected timed mode."),
    F("Host seed override: send config 'S,<seed>,0' (seed=0 returns to auto entropy).\n")
  };

  for (auto msg : helpLines) {
    Serial.println(msg);
  }
}

uint32_t collectEntropySeed() {
  uint32_t seed = 0xA5A5A5A5UL;
  for (uint8_t i = 0; i < ENTROPY_SAMPLE_COUNT; i++) {
    unsigned long t0 = micros();
    int noise = analogRead(0);
    unsigned long t1 = micros();
    seed ^= (uint32_t)(noise & 0x03FFU) << (i % 16U);
    seed ^= (uint32_t)t0;
    seed = (seed * ENTROPY_LCG_A) + ENTROPY_LCG_C + (uint32_t)(t1 - t0);
    delayMicroseconds((unsigned int)((t1 & ENTROPY_JITTER_MASK) + 1U));
  }
  seed ^= (uint32_t)micros();
  seed ^= ((uint32_t)millis() << 16);
  if (seed == 0UL) {
    seed = ENTROPY_FALLBACK_SEED;
  }
  return seed;
}

void applyRandomSeed(unsigned long seed, bool lockSeed) {
  if (seed == 0UL) {
    seed = ENTROPY_FALLBACK_SEED;
  }
  randomSeed(seed);
  lastRandomSeed = seed;
  rngSeedLocked = lockSeed;
}

void seedRngFromEntropy() {
  applyRandomSeed((unsigned long)collectEntropySeed(), false);
  Serial.print(F("RNG:SEED,AUTO,"));
  Serial.println(lastRandomSeed);
}
