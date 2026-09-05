#include "api_client.h"
#include "config.h"

APIClient::APIClient()
    : _baseUrl("http://" + String(BACKEND_HOST) + ":" + String(BACKEND_PORT))
    , _lastHttpResponseCode(0)
    , _lastSendOk(false) {
}

String APIClient::_postJson(const String& url, const String& payload) {
    HTTPClient http;
    http.setTimeout(5000);
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    Serial.printf("POST %s\n", url.c_str());
    Serial.printf("JSON Payload: %s\n", payload.c_str());

    int httpCode = http.POST(payload);
    _lastHttpResponseCode = httpCode;

    String body;
    if (httpCode > 0) {
        body = http.getString();
    }

    Serial.printf("HTTP Response Code: %d\n", httpCode);
    if (httpCode > 0 && body.length() > 0) {
        Serial.printf("Response Body: %s\n", body.c_str());
    }

    http.end();
    return body;
}

bool APIClient::registerDevice(const String& deviceId, const String& deviceName) {
    String url = _baseUrl + "/api/v1/devices";

    Serial.println();
    Serial.println("Attempting device registration...");
    Serial.printf("URL: %s\n", url.c_str());

    StaticJsonDocument<256> doc;
    doc["id"] = deviceId;
    doc["name"] = deviceName;
    doc["device_type"] = "PZEM-004T";

    String payload;
    serializeJson(doc, payload);

    String body = _postJson(url, payload);
    int httpCode = _lastHttpResponseCode;

    if (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_CREATED) {
        Serial.println("DEVICE REGISTRATION SUCCESSFUL");
        _lastSendOk = true;
        return true;
    }

    if (httpCode == HTTP_CODE_CONFLICT) {
        // Device already registered in a previous boot/session - treat as success.
        Serial.println("DEVICE ALREADY REGISTERED (HTTP 409) - CONTINUING");
        _lastSendOk = true;
        return true;
    }

    _printHttpFailure(httpCode, body);
    Serial.println("DEVICE REGISTRATION FAILED");
    _lastSendOk = false;
    return false;
}

bool APIClient::sendMeasurement(const String& deviceId, float voltage, float current,
                                float power, float energy, float frequency, float powerFactor) {
    String url = _baseUrl + "/api/v1/devices/" + deviceId + "/readings";

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

    String body = _postJson(url, payload);
    int httpCode = _lastHttpResponseCode;

    if (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_CREATED) {
        Serial.println("READING UPLOAD SUCCESSFUL");
        _lastSendOk = true;
        return true;
    }

    _printHttpFailure(httpCode, body);
    Serial.println("READING UPLOAD FAILED");
    _lastSendOk = false;
    return false;
}

void APIClient::_printHttpFailure(int httpCode, const String& body) {
    if (httpCode < 0) {
        Serial.println();
        Serial.println("ERROR: Could not connect to backend (HTTP -1).");
        Serial.println("Check:");
        Serial.println("- Laptop is connected to SmartEnergyESP32");
        Serial.println("- Laptop IP is 192.168.4.2");
        Serial.println("- Backend is running (uvicorn ... --port 8000)");
        Serial.println("- Windows Firewall is not blocking port 8000");
        return;
    }

    if (httpCode == HTTP_CODE_NOT_FOUND) {
        Serial.println();
        Serial.println("ERROR 404: API endpoint not found");
    } else if (httpCode == HTTP_CODE_UNPROCESSABLE_ENTITY) {
        Serial.println();
        Serial.println("ERROR 422: Payload validation failed (check field values/ranges)");
    } else if (httpCode >= 500) {
        Serial.println();
        Serial.println("SERVER ERROR (5xx)");
    } else {
        Serial.println();
        Serial.println("HTTP ERROR: Unexpected response code");
    }

    if (body.length() > 0) {
        Serial.printf("Backend Response: %s\n", body.c_str());
    }
}

int APIClient::getLastHttpResponseCode() {
    return _lastHttpResponseCode;
}

bool APIClient::isLastSendSuccessful() {
    return _lastSendOk;
}