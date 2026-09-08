#include <Arduino.h>

#include "config.h"
#include "pzem_manager.h"
#include "wifi_manager.h"
#include "config_server.h"
#include "api_client.h"
#include "relay_manager.h"

PZEMManager pzem;
WiFiManager wifi;
ConfigServer configServer;
APIClient api;
RelayManager relay;

unsigned long lastPzemRead = 0;
unsigned long lastSend = 0;
unsigned long lastWifiCheck = 0;
unsigned long lastRegisterAttempt = 0;
unsigned long lastControlPoll = 0;
bool deviceRegistered = false;
bool laptopConnected = false;
PZEMData lastReading;

// Last successfully executed command ID (in-memory idempotency guard). The
// backend should never re-return it, but if it does we re-acknowledge safely
// instead of toggling the relay again.
String lastExecutedCommandId = "NO_COMMAND";

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);
    Serial.println("\n\n=== SMART ENERGY ESP32-S3 ===");

    // Safety: drive the relay OFF first, before the network is brought up.
    // This guarantees GPIO 40 can never power a socket during boot.
    relay.begin();

    pzem.begin();
    wifi.beginAP();

    // Apply the restored/persisted backend URL (if any) to the API client.
    configServer.begin();
    if (configServer.isConfigured()) {
        api.setBaseUrl(configServer.getBackendUrl());
    }
    configServer.onConfigured(onBackendConfigured);

    Serial.println("\n========================================");
    Serial.println("SMART ENERGY ASSISTANT");
    Serial.println("NETWORK CONFIGURATION");
    Serial.println("========================================");
    Serial.printf("ESP32 AP IP:   %s\n", wifi.getLocalIP().c_str());
    Serial.printf("Backend URL:   %s\n", api.isConfigured() ? api.baseUrl().c_str() : "(not configured - waiting for desktop EXE)");
    Serial.printf("Device ID:     %s\n", DEVICE_ID);
    Serial.printf("Relay GPIO:    %d (Active-Low: %s)\n", RELAY_CHANNEL_1_PIN, RELAY_ACTIVE_LOW ? "YES" : "NO");
    Serial.println("========================================\n");
}

void loop() {
    unsigned long now = millis();

    // ---------- Config server: serves POST /api/backend/config + GET /api/backend/status ----------
    configServer.tick();

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

    // ---------- Register device (only when a laptop is connected AND a backend URL is configured) ----------
    if (laptopConnected && api.isConfigured() && !deviceRegistered && (now - lastRegisterAttempt >= DEVICE_REGISTER_RETRY_MS)) {
        lastRegisterAttempt = now;
        deviceRegistered = api.registerDevice(DEVICE_ID, DEVICE_NAME);
        if (!deviceRegistered) {
            Serial.println("[SYS] Registration failed, will retry next cycle");
        }
    }

    // ---------- Periodic measurement upload (connected + registered + configured only) ----------
    if (laptopConnected && api.isConfigured() && deviceRegistered && lastReading.valid && (now - lastSend >= MEASUREMENT_INTERVAL_MS)) {
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

    // ---------- Control command polling (connected + registered + configured only) ----------
    if (laptopConnected && api.isConfigured() && deviceRegistered && (now - lastControlPoll >= CONTROL_POLL_INTERVAL_MS)) {
        lastControlPoll = now;
        handleControlPoll();
    }
}

// Called by the ConfigServer whenever the desktop EXE pushes a new backend URL.
// Resets the registration state and triggers an immediate registration attempt.
void onBackendConfigured() {
    Serial.println("[SYS] New backend URL received - resetting registration state");
    deviceRegistered = false;
    api.setBaseUrl(configServer.getBackendUrl());
    // Bump lastRegisterAttempt so the very next loop attempts registration now.
    lastRegisterAttempt = millis() - DEVICE_REGISTER_RETRY_MS;
    lastSend = 0;
    lastControlPoll = 0;
}

// Fetch any pending command, execute the relay, and acknowledge.
// Non-blocking: returns quickly; PZEM monitoring continues in parallel.
void handleControlPoll() {
    ControlCommandData cmd = api.pollControlCommand(DEVICE_ID);
    if (!cmd.hasCommand) {
        return;
    }

    // Idempotency: never re-toggle the relay for an already-executed command.
    if (cmd.commandId == lastExecutedCommandId) {
        Serial.printf("[CONTROL] Duplicate command %s; re-acknowledging safely\n", cmd.commandId.c_str());
        api.acknowledgeControl(DEVICE_ID, cmd.commandId, true,
                               relay.getState() ? "ON" : "OFF", "Already executed (idempotent ack)");
        return;
    }

    bool success = false;
    String relayState = "UNKNOWN";
    String message = "Relay execution failed";

    if (cmd.channel == 1) {
        if (cmd.action == "ON") {
            relay.setState(true);
            success = true;
            relayState = "ON";
            message = "Relay switched ON successfully";
        } else if (cmd.action == "OFF") {
            relay.setState(false);
            success = true;
            relayState = "OFF";
            message = "Relay switched OFF successfully";
        } else {
            message = "Unknown action: " + cmd.action;
        }
    } else {
        // Unknown channel: DO NOT perform any GPIO action.
        message = "Unsupported relay channel";
    }

    if (success) {
        lastExecutedCommandId = cmd.commandId;
    }

    api.acknowledgeControl(DEVICE_ID, cmd.commandId, success, relayState, message);
    Serial.printf("[CONTROL] Executed command %s: success=%s state=%s\n",
                  cmd.commandId.c_str(), success ? "true" : "false", relayState.c_str());
}