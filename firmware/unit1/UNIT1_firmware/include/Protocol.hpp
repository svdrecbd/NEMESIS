#pragma once

#include <stdint.h>

// Lightweight placeholder for the structured protocol parser/encoder.
struct HostCommand {
    enum class Type {
        Unknown,
        RunStart,
        RunStop,
        TapManual,
        MotorEnable,
        MotorDisable,
        ArmJog,
        Stepsize,
        Seed
    } type = Type::Unknown;

    // Raw payload fields; refine when protocol solidifies.
    uint32_t period_ms = 0;
    uint8_t stepsize = 4;
    bool direction_up = true;
    uint8_t jog_steps = 9;
};

class Protocol {
public:
    void begin(unsigned long baud);
    bool poll(HostCommand &cmd);
    void sendHello();
    void sendAck(const char *event);
};
