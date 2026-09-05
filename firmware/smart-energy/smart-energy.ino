#include <Arduino.h>

#include "config.h"
#include "pzem_manager.h"
#include "wifi_manager.h"
#include "api_client.h"

PZEMManager pzem;
WiFiManager wifi;
APIClient api;

unsigned long lastPzemRead = 0;
unsigned long lastSend = 0;
unsigned long lastWifiCheck = 0;
unsigned long lastRegisterAttempt = 0;
bool deviceRegistered = false;
bool laptopConnected = false;
PZEMData lastReading;

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);
    Serial.println("\n\n=== SMART ENERGY ESP32-S3 ===");

    pzem.begin();
    wifi.beginAP();

    Serial.println("\n========================================");
    Serial.println("SMART ENERGY ASSISTANT");
    Serial.println("NETWORK CONFIGURATION");
    Serial.println("========================================");
    Serial.printf("ESP32 AP IP:   %s\n", wifi.getLocalIP().c_str());
    Serial.printf("Backend IP:    %s\n", BACKEND_HOST);
    Serial.printf("Backend Port:  %d\n", BACKEND_PORT);
    Serial.printf("Device ID:     %s\n", DEVICE_ID);
    Serial.println("========================================\n");
}

void loop() {
    unsigned long now = millis();

    // ---------- Periodic PZEM reading (always runs, independent of Wi-Fi) ----------
    if (now - lastPzemRead >= PZEM_READ_INTERVAL_MS) {
        lastPzemRead = now;
        lastReading = pzem.read();
        pzem.printReading(lastReading);
    }

    // ---------- Periodic Wi-Fi client status check ----------
    if (now - lastWifiCheck >= WIFI_CHECK_INTERVAL_MS) {
        lastWifiCheck = now;
        bool current = wifi.getConnectedClients() > 0;
        if (current != laptopConnected) {
            laptopConnected = current;
            if (laptopConnected) {
                Serial.printf("[WIFI] Client Connected: YES (%d stations)\n", wifi.getConnectedClients());
                lastRegisterAttempt = 0;
            } else {
                Serial.println("[WIFI] Client Connected: NO - continuing PZEM monitoring");
            }
        } else {
            Serial.printf("[WIFI] Client Connected: %s (%d stations)\n",
                          laptopConnected ? "YES" : "NO", wifi.getConnectedClients());
        }
    }

    // ---------- Register device (only when laptop is connected) ----------
    if (laptopConnected && !deviceRegistered && (now - lastRegisterAttempt >= DEVICE_REGISTER_RETRY_MS)) {
        lastRegisterAttempt = now;
        deviceRegistered = api.registerDevice(DEVICE_ID, DEVICE_NAME);
        if (!deviceRegistered) {
            Serial.println("[SYS] Registration failed, will retry next cycle");
        }
    }

    // ---------- Periodic measurement upload (connected + registered only) ----------
    if (laptopConnected && deviceRegistered && lastReading.valid && (now - lastSend >= MEASUREMENT_INTERVAL_MS)) {
        lastSend = now;
        bool ok = api.sendMeasurement(
            DEVICE_ID,
            lastReading.voltage,
            lastReading.current,
            lastReading.power,
            lastReading.energy,
            lastReading.frequency,
            lastReading.powerFactor);
        Serial.printf("[SYS] Send result: %s\n\n", ok ? "OK" : "FAILED (will retry next cycle)");
    }
}