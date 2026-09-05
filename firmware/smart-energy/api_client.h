#ifndef API_CLIENT_H
#define API_CLIENT_H

#include <Arduino.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

class APIClient {
public:
    APIClient();
    bool registerDevice(const String& deviceId, const String& deviceName);
    bool sendMeasurement(const String& deviceId, float voltage, float current,
                         float power, float energy, float frequency, float powerFactor);
    String getLastUrl();
    int getLastHttpResponseCode();
    bool isLastSendSuccessful();

private:
    String _baseUrl;
    String _lastUrl;
    int _lastHttpResponseCode;
    bool _lastSendOk;
};

#endif // API_CLIENT_H
