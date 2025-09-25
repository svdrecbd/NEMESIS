#pragma once

#include <stdint.h>

// Encapsulates GPIO/timer operations for raising/lowering the tapper arm.
class TapEngine {
public:
    void init();
    void setStepsize(uint8_t microstep); // 1..5 equivalent
    void enableMotor(bool on);
    void tapOnce();
    void jog(bool up, uint8_t steps);
};
