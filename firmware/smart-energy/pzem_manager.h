#ifndef PZEM_MANAGER_H
#define PZEM_MANAGER_H

#include <Arduino.h>
#include <PZEM004Tv30.h>

struct PZEMData {
    float voltage;
    float current;
    float power;
    float energy;
    float frequency;
    float powerFactor;
    bool valid;
};

class PZEMManager {
public:
    PZEMManager();
    void begin();
    PZEMData read();
    void printReading(const PZEMData& data);
    bool isCommunicationOk();

private:
    PZEM004Tv30 _pzem;
    bool _lastReadValid;
};

#endif // PZEM_MANAGER_H
