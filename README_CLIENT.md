# SMART ENERGY ASSISTANT

**Real-time electrical energy monitoring for your home — ready to use, no setup hassle.**

Smart Energy Assistant monitors live electrical usage using an **ESP32-S3** and a **PZEM-004T** energy meter. Everything runs from a single application on your Windows PC and shows your readings on a clear, easy-to-read dashboard.

### Features

- Live energy monitoring
- Voltage monitoring
- Current monitoring
- Power monitoring
- Energy consumption tracking
- Cost and billing analysis
- AI insights
- Energy recommendations
- Reports and analytics
- Voice assistant

---

## 1. What You Received

You receive a **single, self-contained executable** file. It includes the dashboard, the storage system, and everything needed to run — nothing else has to be installed on your PC.

```
Smart Energy Assistant/
│
├── SmartEnergyAssistant.exe
└── README_CLIENT.md
```

> **Why it is self-contained:** the `.exe` starts its own background service, opens the dashboard in your browser, saves data locally, and stops cleanly when you close it. You do **not** need to install Python, databases, or any other software.

---

## 2. System Requirements

### Required

| Item | Requirement |
|---|---|
| Computer | Windows 10 or Windows 11 (laptop or PC) |
| Network | Wi-Fi enabled laptop/PC |
| Hardware | ESP32-S3 powered on |
| Hardware | PZEM-004T properly connected |
| Electrical | Monitoring hardware working (meter wired to the load) |

### Not required

- Python
- FastAPI / Uvicorn / Node.js / npm
- Arduino IDE
- Database installation (SQLite, MySQL, etc.)
- Any software dependencies or developer tools

---

## 3. First-Time Setup

Follow these steps in order.

### Step 1 — Power ON the hardware

Make sure the **ESP32-S3 and PZEM-004T** are powered on and the PZEM is connected correctly to the load you want to monitor.

### Step 2 — Connect the laptop to the ESP32 Wi-Fi

On your Windows PC, open **Settings → Wi-Fi** and connect to the ESP32's own network:

| Setting | Value |
|---|---|
| Wi-Fi network (SSID) | `SmartEnergyESP32` |
| Password | `SmartEnergy123` |

### Step 3 — Wait for the connection

Wait until Windows shows the laptop is connected to `SmartEnergyESP32`.

### Step 4 — Open the app (the IP is automatic)

The ESP32 hotspot provides the laptop **any free address** it chooses
(`192.168.4.2`, `192.168.4.3`, ...). You never need to know it:

| Item | Value |
|---|---|
| ESP32 Access Point | `192.168.4.1` |
| Laptop / backend | auto-detected (`192.168.4.X`) |
| Backend port | `8000` |
| Primary device ID | `ESP32-S3-01` |

> **The address is automatic.** `SmartEnergyAssistant.exe` detects the laptop's
> current IPv4 address and sends it to the ESP32 (`POST /api/backend/config` on
> `192.168.4.1`). No IP editing, no CMD commands, no firmware changes — the ESP32
> simply starts uploading to the detected URL (`http://192.168.4.X:8000`).

---

## 4. Starting the Application

1. **Double-click** `SmartEnergyAssistant.exe`.
2. **Wait a few seconds** while it starts (a small window titled *"Smart Energy Assistant is running"* appears).
3. On the **first run only**, the app adds the Windows Firewall rule
   `SmartEnergyBackend8000` automatically so the hardware can reach the app
   (no manual firewall setup needed).
4. The app detects your laptop's IP, configures the ESP32 with it, and your
   **dashboard opens automatically** in the default browser.

The dashboard is normally available at:

```
http://127.0.0.1:8000/
```

> You do **not** need to type any commands or install anything. The application does everything itself.

---

## 5. Checking Live Data

Once everything is running, your dashboard should show:

- Device **connected/online** status
- **Recent update time** (readings arrive every few seconds)
- **Live voltage**
- **Live current**
- **Live power**
- **Energy consumption**
- **Frequency**
- **Power factor**

Live readings update automatically about every few seconds when **all** of these are true:

- [ ] ESP32 is powered on
- [ ] PZEM-004T communication is working
- [ ] Laptop is connected to the `SmartEnergyESP32` Wi-Fi
- [ ] `SmartEnergyAssistant.exe` is running

---

## 6. Using the Dashboard

### Live Monitor
See your real-time electrical measurements — voltage, current, power, frequency and power factor at a glance.

### AI Insights
Automatically generated observations about how you are using energy.

### Cost & Billing
Estimated energy consumption and the corresponding electricity cost.

### Energy Recommendations
Practical suggestions for reducing your energy consumption.

### Reports & Analytics
Historical consumption and trends over hours, days and weeks.

### What-If Simulator
Explore "what if" energy-use scenarios to see how they would affect cost.

### Voice Assistant
Ask questions aloud (or by typing) about current power, energy usage, billing and system status.

---

## 7. Closing the Application

To stop the application:

1. Click **Exit** in the small running window, or simply **close the window** (✕).

Closing it:

- Safely stops the background service
- **Does not delete your data**
- Keeps all previously stored readings for next time

---

## 8. Data Storage

The application saves all data **locally on your Windows PC**, in a private application folder:

```
%LOCALAPPDATA%\SmartEnergyAssistant\
```

Example location on most PCs:

```
C:\Users\<your-user>\AppData\Local\SmartEnergyAssistant\
```

- Your history is **saved automatically**.
- **Closing or restarting the application never erases** your previous readings.
- **Do not delete or move** this folder unless you are asked to — it holds your data.

---

## 9. Troubleshooting

| Problem | Possible solution |
|---|---|
| Dashboard does not open | Wait a few seconds, then check that `SmartEnergyAssistant.exe` is still running and its small window is open. |
| Dashboard shows "Connect this laptop to SmartEnergyESP32 Wi-Fi..." | The laptop is not connected to the hardware Wi-Fi. Connect to `SmartEnergyESP32` (password `SmartEnergy123`) — the app will pick it up automatically, no restart needed. |
| Dashboard shows Offline | Check the ESP32 power; check the PZEM power; make sure the laptop is connected to `SmartEnergyESP32` Wi-Fi; make sure `SmartEnergyAssistant.exe` is running; wait a few seconds. |
| Dashboard is connected but readings do not update | Confirm the ESP32 is powered; confirm the PZEM is connected; confirm the laptop is on `SmartEnergyESP32` Wi-Fi; make sure no other Wi-Fi network is controlling the connection; restart `SmartEnergyAssistant.exe`; restart the ESP32 if needed. |
| Wi-Fi is connected but no data appears | The app pushes the backend URL to the ESP32 automatically. Confirm the laptop is on `SmartEnergyESP32` Wi-Fi, `SmartEnergyAssistant.exe` is running, and firewall rule `SmartEnergyBackend8000` was allowed (added automatically on first run). |
| "SmartScreen" warning appears | The application is currently an **unsigned** Windows executable, so Windows may show a blue warning. If it appears, choose **More info → Run anyway**. This is normal for new unbranded software and is safe when you received the file from us. |

---

## 10. Important Usage Notes

- Keep the **ESP32 powered on** while using live monitoring.
- Keep the laptop **connected to the `SmartEnergyESP32` Wi-Fi**.
- **Do not change** the ESP32 hotspot configuration unless we tell you to.
- **Do not delete** application data unless we tell you to.
- The laptop address (`192.168.4.X`) is detected automatically — you never need to enter or edit it.
- An **internet connection is not required** for the local ESP32 → laptop monitoring to work.

---

## 11. Quick Start Checklist

- [ ] ESP32 powered ON
- [ ] PZEM connected
- [ ] Laptop Wi-Fi ON
- [ ] Connected to `SmartEnergyESP32`
- [ ] `SmartEnergyAssistant.exe` started
- [ ] Firewall rule added automatically (first run)
- [ ] Dashboard opened
- [ ] Live readings updating

---

## 12. Support Information

For technical support, contact:

**[PROJECT PROVIDER / CONTACT DETAILS]**

*(This section will be completed with your provider name, email and phone number.)*