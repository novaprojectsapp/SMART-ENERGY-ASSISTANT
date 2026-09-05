#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>

class WiFiManager {
public:
    WiFiManager();
    void beginAP();
    void printStatus();
    bool isConnected();
    int getConnectedClients();
    String getLocalIP();

private:
    bool _apActive;
};

#endif // WIFI_MANAGER_H
