#pragma once

#include <stdint.h>

// High-level orchestration for UNIT1 firmware. The DeviceManager wires together
// the tap engine, scheduler, and host protocol. Implementation is in src/DeviceManager.cpp.
class DeviceManager {
public:
    void init();
    void loop();

private:
    void handleSerial();
    void serviceHeartbeat();
};
