# Wiring & Power Notes

- **Stepper driver**: SparkFun Big Easy Driver powered from 12 V supply. Connect `STEP`→D2, `DIR`→D3, `MS1..3`→D4..D6, `ENABLE`→D7.
- **Indicators**: Sync LED on D8, fault LED on D9. Adjust in firmware if your board differs.
- **Inputs**: Mode switch on D10 (pull-up), manual tap button on D11 (pull-up). Debounced in firmware.
- **Grounding**: Tie Arduino/UNIT1 ground to the driver ground and host PC ground reference.
- **Future UNIT1**: Reserve UART header (TX/RX/GND) and I2C (SDA/SCL) for telemetry accessories.
