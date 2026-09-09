#include "config_server.h"
#include "config.h"
#include <ArduinoJson.h>
#include <Preferences.h>

String normalizeBackendUrl(const String& url) {
    String out = url;
    out.trim();
    // Strip a single trailing slash so "http://192.168.4.5:8000/" == "http://192.168.4.5:8000".
    if (out.length() > 0 && out.endsWith("/")) {
        out.remove(out.length() - 1);
    }
    return out;
}

bool isValidBackendUrl(const String& url) {
    String u = url;
    u.trim();
    if (u.length() == 0) {
        return false;
    }
    if (!u.startsWith("http://") && !u.startsWith("https://")) {
        return false;
    }
    String rest = u.substring(u.indexOf("://") + 3);
    if (rest.length() == 0) {
        return false;
    }
    if (rest.charAt(0) == ':' || rest.charAt(0) == '/') {
        return false;  // no host
    }
    // No whitespace inside a host/path (URLs may contain spaces in the path,
    // but a strict reject keeps firmware payloads predictable).
    for (unsigned int i = 0; i < rest.length(); i++) {
        if (rest.charAt(i) == ' ') {
            return false;
        }
    }
    return true;
}

String backendHostFromUrl(const String& url) {
    String rest = url.substring(url.indexOf("://") + 3);
    int end = rest.indexOf(':');
    if (end < 0) {
        end = rest.indexOf('/');
    }
    if (end < 0) {
        return rest;
    }
    return rest.substring(0, end);
}

ConfigServer::ConfigServer()
    : _server(ESP32_AP_CONFIG_SERVER_PORT)
    , _configured(false)
    , _onConfigured(nullptr) {
}

void ConfigServer::begin() {
    Preferences prefs;
    prefs.begin(ESP32_NVS_NAMESPACE, true);
    String saved = prefs.getString(ESP32_NVS_BACKEND_URL_KEY, "");
    prefs.end();

    if (saved.length() > 0 && isValidBackendUrl(saved)) {
        _backendUrl = normalizeBackendUrl(saved);
        _configured = true;
        Serial.printf("[BACKEND] Restored URL: %s\n", _backendUrl.c_str());
    } else if (String(DEFAULT_BACKEND_URL).length() > 0 && isValidBackendUrl(DEFAULT_BACKEND_URL)) {
        _backendUrl = normalizeBackendUrl(DEFAULT_BACKEND_URL);
        _configured = true;
        Serial.printf("[BACKEND] Default URL: %s\n", _backendUrl.c_str());
    } else {
        _backendUrl = "";
        _configured = false;
        Serial.println("[BACKEND] Not configured - waiting for desktop EXE (POST /api/backend/config)");
    }

    _server.on("/api/backend/config", HTTP_POST, [this]() { this->_handleConfig(); });
    _server.on("/api/backend/status", HTTP_GET, [this]() { this->_handleStatus(); });
    _server.begin();
    Serial.printf("[BACKEND] AP config server listening on port %d\n", ESP32_AP_CONFIG_SERVER_PORT);
}

void ConfigServer::tick() {
    _server.handleClient();
}

void ConfigServer::_handleConfig() {
    String body = _server.arg("plain");
    if (body.length() == 0) {
        _server.send(400, "application/json", "{\"configured\":false,\"error\":\"empty body\"}");
        return;
    }

    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, body)) {
        _sendJson(400, "{\"configured\":false,\"error\":\"invalid JSON\"}");
        return;
    }

    const char* rawUrl = doc["backend_url"];
    if (!rawUrl || strlen(rawUrl) == 0) {
        _sendJson(400, "{\"configured\":false,\"error\":\"backend_url must not be empty\"}");
        return;
    }

    if (!isValidBackendUrl(rawUrl)) {
        _sendJson(400, "{\"configured\":false,\"error\":\"backend_url must be a valid http(s) URL with a host\"}");
        return;
    }

    String url = normalizeBackendUrl(rawUrl);

    if (!_storeUrl(url)) {
        _sendJson(500, "{\"configured\":false,\"error\":\"could not persist backend_url\"}");
        return;
    }

    Serial.println();
    Serial.printf("[BACKEND] Configured URL: %s\n", _backendUrl.c_str());
    Serial.printf("[BACKEND] Backend host: %s (port inferred from URL)\n", backendHostFromUrl(_backendUrl).c_str());

    char resp[160];
    snprintf(resp, sizeof(resp), "{\"configured\":true,\"backend_url\":\"%s\"}", _backendUrl.c_str());
    _sendJson(200, resp);
}

void ConfigServer::applyDiscoveredBackend(const String& url) {
    if (!isValidBackendUrl(url)) {
        Serial.printf("[DISCOVERY] Rejecting discovered backend URL: %s\n", url.c_str());
        return;
    }
    String normalized = normalizeBackendUrl(url);
    if (!_storeUrl(normalized)) {
        Serial.println("[DISCOVERY] Could not persist discovered backend URL");
        return;
    }
    Serial.printf("[BACKEND] Discovered URL: %s\n", _backendUrl.c_str());
}

bool ConfigServer::_storeUrl(const String& url) {
    // Persist to NVS so the device boot-recovery keeps using the same URL.
    Preferences prefs;
    prefs.begin(ESP32_NVS_NAMESPACE, false);
    prefs.putString(ESP32_NVS_BACKEND_URL_KEY, url.c_str());
    prefs.end();

    _backendUrl = url;
    _configured = true;

    if (_onConfigured != nullptr) {
        _onConfigured();
    }
    return true;
}

void ConfigServer::_handleStatus() {
    if (!_configured) {
        _sendJson(200, "{\"configured\":false,\"backend_url\":\"\"}");
        return;
    }
    char resp[160];
    snprintf(resp, sizeof(resp), "{\"configured\":true,\"backend_url\":\"%s\"}", _backendUrl.c_str());
    _sendJson(200, resp);
}

void ConfigServer::_sendJson(int code, const String& body) {
    _server.send(code, "application/json", body);
}