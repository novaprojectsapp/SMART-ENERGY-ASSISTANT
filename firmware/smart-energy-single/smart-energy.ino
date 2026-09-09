// ============================================================
// SMART ENERGY ASSISTANT - ESP32-S3 single-file firmware
// Arduino IDE sketch. Drop-in replacement for the old firmware
// that only discovered the laptop backend by scanning
// 192.168.4.2..50:8000 (missed e.g. a laptop at .100).
//
// The laptop backend now broadcasts UDP announcements on the AP
// subnet (port 44441); this sketch listens, validates them and
// streams to ANY 192.168.4.X address. It also keeps the SoftAP
// config server (POST /api/backend/config) used by the desktop
// EXE, PZEM-004T telemetry, and GPIO-40 relay control.
//
// Required libraries (Arduino IDE Library Manager):
//   - ArduinoJson        (bblanchon)
//   - PZEM004Tv30        (mandulaj - PZEM-004T v3.0)
//   Built-in: WiFi, WebServer, WiFiUdp, HTTPClient, Preferences
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <PZEM004Tv30.h>

// ============================================================
// Configuration (must mirror backend/app/utils/udp_discovery.py)
// ============================================================
#define PZEM_RX_PIN 17
#define PZEM_TX_PIN 18
#define PZEM_SERIAL_BAUD 9600

#define WIFI_AP_SSID "SmartEnergyESP32"
#define WIFI_AP_PASSWORD "SmartEnergy123"
#define WIFI_AP_CHANNEL 1
#define WIFI_AP_MAX_CLIENTS 4

#define DEVICE_ID "ESP32-S3-01"
#define DEVICE_NAME "ESP32-S3 Smart Energy"

#define RELAY_CHANNEL_1_PIN 40
#define RELAY_ACTIVE_LOW true

#define BACKEND_DISCOVERY_SERVICE "SMART_ENERGY_BACKEND"
#define BACKEND_DISCOVERY_VERSION 1
#define BACKEND_DISCOVERY_UDP_PORT 44441
#define BACKEND_DISCOVERY_MAX_PACKET 512
#define BACKEND_LOST_FAILURE_THRESHOLD 5

#define ESP32_AP_CONFIG_SERVER_PORT 80
#define ESP32_NVS_NAMESPACE "sea"
#define ESP32_NVS_BACKEND_URL_KEY "backend_url"

#define MEASUREMENT_INTERVAL_MS 2000
#define PZEM_READ_INTERVAL_MS 1000
#define WIFI_CHECK_INTERVAL_MS 10000
#define DEVICE_REGISTER_RETRY_MS 30000
#define CONTROL_POLL_INTERVAL_MS 1000
#define SERIAL_BAUD 115200

struct PZEMData {
    float voltage;
    float current;
    float power;
    float energy;
    float frequency;
    float powerFactor;
    bool valid;
};

// ============================================================
// Global state
// ============================================================
unsigned long lastPzemRead = 0;
unsigned long lastSend = 0;
unsigned long lastWifiCheck = 0;
unsigned long lastRegisterAttempt = 0;
unsigned long lastControlPoll = 0;
bool deviceRegistered = false;
bool laptopConnected = false;
PZEMData lastReading;
// Last successfully executed command ID (in-memory idempotency guard).
String lastExecutedCommandId = "NO_COMMAND";

// ============================================================
// Relay
// ============================================================
static void relayApply(bool on) {
    uint8_t level = RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW);
    digitalWrite(RELAY_CHANNEL_1_PIN, level);
    Serial.printf("[RELAY] GPIO%d -> %s (logical %s)\n",
                  RELAY_CHANNEL_1_PIN, level == HIGH ? "HIGH" : "LOW", on ? "ON" : "OFF");
}

static bool relayState = false;

static void relayBegin() {
    pinMode(RELAY_CHANNEL_1_PIN, OUTPUT);
    relayState = false;
    relayApply(relayState);
    Serial.println("[RELAY] Relay initialized (GPIO 40, Active-Low, initial OFF)");
}

static void relaySet(bool on) {
    relayState = on;
    relayApply(relayState);
    Serial.printf("[RELAY] %s\n", on ? "ON" : "OFF");
}

// ============================================================
// PZEM-004T
// ============================================================
PZEM004Tv30 pzem(Serial1, PZEM_RX_PIN, PZEM_TX_PIN);

static void pzemBegin() {
    Serial1.begin(PZEM_SERIAL_BAUD, SERIAL_8N1, PZEM_RX_PIN, PZEM_TX_PIN);
    Serial.println("[PZEM] UART1 initialized");
    Serial.printf("[PZEM] RX: GPIO%d, TX: GPIO%d, Baud: %d\n", PZEM_RX_PIN, PZEM_TX_PIN, PZEM_SERIAL_BAUD);
}

static PZEMData pzemRead() {
    PZEMData data;
    data.voltage = pzem.voltage();
    data.current = pzem.current();
    data.power = pzem.power();
    data.energy = pzem.energy();
    data.frequency = pzem.frequency();
    data.powerFactor = pzem.pf();
    data.valid = !isnan(data.voltage);
    return data;
}

static void pzemPrint(const PZEMData& data) {
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

// ============================================================
// URL helpers (shared by the config server and UDP discovery)
// ============================================================
static String normalizeBackendUrl(const String& url) {
    String out = url;
    out.trim();
    if (out.length() > 0 && out.endsWith("/")) {
        out.remove(out.length() - 1);
    }
    return out;
}

static bool isValidBackendUrl(const String& url) {
    String u = url;
    u.trim();
    if (u.length() == 0) return false;
    if (!u.startsWith("http://") && !u.startsWith("https://")) return false;
    String rest = u.substring(u.indexOf("://") + 3);
    if (rest.length() == 0) return false;
    if (rest.charAt(0) == ':' || rest.charAt(0) == '/') return false;
    for (unsigned int i = 0; i < rest.length(); i++) {
        if (rest.charAt(i) == ' ') return false;
    }
    return true;
}

// ============================================================
// AP config server: POST /api/backend/config, GET /api/backend/status
// ============================================================
WebServer configServer(ESP32_AP_CONFIG_SERVER_PORT);
String backendUrl = "";
bool backendConfigured = false;
void (*onBackendConfiguredCallback)() = nullptr;

static bool storeBackendUrl(const String& url) {
    Preferences prefs;
    prefs.begin(ESP32_NVS_NAMESPACE, false);
    prefs.putString(ESP32_NVS_BACKEND_URL_KEY, url.c_str());
    prefs.end();
    backendUrl = url;
    backendConfigured = true;
    if (onBackendConfiguredCallback != nullptr) {
        onBackendConfiguredCallback();
    }
    return true;
}

static void sendJson(int code, const String& body) {
    configServer.send(code, "application/json", body);
}

static void handleConfigPost() {
    String body = configServer.arg("plain");
    if (body.length() == 0) {
        sendJson(400, "{\"configured\":false,\"error\":\"empty body\"}");
        return;
    }
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, body)) {
        sendJson(400, "{\"configured\":false,\"error\":\"invalid JSON\"}");
        return;
    }
    const char* rawUrl = doc["backend_url"];
    if (!rawUrl || strlen(rawUrl) == 0) {
        sendJson(400, "{\"configured\":false,\"error\":\"backend_url must not be empty\"}");
        return;
    }
    if (!isValidBackendUrl(rawUrl)) {
        sendJson(400, "{\"configured\":false,\"error\":\"backend_url must be a valid http(s) URL with a host\"}");
        return;
    }
    String url = normalizeBackendUrl(rawUrl);
    if (!storeBackendUrl(url)) {
        sendJson(500, "{\"configured\":false,\"error\":\"could not persist backend_url\"}");
        return;
    }
    Serial.println();
    Serial.printf("[BACKEND] Configured URL: %s\n", backendUrl.c_str());
    char resp[160];
    snprintf(resp, sizeof(resp), "{\"configured\":true,\"backend_url\":\"%s\"}", backendUrl.c_str());
    sendJson(200, resp);
}

static void handleStatusGet() {
    if (!backendConfigured) {
        sendJson(200, "{\"configured\":false,\"backend_url\":\"\"}");
        return;
    }
    char resp[160];
    snprintf(resp, sizeof(resp), "{\"configured\":true,\"backend_url\":\"%s\"}", backendUrl.c_str());
    sendJson(200, resp);
}

static void configServerBegin() {
    Preferences prefs;
    prefs.begin(ESP32_NVS_NAMESPACE, true);
    String saved = prefs.getString(ESP32_NVS_BACKEND_URL_KEY, "");
    prefs.end();
    if (saved.length() > 0 && isValidBackendUrl(saved)) {
        backendUrl = normalizeBackendUrl(saved);
        backendConfigured = true;
        Serial.printf("[BACKEND] Restored URL: %s\n", backendUrl.c_str());
    } else {
        backendUrl = "";
        backendConfigured = false;
        Serial.println("[BACKEND] Not configured - waiting for UDP discovery / desktop EXE");
    }
    configServer.on("/api/backend/config", HTTP_POST, handleConfigPost);
    configServer.on("/api/backend/status", HTTP_GET, handleStatusGet);
    configServer.begin();
    Serial.printf("[BACKEND] AP config server listening on port %d\n", ESP32_AP_CONFIG_SERVER_PORT);
}

static void applyDiscoveredBackend(const String& url) {
    if (!isValidBackendUrl(url)) {
        Serial.printf("[DISCOVERY] Rejecting discovered backend URL: %s\n", url.c_str());
        return;
    }
    if (!storeBackendUrl(normalizeBackendUrl(url))) {
        Serial.println("[DISCOVERY] Could not persist discovered backend URL");
        return;
    }
    Serial.printf("[BACKEND] Discovered URL: %s\n", backendUrl.c_str());
}

// ============================================================
// UDP backend discovery (SA + efficient, never blocks)
// ============================================================
WiFiUDP discoveryUdp;

static bool isValidDiscoveryHost(const String& host) {
    int octets[4] = { -1, -1, -1, -1 };
    int idx = 0;
    int start = 0;
    for (unsigned int i = 0; i <= host.length(); i++) {
        if (i == host.length() || host.charAt(i) == '.') {
            if (idx >= 4) return false;
            String part = host.substring(start, i);
            if (part.length() == 0 || part.length() > 3) return false;
            for (unsigned int j = 0; j < part.length(); j++) {
                if (part.charAt(j) < '0' || part.charAt(j) > '9') return false;
            }
            octets[idx] = part.toInt();
            if (octets[idx] < 0 || octets[idx] > 255) return false;
            idx++;
            start = i + 1;
        }
    }
    if (idx != 4) return false;
    if (octets[3] == 0 || octets[3] == 255) return false;
    return octets[0] == 192 && octets[1] == 168 && octets[2] == 4;
}

void (*onBackendDiscoveredCallback)(const String& host, uint16_t port) = nullptr;

static void discoveryBegin() {
    if (discoveryUdp.begin(BACKEND_DISCOVERY_UDP_PORT)) {
        Serial.printf("[DISCOVERY] Listening for backend broadcasts on UDP port %d\n", BACKEND_DISCOVERY_UDP_PORT);
    } else {
        Serial.printf("[DISCOVERY] WARNING: could not bind UDP port %d\n", BACKEND_DISCOVERY_UDP_PORT);
    }
}

static void discoveryTick() {
    int packetSize = discoveryUdp.parsePacket();
    if (packetSize <= 0) return;
    if (packetSize > BACKEND_DISCOVERY_MAX_PACKET) {
        while (discoveryUdp.available()) {
            discoveryUdp.read();
        }
        return;
    }
    char buf[BACKEND_DISCOVERY_MAX_PACKET];
    int len = discoveryUdp.read(buf, sizeof(buf) - 1);
    if (len <= 0) return;
    buf[len] = '\0';

    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, String(buf))) return;

    const char* service = doc["service"];
    int version = doc["version"] | 0;
    const char* host = doc["host"];
    int port = doc["port"] | 0;

    if (service == nullptr || strcmp(service, BACKEND_DISCOVERY_SERVICE) != 0) return;
    if (version != BACKEND_DISCOVERY_VERSION) return;
    if (host == nullptr) return;
    String hostStr = String(host);
    if (!isValidDiscoveryHost(hostStr)) return;
    if (port <= 0 || port > 65535) return;

    if (onBackendDiscoveredCallback != nullptr) {
        onBackendDiscoveredCallback(hostStr, (uint16_t)port);
    }
}

// ============================================================
// API client (registration, telemetry, control)
// ============================================================
struct ControlCommandData {
    bool hasCommand;
    String commandId;
    String deviceId;
    String applianceId;
    int channel;
    String action;
    String expiresAt;
};

static String apiBaseUrl = "";
static int lastHttpCode = 0;
static int consecutiveFailures = 0;

static void apiSetBaseUrl(const String& url) {
    apiBaseUrl = normalizeBackendUrl(url);
}

static bool apiIsConfigured() {
    return apiBaseUrl.length() > 0 && isValidBackendUrl(apiBaseUrl);
}

static String apiPost(const String& url, const String& payload) {
    HTTPClient http;
    http.setTimeout(5000);
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    Serial.printf("POST %s\n", url.c_str());
    Serial.printf("JSON Payload: %s\n", payload.c_str());
    int code = http.POST(payload);
    lastHttpCode = code;
    if (code < 0) {
        consecutiveFailures++;
    } else {
        consecutiveFailures = 0;
    }
    String body;
    if (code > 0) body = http.getString();
    Serial.printf("HTTP Response Code: %d\n", code);
    if (code > 0 && body.length() > 0) Serial.printf("Response Body: %s\n", body.c_str());
    http.end();
    return body;
}

static String apiGet(const String& url) {
    HTTPClient http;
    http.setTimeout(5000);
    http.begin(url);
    Serial.printf("GET %s\n", url.c_str());
    int code = http.GET();
    lastHttpCode = code;
    if (code < 0) {
        consecutiveFailures++;
    } else {
        consecutiveFailures = 0;
    }
    String body;
    if (code > 0) {
        body = http.getString();
        Serial.printf("HTTP Response Code: %d\n", code);
        if (body.length() > 0) Serial.printf("Response Body: %s\n", body.c_str());
    } else {
        Serial.printf("HTTP Response Code: %d (connection failed)\n", code);
    }
    http.end();
    return body;
}

static void apiPrintFailure(int code, const String& body) {
    if (code < 0) {
        Serial.println();
        Serial.println("ERROR: Could not connect to backend (HTTP -1).");
        Serial.println("Check:");
        Serial.println("- Laptop is connected to SmartEnergyESP32");
        Serial.println("- Backend is running (SmartEnergyAssistant.exe) on port 8000");
        Serial.println("- Windows Firewall is not blocking port 8000");
        return;
    }
    if (code == HTTP_CODE_NOT_FOUND) {
        Serial.println("\nERROR 404: API endpoint not found");
    } else if (code == HTTP_CODE_UNPROCESSABLE_ENTITY) {
        Serial.println("\nERROR 422: Payload validation failed");
    } else if (code >= 500) {
        Serial.println("\nSERVER ERROR (5xx)");
    } else {
        Serial.println("\nHTTP ERROR: Unexpected response code");
    }
    if (body.length() > 0) Serial.printf("Backend Response: %s\n", body.c_str());
}

static bool apiRegister(const String& deviceId, const String& deviceName) {
    String url = apiBaseUrl + "/api/v1/devices";
    Serial.println();
    Serial.println("Attempting device registration...");
    StaticJsonDocument<256> doc;
    doc["id"] = deviceId;
    doc["name"] = deviceName;
    doc["device_type"] = "PZEM-004T";
    String payload;
    serializeJson(doc, payload);
    String body = apiPost(url, payload);
    int code = lastHttpCode;
    if (code == HTTP_CODE_OK || code == HTTP_CODE_CREATED) {
        Serial.println("DEVICE REGISTRATION SUCCESSFUL");
        return true;
    }
    if (code == HTTP_CODE_CONFLICT) {
        Serial.println("DEVICE ALREADY REGISTERED (HTTP 409) - CONTINUING");
        return true;
    }
    apiPrintFailure(code, body);
    Serial.println("DEVICE REGISTRATION FAILED");
    return false;
}

static bool apiSendMeasurement(const String& deviceId, float voltage, float current,
                               float power, float energy, float frequency, float powerFactor) {
    String url = apiBaseUrl + "/api/v1/devices/" + deviceId + "/readings";
    Serial.println();
    Serial.println("----------------------------------------");
    Serial.println("SENDING PZEM DATA TO BACKEND");
    Serial.println("----------------------------------------");
    Serial.printf("Backend URL: %s\n", url.c_str());
    StaticJsonDocument<256> doc;
    doc["voltage"] = voltage;
    doc["current"] = current;
    doc["power"] = power;
    doc["energy"] = energy;
    doc["frequency"] = frequency;
    doc["power_factor"] = powerFactor;
    String payload;
    serializeJson(doc, payload);
    String body = apiPost(url, payload);
    int code = lastHttpCode;
    if (code == HTTP_CODE_OK || code == HTTP_CODE_CREATED) {
        Serial.println("READING UPLOAD SUCCESSFUL");
        return true;
    }
    apiPrintFailure(code, body);
    Serial.println("READING UPLOAD FAILED");
    return false;
}

static ControlCommandData apiPollControl(const String& deviceId) {
    ControlCommandData data;
    data.hasCommand = false;
    data.commandId = "";
    data.deviceId = deviceId;
    data.applianceId = "";
    data.channel = 0;
    data.action = "";
    data.expiresAt = "";

    String url = apiBaseUrl + "/api/v1/devices/" + deviceId + "/control/pending";
    Serial.println();
    Serial.println("POLLING FOR CONTROL COMMANDS");
    String body = apiGet(url);
    int code = lastHttpCode;
    if (code != HTTP_CODE_OK) {
        apiPrintFailure(code, body);
        Serial.println("Control poll failed; will retry next cycle");
        return data;
    }
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, body)) {
        Serial.println("Control poll: failed to parse response");
        return data;
    }
    JsonVariant cmd = doc["command"];
    if (cmd.isNull() || cmd["command_id"].isNull()) {
        Serial.println("Control poll: no pending command");
        return data;
    }
    data.hasCommand = true;
    if (!cmd["command_id"].isNull()) data.commandId = cmd["command_id"].as<const char*>();
    if (!cmd["device_id"].isNull()) data.deviceId = cmd["device_id"].as<const char*>();
    if (!cmd["appliance_id"].isNull()) data.applianceId = cmd["appliance_id"].as<const char*>();
    data.channel = cmd["channel"].isNull() ? 0 : cmd["channel"].as<int>();
    if (!cmd["action"].isNull()) data.action = cmd["action"].as<const char*>();
    if (!cmd["expires_at"].isNull()) data.expiresAt = cmd["expires_at"].as<const char*>();
    Serial.printf("Control poll: got command id=%s channel=%d action=%s\n",
                  data.commandId.c_str(), data.channel, data.action.c_str());
    return data;
}

static bool apiAckControl(const String& deviceId, const String& commandId,
                          bool success, const String& relayState, const String& message) {
    String url = apiBaseUrl + "/api/v1/devices/" + deviceId + "/control/" + commandId + "/ack";
    Serial.println();
    Serial.println("SENDING CONTROL ACKNOWLEDGEMENT");
    StaticJsonDocument<512> doc;
    doc["success"] = success;
    doc["relay_state"] = relayState;
    doc["message"] = message;
    String payload;
    serializeJson(doc, payload);
    String body = apiPost(url, payload);
    int code = lastHttpCode;
    if (code == HTTP_CODE_OK || code == HTTP_CODE_CREATED) {
        Serial.println("CONTROL ACK SUCCESSFUL");
        return true;
    }
    apiPrintFailure(code, body);
    Serial.println("CONTROL ACK FAILED");
    return false;
}

// ============================================================
// Backend link state machine
// ============================================================
enum BackendState {
    ST_WAITING_FOR_BACKEND,
    ST_BACKEND_DISCOVERED,
    ST_REGISTERING_DEVICE,
    ST_STREAMING
};
BackendState netState = ST_WAITING_FOR_BACKEND;

static void setState(BackendState newState) {
    if (netState == newState) return;
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

static void applyBackendUrl(const String& url) {
    deviceRegistered = false;
    apiSetBaseUrl(url);
    consecutiveFailures = 0;
    lastRegisterAttempt = millis() - DEVICE_REGISTER_RETRY_MS;
    lastSend = 0;
    lastControlPoll = 0;
}

static void onBackendConfigured() {
    Serial.println("[SYS] New backend URL received - resetting registration state");
    applyBackendUrl(backendUrl);
    setState(ST_BACKEND_DISCOVERED);
}

static void onBackendDiscovered(const String& host, uint16_t port) {
    String url = "http://" + host + ":" + String(port);
    Serial.printf("\nBackend discovered: %s\n", url.c_str());
    applyBackendUrl(url);
    applyDiscoveredBackend(url);
    setState(ST_BACKEND_DISCOVERED);
}

static void handleBackendLost() {
    Serial.println("[SYS] Backend unreachable - returning to WAITING_FOR_BACKEND");
    apiSetBaseUrl("");
    consecutiveFailures = 0;
    deviceRegistered = false;
    setState(ST_WAITING_FOR_BACKEND);
}

// ============================================================
// Control execution
// ============================================================
static void handleControlPoll() {
    ControlCommandData cmd = apiPollControl(DEVICE_ID);
    if (!cmd.hasCommand) return;

    if (cmd.commandId == lastExecutedCommandId) {
        Serial.printf("[CONTROL] Duplicate command %s; re-acknowledging safely\n", cmd.commandId.c_str());
        apiAckControl(DEVICE_ID, cmd.commandId, true,
                      relayState ? "ON" : "OFF", "Already executed (idempotent ack)");
        return;
    }

    bool success = false;
    String relayStateStr = "UNKNOWN";
    String message = "Relay execution failed";

    if (cmd.channel == 1) {
        if (cmd.action == "ON") {
            relaySet(true);
            success = true;
            relayStateStr = "ON";
            message = "Relay switched ON successfully";
        } else if (cmd.action == "OFF") {
            relaySet(false);
            success = true;
            relayStateStr = "OFF";
            message = "Relay switched OFF successfully";
        } else {
            message = "Unknown action: " + cmd.action;
        }
    } else {
        message = "Unsupported relay channel";
    }

    if (success) {
        lastExecutedCommandId = cmd.commandId;
    }

    apiAckControl(DEVICE_ID, cmd.commandId, success, relayStateStr, message);
    Serial.printf("[CONTROL] Executed command %s: success=%s state=%s\n",
                  cmd.commandId.c_str(), success ? "true" : "false", relayStateStr.c_str());
}

// ============================================================
// setup + loop
// ============================================================
void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);
    Serial.println("\n\n=== SMART ENERGY ESP32-S3 ===");

    relayBegin();
    pzemBegin();

    WiFi.mode(WIFI_AP);
    WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD, WIFI_AP_CHANNEL, 0, WIFI_AP_MAX_CLIENTS);
    delay(500);
    Serial.printf("ESP32 AP IP: %s\n", WiFi.softAPIP().toString().c_str());

    configServerBegin();
    if (backendConfigured) {
        apiSetBaseUrl(backendUrl);
    }
    onBackendConfiguredCallback = onBackendConfigured;

    discoveryBegin();
    onBackendDiscoveredCallback = onBackendDiscovered;

    Serial.println("\n========================================");
    Serial.println("SMART ENERGY ASSISTANT");
    Serial.println("NETWORK CONFIGURATION");
    Serial.println("========================================");
    Serial.printf("ESP32 AP IP:   %s\n", WiFi.softAPIP().toString().c_str());
    Serial.printf("Backend URL:   %s\n", apiIsConfigured() ? apiBaseUrl.c_str() : "(not configured - waiting for UDP discovery / desktop EXE)");
    Serial.printf("Device ID:     %s\n", DEVICE_ID);
    Serial.printf("Relay GPIO:    %d (Active-Low: %s)\n", RELAY_CHANNEL_1_PIN, RELAY_ACTIVE_LOW ? "YES" : "NO");
    Serial.println("========================================\n");

    setState(ST_WAITING_FOR_BACKEND);
}

void loop() {
    unsigned long now = millis();

    configServer.handleClient();

    discoveryTick();

    if (now - lastPzemRead >= PZEM_READ_INTERVAL_MS) {
        lastPzemRead = now;
        lastReading = pzemRead();
        pzemPrint(lastReading);
    }

    if (now - lastWifiCheck >= WIFI_CHECK_INTERVAL_MS) {
        lastWifiCheck = now;
        int clients = WiFi.softAPgetStationNum();
        bool current = clients > 0;
        if (current != laptopConnected) {
            laptopConnected = current;
            if (laptopConnected) {
                Serial.printf("[WIFI] Client Connected: YES (%d stations)\n", clients);
                lastRegisterAttempt = 0;
            } else {
                Serial.println("[WIFI] Client Connected: NO - continuing PZEM monitoring");
            }
        } else {
            Serial.printf("[WIFI] Client Connected: %s (%d stations)\n",
                          laptopConnected ? "YES" : "NO", clients);
        }
    }

    if (laptopConnected && apiIsConfigured() && !deviceRegistered && (now - lastRegisterAttempt >= DEVICE_REGISTER_RETRY_MS)) {
        lastRegisterAttempt = now;
        setState(ST_REGISTERING_DEVICE);
        deviceRegistered = apiRegister(DEVICE_ID, DEVICE_NAME);
        if (!deviceRegistered) {
            Serial.println("[SYS] Registration failed, will retry next cycle");
            if (consecutiveFailures >= BACKEND_LOST_FAILURE_THRESHOLD) {
                handleBackendLost();
            }
        } else {
            setState(ST_STREAMING);
        }
    }

    if (laptopConnected && apiIsConfigured() && deviceRegistered && lastReading.valid && (now - lastSend >= MEASUREMENT_INTERVAL_MS)) {
        lastSend = now;
        bool ok = apiSendMeasurement(
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
        } else if (consecutiveFailures >= BACKEND_LOST_FAILURE_THRESHOLD) {
            handleBackendLost();
        }
    }

    if (laptopConnected && apiIsConfigured() && deviceRegistered && (now - lastControlPoll >= CONTROL_POLL_INTERVAL_MS)) {
        lastControlPoll = now;
        handleControlPoll();
    }
}