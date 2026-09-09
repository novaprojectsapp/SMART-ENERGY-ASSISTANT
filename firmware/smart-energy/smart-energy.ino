#include <Arduino.h>

#include "config.h"
#include "pzem_manager.h"
#include "wifi_manager.h"
#include "config_server.h"
#include "backend_discovery.h"
#include "api_client.h"
#include "relay_manager.h"

PZEMManager pzem;
WiFiManager wifi;
ConfigServer configServer;
BackendDiscovery discovery;
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

// Backend link state machine, driven by UDP discovery + HTTP config push.
enum BackendState {
    ST_WAITING_FOR_BACKEND,   // no laptop backend known yet
    ST_BACKEND_DISCOVERED,    // got a valid backend (UDP/HTTP), applying it
    ST_REGISTERING_DEVICE,    // sending device registration
    ST_STREAMING              // registered, uploading PZEM readings
};
BackendState netState = ST_WAITING_FOR_BACKEND;

void setState(BackendState newState) {
    if (netState == newState) {
        return;
    }
    netState = newState;
    switch (netState) {
        case ST_WAITING_FOR_BACKEND:
            Serial.println("\n[SYS] Waiting for Smart Energy backend...");
            break;
        case ST_BACKEND_DISCOVERED:
            Serial.println("[SYS] Backend discovered - applying configuration");
            break;
        case ST_REGISTERING_DEVICE:
            Serial.println("[SYS] Registering device with backend...");
            break;
        case ST_STREAMING:
            Serial.println("[SYS] Backend online - streaming PZEM readings");
            break;
    }
}

void applyBackendUrl(const String& url) {
    deviceRegistered = false;
    api.setBaseUrl(url);
    api.resetFailures();
    lastRegisterAttempt = millis() - DEVICE_REGISTER_RETRY_MS;
    lastSend = 0;
    lastControlPoll = 0;
}

// Called by the ConfigServer whenever the desktop EXE pushes a new backend URL
// (HTTP POST /api/backend/config). Resets registration state and registers now.
void onBackendConfigured() {
    Serial.println("[SYS] New backend URL received - resetting registration state");
    applyBackendUrl(configServer.getBackendUrl());
    setState(ST_BACKEND_DISCOVERED);
}

// Called by the UDP discovery listener with a valid host/port.
void onBackendDiscovered(const String& host, uint16_t port) {
    String url = "http://" + host + ":" + String(port);
    Serial.printf("\nBackend discovered: %s\n", url.c_str());
    applyBackendUrl(url);
    configServer.applyDiscoveredBackend(url);
    setState(ST_BACKEND_DISCOVERED);
}

// Backend is repeatedly unreachable: invalidate the discovery, keep PZEM +
// UDP listening, and return to WAITING_FOR_BACKEND (no reboot required).
void handleBackendLost() {
    Serial.println("[SYS] Backend unreachable - returning to WAITING_FOR_BACKEND");
    api.setBaseUrl("");
    api.resetFailures();
    deviceRegistered = false;
    setState(ST_WAITING_FOR_BACKEND);
}

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

    // Listen for UDP backend discovery broadcasts (any laptop IPv4 works).
    discovery.begin(BACKEND_DISCOVERY_UDP_PORT);
    discovery.onDiscovered(onBackendDiscovered);

    Serial.println("\n========================================");
    Serial.println("SMART ENERGY ASSISTANT");
    Serial.println("NETWORK CONFIGURATION");
    Serial.println("========================================");
    Serial.printf("ESP32 AP IP:   %s\n", wifi.getLocalIP().c_str());
    Serial.printf("Backend URL:   %s\n", api.isConfigured() ? api.baseUrl().c_str() : "(not configured - waiting for UDP discovery / desktop EXE)");
    Serial.printf("Device ID:     %s\n", DEVICE_ID);
    Serial.printf("Relay GPIO:    %d (Active-Low: %s)\n", RELAY_CHANNEL_1_PIN, RELAY_ACTIVE_LOW ? "YES" : "NO");
    Serial.println("========================================\n");

    setState(ST_WAITING_FOR_BACKEND);
}

void loop() {
    unsigned long now = millis();

    // ---------- Config server: serves POST /api/backend/config + GET /api/backend/status ----------
    configServer.tick();

    // ---------- UDP backend discovery (always listening, never blocks for long) ----------
    discovery.tick();

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
        setState(ST_REGISTERING_DEVICE);
        deviceRegistered = api.registerDevice(DEVICE_ID, DEVICE_NAME);
        if (!deviceRegistered) {
            Serial.println("[SYS] Registration failed, will retry next cycle");
            if (api.consecutiveFailures() >= BACKEND_LOST_FAILURE_THRESHOLD) {
                handleBackendLost();
            }
        } else {
            setState(ST_STREAMING);
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
        if (ok) {
            setState(ST_STREAMING);
        } else if (api.consecutiveFailures() >= BACKEND_LOST_FAILURE_THRESHOLD) {
            handleBackendLost();
        }
    }

    // ---------- Control command polling (connected + registered + configured only) ----------
    if (laptopConnected && api.isConfigured() && deviceRegistered && (now - lastControlPoll >= CONTROL_POLL_INTERVAL_MS)) {
        lastControlPoll = now;
        handleControlPoll();
    }
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