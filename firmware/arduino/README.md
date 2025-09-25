# Legacy Arduino Tapper (Big Easy Driver)

This is the existing sketch that NEMESIS drives today. Keep this folder for any maintenance fixes while UNIT1 is under development.

- Board: Arduino Uno (or compatible ATmega328P)
- Driver: SparkFun Big Easy Driver
- Serial protocol: single-character commands (`t/e/d/r/l/1..5/h` etc.) consumed by NEMESIS' "Arduino" backend.

Build/upload with the Arduino IDE or CLI:

```bash
arduino-cli compile --fqbn arduino:avr:uno
arduino-cli upload --port /dev/ttyUSB0 --fqbn arduino:avr:uno
```

The implementation lives in `stentor_habituator_stepper_v9/NEMESIS_Firmware.ino` and is intentionally kept close to the historical v8 sketch for continuity.
