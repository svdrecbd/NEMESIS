#include "DeviceManager.hpp"
#include "Protocol.hpp"
#include "TapEngine.hpp"

static Protocol protocol;
static TapEngine tapper;

void DeviceManager::init() {
    tapper.init();
    protocol.begin(115200);
    protocol.sendHello();
}

void DeviceManager::loop() {
    handleSerial();
    serviceHeartbeat();
}

void DeviceManager::handleSerial() {
    HostCommand cmd;
    while (protocol.poll(cmd)) {
        switch (cmd.type) {
            case HostCommand::Type::TapManual:
                tapper.tapOnce();
                protocol.sendAck("tap.ack");
                break;
            case HostCommand::Type::MotorEnable:
                tapper.enableMotor(true);
                protocol.sendAck("motor.enabled");
                break;
            case HostCommand::Type::MotorDisable:
                tapper.enableMotor(false);
                protocol.sendAck("motor.disabled");
                break;
            case HostCommand::Type::Stepsize:
                tapper.setStepsize(cmd.stepsize);
                protocol.sendAck("config.stepsize");
                break;
            case HostCommand::Type::ArmJog:
                tapper.jog(cmd.direction_up, cmd.jog_steps);
                protocol.sendAck("arm.jogged");
                break;
            default:
                protocol.sendAck("cmd.unknown");
                break;
        }
    }
}

void DeviceManager::serviceHeartbeat() {
    // TODO: periodically emit heartbeat once timers are in place.
}
