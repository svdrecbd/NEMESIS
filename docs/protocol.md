# UNIT1 Serial Protocol Draft

This document sketches the UART messaging contract between NEMESIS (host) and UNIT1 (firmware).
It deliberately overlaps with the legacy Arduino behaviour so the UI can auto-detect the target.

## Physical Layer
- Default: 115200 baud, 8N1 (tune later once MCU chosen).
- All frames start with `{` and end with `}\n` to stay human-readable and easy to debug.
- JSON objects for readability during development; may migrate to CBOR once stable.

## Boot / Handshake
1. UNIT1 emits `{"hello":"unit1","fw":"0.1.0","proto":1}` within 250 ms of boot or connect.
2. Host replies with `{"host":"nemesis","version":"1.0-rc1","mode":"pure"}`.
3. UNIT1 acknowledges with `{"ack":"hello"}` and begins accepting commands.

If the host sends the legacy `h` command, UNIT1 should still print the short help text to remain backward-compatible.

## Commands (Host → UNIT1)
| Command              | Example Payload                                                | Purpose |
|----------------------|----------------------------------------------------------------|---------|
| `run.start`          | `{ "cmd":"run.start", "mode":"periodic", "period_ms":10000, "stepsize":4 }` | Begin a scheduled run. UNIT1 arms timers and responds with `run.started` ack. |
| `run.stop`           | `{ "cmd":"run.stop" }`                                       | Halt active run, release timers, respond with `run.stopped`. |
| `tap.manual`         | `{ "cmd":"tap.manual" }`                                     | Execute a single tap immediately, respond with `tap.ack`. |
| `motor.enable`       | `{ "cmd":"motor.enable" }`                                   | Energize driver; respond with `motor.state`. |
| `motor.disable`      | `{ "cmd":"motor.disable" }`                                  | De-energize driver; respond with `motor.state`. |
| `arm.jog`            | `{ "cmd":"arm.jog", "direction":"up", "steps":9 }`        | Half-step jog used by UI buttons; respond with `arm.jogged`. |
| `config.stepsize`    | `{ "cmd":"config.stepsize", "value":4 }`                    | Update microstep profile for subsequent taps. |
| `config.seed`        | `{ "cmd":"config.seed", "value":12345 }`                    | Apply RNG seed for Poisson scheduling (host optional). |

## Events (UNIT1 → Host)
| Event                | Payload Example                                                | Notes |
|----------------------|----------------------------------------------------------------|-------|
| `run.started`        | `{ "event":"run.started", "run_id":"unit1-abc123", "ts":123456 }` | Confirms run activation with firmware-side timestamp. |
| `run.stopped`        | `{ "event":"run.stopped", "reason":"operator" }`          | Sent on stop or fault. |
| `tap.ack`            | `{ "event":"tap.ack", "tap_uuid":"...","host_sent":123456,"firmware_exec":123789 }` | Provides precise execute time for logging. |
| `motor.state`        | `{ "event":"motor.state", "enabled":true }`                 | Broadcast whenever state changes. |
| `fault`              | `{ "event":"fault", "code":"overcurrent", "detail":"..." }` | Critical conditions requiring host action. |
| `heartbeat`          | `{ "event":"heartbeat", "uptime_ms":456789 }`               | Optional periodic health message. |

## Compatibility Layer
- UNIT1 should respond to single-character commands (`e`, `d`, `t`, `r`, `l`, `1`..`5`, `h`) for legacy testing. Each command maps internally to the JSON pathway and UNIT1 emits an echo message so the host can detect the new firmware.
- If the host sends a JSON frame to the Arduino sketch, the Arduino will ignore it; thus, successful parse of `{` indicates UNIT1.

## Open Questions
- Final baud rate and flow control (hardware vs software).
- Whether UNIT1 precomputes Poisson delays or expects host-supplied schedule.
- Integration with hardware safety circuits (limit switches, force sensors).
- CRC/Checksum: may wrap frames in SLIP or append CRC16 once JSON stabilises.
