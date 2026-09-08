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
