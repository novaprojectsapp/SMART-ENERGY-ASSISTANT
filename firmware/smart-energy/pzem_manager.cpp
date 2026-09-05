#include "pzem_manager.h"
#include "config.h"

PZEMManager::PZEMManager()
    : _pzem(Serial1, PZEM_RX_PIN, PZEM_TX_PIN)
    , _lastReadValid(false) {
}

void PZEMManager::begin() {
    Serial1.begin(PZEM_SERIAL_BAUD, SERIAL_8N1, PZEM_RX_PIN, PZEM_TX_PIN);
    Serial.println("[PZEM] UART1 initialized");
    Serial.printf("[PZEM] RX: GPIO%d, TX: GPIO%d, Baud: %d\n", PZEM_RX_PIN, PZEM_TX_PIN, PZEM_SERIAL_BAUD);
}

PZEMData PZEMManager::read() {
    PZEMData data;
    data.voltage = _pzem.voltage();
    data.current = _pzem.current();
    data.power = _pzem.power();
    data.energy = _pzem.energy();
    data.frequency = _pzem.frequency();
    data.powerFactor = _pzem.pf();
    data.valid = !isnan(data.voltage);

    _lastReadValid = data.valid;
    return data;
}

void PZEMManager::printReading(const PZEMData& data) {
    if (!data.valid) {
        Serial.println("[PZEM] WARNING: No valid data - check PZEM connection");
        return;
    }

    Serial.println("[PZEM] ---- Reading ----");
    Serial.printf("[PZEM] Voltage:      %.1f V\n", data.voltage);
    Serial.printf("[PZEM] Current:      %.3f A\n", data.current);
    Serial.printf("[PZEM] Power:        %.1f W\n", data.power);
    Serial.printf("[PZEM] Energy:       %.4f kWh\n", data.energy);
    Serial.printf("[PZEM] Frequency:    %.1f Hz\n", data.frequency);
    Serial.printf("[PZEM] Power Factor: %.2f\n", data.powerFactor);
    Serial.println("[PZEM] -----------------");
}

bool PZEMManager::isCommunicationOk() {
    return _lastReadValid;
}
