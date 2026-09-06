#ifndef RELAY_MANAGER_H
#define RELAY_MANAGER_H

#include <Arduino.h>

// Centralized relay control. Handles active-low wiring and safe boot behaviour.
//
// RELAY_ACTIVE_LOW == true:
//     ON  -> digitalWrite HIGH? no: ON  -> LOW
//     OFF -> HIGH
// otherwise:
//     ON  -> HIGH, OFF -> LOW
//
// The relay is forced OFF during begin() so the socket never powers up
// unexpectedly on boot.
class RelayManager {
public:
    RelayManager();
    void begin(int pin, bool activeLow);
    void begin();
    bool setState(bool on);
    bool getState();
    int getPin();
    bool isActiveLow();

private:
    int _pin;
    bool _activeLow;
    bool _state;
    void _apply();
};

#endif // RELAY_MANAGER_H