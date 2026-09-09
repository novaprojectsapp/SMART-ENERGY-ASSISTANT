#ifndef BACKEND_DISCOVERY_H
#define BACKEND_DISCOVERY_H

#include <Arduino.h>
#include <WiFiUdp.h>

// UDP listener that lets the ESP32 discover the laptop backend automatically.
//
// The Smart Energy Assistant desktop application broadcasts a JSON packet (
// {"service":"SMART_ENERGY_BACKEND","version":1,"host":"192.168.4.X","port":8000} )
// on the SoftAP subnet. This class listens on BACKEND_DISCOVERY_UDP_PORT,
// validates every packet exactly as the backend does, and only then reports the
// discovered host/port through the callback. Malformed or foreign packets are
// silently ignored.
//
// PZEM measurement continues unaffected while we are here: tick() is
// non-blocking and must be called from the main loop every iteration.
class BackendDiscovery {
public:
    BackendDiscovery();

    // Bind the UDP listener on the given port (BACKEND_DISCOVERY_UDP_PORT).
    void begin(uint16_t port);

    // Non-blocking; call from loop(). Reads at most one datagram.
    void tick();

    // Invoked once with a VALID discovered backend (host + port).
    void onDiscovered(void (*callback)(const String& host, uint16_t port));

private:
    bool isValidHost(const String& host) const;
    WiFiUDP _udp;
    uint16_t _port;
    void (*_onDiscovered)(const String& host, uint16_t port);
};

#endif // BACKEND_DISCOVERY_H