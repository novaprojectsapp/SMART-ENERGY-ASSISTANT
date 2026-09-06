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
    bool registerDevice(const String& deviceId, const String& deviceName);
    bool sendMeasurement(const String& deviceId, float voltage, float current,
                         float power, float energy, float frequency, float powerFactor);
    ControlCommandData pollControlCommand(const String& deviceId);
    bool acknowledgeControl(const String& deviceId, const String& commandId,
                            bool success, const String& relayState, const String& message);
    int getLastHttpResponseCode();
    bool isLastSendSuccessful();

private:
    String _baseUrl;
    int _lastHttpResponseCode;
    bool _lastSendOk;
    String _postJson(const String& url, const String& payload);
    String _getJson(const String& url);
    void _printHttpFailure(int httpCode, const String& body);
};

#endif // API_CLIENT_H