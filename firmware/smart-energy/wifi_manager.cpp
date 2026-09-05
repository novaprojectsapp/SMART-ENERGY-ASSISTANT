#include "wifi_manager.h"
#include "config.h"

WiFiManager::WiFiManager() : _apActive(false) {}

void WiFiManager::beginAP() {
    Serial.println("\n================================");
    Serial.println("SMART ENERGY WIFI ACCESS POINT");
    Serial.println("================================");
    Serial.printf("SSID:     %s\n", WIFI_AP_SSID);
    Serial.printf("Password: %s\n", WIFI_AP_PASSWORD);
    Serial.println("================================");

    WiFi.mode(WIFI_AP);
    WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD, WIFI_AP_CHANNEL, 0, WIFI_AP_MAX_CLIENTS);

    delay(500);

    IPAddress apIP = WiFi.softAPIP();
    Serial.printf("ESP32 AP IP: %s\n", apIP.toString().c_str());
    Serial.println("================================\n");

    _apActive = true;
}

void WiFiManager::printStatus() {
    if (!_apActive) {
        Serial.println("[WIFI] AP not active");
        return;
    }

    int clients = WiFi.softAPgetStationNum();
    Serial.printf("[WIFI] AP Active | SSID: %s | Clients: %d | IP: %s\n",
                  WIFI_AP_SSID, clients, WiFi.softAPIP().toString().c_str());
}

bool WiFiManager::isConnected() {
    return _apActive && (WiFi.softAPgetStationNum() > 0);
}

int WiFiManager::getConnectedClients() {
    return _apActive ? WiFi.softAPgetStationNum() : 0;
}

String WiFiManager::getLocalIP() {
    return _apActive ? WiFi.softAPIP().toString() : "0.0.0.0";
}
