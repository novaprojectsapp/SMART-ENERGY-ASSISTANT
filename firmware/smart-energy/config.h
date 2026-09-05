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
#define BACKEND_HOST "192.168.4.2"
#define BACKEND_PORT 8000

// =============================================
// Device Configuration
// =============================================
#define DEVICE_ID "ESP32-S3-01"
#define DEVICE_NAME "ESP32-S3 Smart Energy"

// =============================================
// Timing Configuration
// =============================================
#define MEASUREMENT_INTERVAL_MS 2000
#define PZEM_READ_INTERVAL_MS 1000
#define WIFI_CHECK_INTERVAL_MS 10000
#define DEVICE_REGISTER_RETRY_MS 30000

// =============================================
// Serial Monitor Configuration
// =============================================
#define SERIAL_BAUD 115200

#endif // CONFIG_H
