#ifndef CONFIG_SERVER_H
#define CONFIG_SERVER_H

#include <Arduino.h>
#include <WebServer.h>

// Normalize a backend URL: trims whitespace, strips a single trailing slash.
String normalizeBackendUrl(const String& url);

// Validate a backend URL. Returns true when:
//   - it is non-empty after trimming
//   - it starts with http:// or https://
//   - it contains a non-empty host (no whitespace, not starting with : or /)
bool isValidBackendUrl(const String& url);

// Extract the host part of a validated backend URL (e.g. "192.168.4.5").
String backendHostFromUrl(const String& url);

// Thin HTTP server running on the ESP32 SoftAP:
//   POST /api/backend/config  JSON {"backend_url": "http://192.168.4.5:8000"}
//   GET  /api/backend/status  {"configured": true, "backend_url": "..."}
//
// The configured URL is kept in RAM and persisted to NVS (Preferences) so the
// device recovers the last-known backend across reboots. New configuration
// from the desktop EXE always overrides an older persisted URL.
class ConfigServer {
public:
    ConfigServer();

    // Start the SoftAP HTTP server and restore the persisted URL (if any).
    void begin();
    // Must be called from the main loop; services incoming HTTP requests.
    void tick();

    bool isConfigured() const { return _configured; }
    const String& getBackendUrl() const { return _backendUrl; }

    // Optional callback invoked after a new URL is applied. Used by the main
    // loop to reset device registration and resume upload immediately.
    void onConfigured(void (*callback)()) { _onConfigured = callback; }

private:
    void _handleConfig();
    void _handleStatus();
    void _sendJson(int code, const String& body);

    WebServer _server;
    String _backendUrl;
    bool _configured;
    void (*_onConfigured)(void);
};

#endif // CONFIG_SERVER_H