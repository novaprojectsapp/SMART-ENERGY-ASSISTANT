#include "api_client.h"
#include "config.h"

APIClient::APIClient()
    : _baseUrl("http://" + String(BACKEND_HOST) + ":" + String(BACKEND_PORT))
    , _lastHttpResponseCode(0)
    , _lastSendOk(false) {
}

bool APIClient::registerDevice(const String& deviceId, const String& deviceName) {
    String url = _baseUrl + "/api/v1/devices";
    _lastUrl = url;

    StaticJsonDocument<256> doc;
    doc["id"] = deviceId;
    doc["name"] = deviceName;
    doc["device_type"] = "PZEM-004T";

    String payload;
    serializeJson(doc, payload);

    HTTPClient http;
    http.setTimeout(5000);
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    Serial.println("[HTTP] Registering device...");
    int httpCode = http.POST(payload);
    _lastHttpResponseCode = httpCode;

    bool ok = (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_CREATED);
    if (ok) {
        Serial.printf("[HTTP] Device registered: %d\n", httpCode);
    } else {
        Serial.printf("[HTTP] Device register failed: %d - %s\n", httpCode, http.errorToString(httpCode).c_str());
    }

    http.end();
    _lastSendOk = ok;
    return ok;
}

bool APIClient::sendMeasurement(const String& deviceId, float voltage, float current,
                                float power, float energy, float frequency, float powerFactor) {
    String url = _baseUrl + "/api/v1/devices/" + deviceId + "/readings";
    _lastUrl = url;

    StaticJsonDocument<256> doc;
    doc["voltage"] = voltage;
    doc["current"] = current;
    doc["power"] = power;
    doc["energy"] = energy;
    doc["frequency"] = frequency;
    doc["power_factor"] = powerFactor;

    String payload;
    serializeJson(doc, payload);

    HTTPClient http;
    http.setTimeout(5000);
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    Serial.printf("[HTTP] POST %s\n", url.c_str());
    Serial.printf("[HTTP] Body: %s\n", payload.c_str());

    int httpCode = http.POST(payload);
    _lastHttpResponseCode = httpCode;

    bool ok = (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_CREATED);
    if (ok) {
        Serial.printf("[HTTP] Response Code: %d\n", httpCode);
        Serial.println("[HTTP] Measurement sent successfully");
    } else {
        Serial.printf("[HTTP] Error %d: %s\n", httpCode, http.errorToString(httpCode).c_str());
        Serial.println("[HTTP] Will retry during next transmission cycle");
    }

    http.end();
    _lastSendOk = ok;
    return ok;
}

String APIClient::getLastUrl() {
    return _lastUrl;
}

int APIClient::getLastHttpResponseCode() {
    return _lastHttpResponseCode;
}

bool APIClient::isLastSendSuccessful() {
    return _lastSendOk;
}