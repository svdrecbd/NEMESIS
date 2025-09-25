#include <Arduino.h>
#include "DeviceManager.hpp"

static DeviceManager manager;

void setup() {
    manager.init();
}

void loop() {
    manager.loop();
}
