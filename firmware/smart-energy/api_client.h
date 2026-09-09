#ifndef API_CLIENT_H
#define API_CLIENT_H

#include <Arduino.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// A pending control command received from the backend.
struct ControlCommandData {
    bool hasCommand;
    String commandId;
    String deviceId;
    String applianceId;
    int channel;
    String action;
    String expiresAt;
};

class APIClient {
public:
    APIClient();
    // Set the base URL (e.g. "http://192.168.4.5:8000") configured at runtime
    // by the desktop application. Configured URLs are normalized (trailing
    // slash stripped). An empty/invalid URL leaves the client unconfigured.
    void setBaseUrl(const String& url);
    bool isConfigured() const;
    const String& baseUrl() const { return _baseUrl; }
    bool registerDevice(const String& deviceId, const String& deviceName);
    bool sendMeasurement(const String& deviceId, float voltage, float current,
                         float power, float energy, float frequency, float powerFactor);
    ControlCommandData pollControlCommand(const String& deviceId);
    bool acknowledgeControl(const String& deviceId, const String& commandId,
                            bool success, const String& relayState, const String& message);
    int getLastHttpResponseCode();
    bool isLastSendSuccessful();
    // Number of consecutive connection-level failures (HTTP code < 0). The main
    // loop uses this to decide when the laptop backend is lost.
    int consecutiveFailures() const { return _consecutiveFailures; }
    void resetFailures() { _consecutiveFailures = 0; }

private:
    String _baseUrl;
    int _lastHttpResponseCode;
    bool _lastSendOk;
    int _consecutiveFailures;
    String _postJson(const String& url, const String& payload);
    String _getJson(const String& url);
    void _printHttpFailure(int httpCode, const String& body);
};

#endif // API_CLIENT_H