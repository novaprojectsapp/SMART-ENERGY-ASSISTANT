#ifndef CONFIG_H
#define CONFIG_H

// =============================================
// PZEM-004T UART Configuration
// =============================================
#define PZEM_RX_PIN 17
#define PZEM_TX_PIN 18
#define PZEM_SERIAL_BAUD 9600
#define PZEM_UART_NUM 1

// =============================================
// WiFi Access Point Configuration
// =============================================
#define WIFI_AP_SSID "SmartEnergyESP32"
#define WIFI_AP_PASSWORD "SmartEnergy123"
#define WIFI_AP_CHANNEL 1
#define WIFI_AP_MAX_CLIENTS 4

// =============================================
// Backend Configuration
// =============================================
// The backend URL is NO LONGER hardcoded. It is configured at runtime by the
// Smart Energy Assistant desktop application via the AP configuration server
// (POST /api/backend/config). An optional default (blank = disabled) can be
// overridden/persisted by the desktop app at any time.
#define DEFAULT_BACKEND_URL ""

// =============================================
// UDP Backend Discovery (ESP32 listens on the SoftAP)
// =============================================
// The laptop backend announces itself over UDP on the SoftAP subnet so the
// ESP32 learns the laptop's dynamic 192.168.4.X address with NO hardcoded IP
// ("192.168.4.2/3/4/100 ... all supported"). Constants must mirror
// backend/app/utils/udp_discovery.py.
#define BACKEND_DISCOVERY_SERVICE "SMART_ENERGY_BACKEND"
#define BACKEND_DISCOVERY_VERSION 1
#define BACKEND_DISCOVERY_UDP_PORT 44441
#define BACKEND_DISCOVERY_MAX_PACKET 512
// After this many consecutive HTTP connection failures the firmware considers
// the laptop backend lost, returns to WAITING_FOR_BACKEND and keeps listening
// for a new UDP announcement (no reboot required).
#define BACKEND_LOST_FAILURE_THRESHOLD 5

// =============================================
// ESP32 AP Configuration Server
// =============================================
// Serves POST /api/backend/config and GET /api/backend/status on the SoftAP
// so the desktop EXE can push the laptop's dynamically detected backend URL.
#define ESP32_AP_CONFIG_SERVER_PORT 80
#define ESP32_NVS_NAMESPACE "sea"
#define ESP32_NVS_BACKEND_URL_KEY "backend_url"

// =============================================
// Device Configuration
// =============================================
#define DEVICE_ID "ESP32-S3-01"
#define DEVICE_NAME "ESP32-S3 Smart Energy"

// =============================================
// Relay / Appliance Control Configuration
// =============================================
// The single-channel relay is wired to GPIO 40. It is ACTIVE LOW (module has
// been manually tested): ON  = LOW, OFF = HIGH.
#define RELAY_CHANNEL_1_PIN 40
#define RELAY_ACTIVE_LOW true

// Channel 1 on the backend maps to GPIO 40 through this firmware.
#define CONTROL_CHANNEL_1_PIN RELAY_CHANNEL_1_PIN

// =============================================
// Timing Configuration
// =============================================
#define MEASUREMENT_INTERVAL_MS 2000
#define PZEM_READ_INTERVAL_MS 1000
#define WIFI_CHECK_INTERVAL_MS 10000
#define DEVICE_REGISTER_RETRY_MS 30000
#define CONTROL_POLL_INTERVAL_MS 1000

// =============================================
// Serial Monitor Configuration
// =============================================
#define SERIAL_BAUD 115200

#endif // CONFIG_H
