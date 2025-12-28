#include "Protocol.hpp"
#include <Arduino.h>

constexpr uint8_t DEFAULT_JOG_STEPS = 9;

void Protocol::begin(unsigned long baud) {
    Serial.begin(baud);
}

bool Protocol::poll(HostCommand &cmd) {
    cmd.type = HostCommand::Type::Unknown;
    if (!Serial.available()) {
        return false;
    }

    int incoming = Serial.peek();
    if (incoming == '{') {
        // TODO: parse JSON frame for UNIT1 pure mode.
        Serial.read(); // consume for now
        return false;
    }

    char ch = static_cast<char>(Serial.read());
    switch (ch) {
        case 't':
            cmd.type = HostCommand::Type::TapManual;
            return true;
        case 'e':
            cmd.type = HostCommand::Type::MotorEnable;
            return true;
        case 'd':
            cmd.type = HostCommand::Type::MotorDisable;
            return true;
        case 'r':
            cmd.type = HostCommand::Type::ArmJog;
            cmd.direction_up = true;
            cmd.jog_steps = DEFAULT_JOG_STEPS;
            return true;
        case 'l':
            cmd.type = HostCommand::Type::ArmJog;
            cmd.direction_up = false;
            cmd.jog_steps = DEFAULT_JOG_STEPS;
            return true;
        case '1': case '2': case '3': case '4': case '5':
            cmd.type = HostCommand::Type::Stepsize;
            cmd.stepsize = static_cast<uint8_t>(ch - '0');
            return true;
        default:
            return false;
    }
}

void Protocol::sendHello() {
    Serial.println(F("{\"hello\":\"unit1\",\"fw\":\"0.0.0\",\"proto\":0}"));
}

void Protocol::sendAck(const char *event) {
    Serial.print(F("{\"ack\":\""));
    Serial.print(event);
    Serial.println(F("\"}"));
}
