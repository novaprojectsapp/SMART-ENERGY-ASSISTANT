#include "backend_discovery.h"
#include "config.h"
#include <ArduinoJson.h>
#include <WiFi.h>

BackendDiscovery::BackendDiscovery()
    : _port(0)
    , _onDiscovered(nullptr) {
}

void BackendDiscovery::begin(uint16_t port) {
    _port = port;
    if (_udp.begin(_port)) {
        Serial.printf("[DISCOVERY] Listening for backend broadcasts on UDP port %d\n", _port);
    } else {
        Serial.printf("[DISCOVERY] WARNING: could not bind UDP port %d\n", _port);
    }
}

void BackendDiscovery::tick() {
    int packetSize = _udp.parsePacket();
    if (packetSize <= 0) {
        return;
    }
    if (packetSize > BACKEND_DISCOVERY_MAX_PACKET) {
        while (_udp.available()) {
            _udp.read();  // drain oversized datagram, ignore it
        }
        return;
    }

    char buf[BACKEND_DISCOVERY_MAX_PACKET];
    int len = _udp.read(buf, sizeof(buf) - 1);
    if (len <= 0) {
        return;
    }
    buf[len] = '\0';

    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, String(buf))) {
        return;  // not JSON -> ignore
    }

    const char* service = doc["service"];
    int version = doc["version"] | 0;
    const char* host = doc["host"];
    int port = doc["port"] | 0;

    if (service == nullptr || strcmp(service, BACKEND_DISCOVERY_SERVICE) != 0) {
        return;  // wrong service identifier
    }
    if (version != BACKEND_DISCOVERY_VERSION) {
        return;  // unsupported protocol version
    }
    if (host == nullptr) {
        return;
    }
    String hostStr = String(host);
    if (!isValidHost(hostStr)) {
        return;  // not an IPv4 on the AP subnet (or .0/.255)
    }
    if (port <= 0 || port > 65535) {
        return;  // invalid backend port
    }

    if (_onDiscovered != nullptr) {
        _onDiscovered(hostStr, (uint16_t)port);
    }
}

bool BackendDiscovery::isValidHost(const String& host) const {
    // Dotted decimal IPv4 inside the ESP32 AP subnet 192.168.4.0/24,
    // excluding network (.0) and broadcast (.255).
    int octets[4] = { -1, -1, -1, -1 };
    int idx = 0;
    int start = 0;
    for (unsigned int i = 0; i <= host.length(); i++) {
        if (i == host.length() || host.charAt(i) == '.') {
            if (idx >= 4) {
                return false;
            }
            String part = host.substring(start, i);
            if (part.length() == 0 || part.length() > 3) {
                return false;
            }
            for (unsigned int j = 0; j < part.length(); j++) {
                if (part.charAt(j) < '0' || part.charAt(j) > '9') {
                    return false;
                }
            }
            octets[idx] = part.toInt();
            if (octets[idx] < 0 || octets[idx] > 255) {
                return false;
            }
            idx++;
            start = i + 1;
        }
    }
    if (idx != 4) {
        return false;
    }
    if (octets[3] == 0 || octets[3] == 255) {
        return false;  // network/broadcast address
    }
    return octets[0] == 192 && octets[1] == 168 && octets[2] == 4;
}