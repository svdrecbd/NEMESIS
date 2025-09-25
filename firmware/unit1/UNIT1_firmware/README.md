# UNIT1 Controller (Pure Mode)

UNIT1 is the next-generation MCU that will replace the Arduino tapper. NEMESIS will
speak a richer protocol when "Pure Mode" is enabled. This directory scaffolds the
firmware project without locking in a specific toolchain yet.

## Goals
- Deterministic tap timing (hardware-timed pulses, host sends schedule hints).
- Structured UART protocol (self-describing JSON-ish or CBOR frames).
- Bi-directional telemetry (tap acknowledgements, motor/limit status, firmware id).
- Backward-compatible command aliases so NEMESIS can fall back to the legacy single-letter verbs if needed.

## Layout
- `include/` — Header files shared across the firmware modules.
- `src/` — Implementation files. `main.cpp` currently hosts the run loop skeleton.
- Protocol spec now lives in `docs/protocol.md` at the repo root.
- `CMakeLists.txt` (optional, TBD) — Add once the target MCU and toolchain are chosen.

## Next Steps
1. Finalize the serial protocol: handshake, run control, tap ack payloads, health updates.
2. Choose MCU/toolchain (e.g., STM32 + Zephyr, RP2040 + Pico SDK, ESP32 + ESP-IDF) and drop in the appropriate build files.
3. Flesh out `DeviceManager` and `TapEngine` implementations in `src/`.
4. Hook hardware abstraction to actual GPIO/timer/driver peripherals.
