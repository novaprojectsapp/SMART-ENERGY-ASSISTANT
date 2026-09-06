#include "relay_manager.h"
#include "config.h"

RelayManager::RelayManager()
    : _pin(-1), _activeLow(RELAY_ACTIVE_LOW), _state(false) {
}

void RelayManager::begin() {
    begin(RELAY_CHANNEL_1_PIN, RELAY_ACTIVE_LOW);
}

void RelayManager::begin(int pin, bool activeLow) {
    _pin = pin;
    _activeLow = activeLow;

    if (_pin < 0) {
        Serial.println("[RELAY] No relay pin configured - relay disabled");
        return;
    }

    pinMode(_pin, OUTPUT);

    // Force the relay OFF safely during boot (never power a socket unexpectedly).
    _state = false;
    _apply();

    Serial.println("[RELAY] Relay initialized");
    Serial.printf("[RELAY] Pin GPIO%d, Active-Low: %s\n", _pin, _activeLow ? "YES" : "NO");
    Serial.printf("[RELAY] Initial state: OFF\n");
}

bool RelayManager::setState(bool on) {
    _state = on;
    _apply();
    Serial.printf("[RELAY] %s\n", on ? "ON" : "OFF");
    return true;
}

bool RelayManager::getState() {
    return _state;
}

int RelayManager::getPin() {
    return _pin;
}

bool RelayManager::isActiveLow() {
    return _activeLow;
}

void RelayManager::_apply() {
    if (_pin < 0) {
        return;
    }
    // For an active-low relay, ON means write LOW; otherwise write HIGH.
    uint8_t level = _activeLow ? (_state ? LOW : HIGH) : (_state ? HIGH : LOW);
    digitalWrite(_pin, level);
    Serial.printf("[RELAY] GPIO%d -> %s (logical %s)\n",
                  _pin, level == HIGH ? "HIGH" : "LOW", _state ? "ON" : "OFF");
}