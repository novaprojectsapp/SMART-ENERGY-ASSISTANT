# Smart Energy Assistant - Client Guide

Your energy monitoring app runs entirely on your Windows PC. This guide tells
you everything you need to know.

## What you need

- A Windows laptop / PC
- The ESP32-S3 + PZEM-004T hardware unit (already set up)
- This application (a single `.exe` file)

## 1. First launch

1. Copy `SmartEnergyAssistant.exe` anywhere on the PC (for example to `C:\SmartEnergy`).
2. **Double-click** `SmartEnergyAssistant.exe`.
3. On the very first run, Windows may ask about a network connection
   ("Windows Security / Firewall"). Click **Allow** so the ESP32 can reach the app.
4. A small window opens: **"Smart Energy Assistant is running"**, and your
   default browser opens the dashboard automatically.
5. You can leave that small window open while using the app. Click **Exit**
   (or the X) to stop the app when you are done.

The dashboard address is `http://127.0.0.1:8000/`.

## 2. Connecting the ESP32

The ESP32 creates its own Wi-Fi network. Connect your PC/laptop to it:

| Setting | Value |
|---|---|
| Wi-Fi network (SSID) | `SmartEnergy` |
| Password | `SmartEnergy123` |
| ESP32 gateway | `192.168.4.1` |
| Your laptop's backend IP | `192.168.4.2` |

Important: the ESP32 sends data to the laptop at `192.168.4.2:8000`. The
laptop must have that IP while it is connected to the `SmartEnergy` Wi-Fi.
When your laptop joins the ESP32 hotspot it normally gets this IP
automatically.

Once connected, real meter readings appear on the dashboard within a few
seconds.

## 3. Where your data is stored

Everything is saved in a folder on your PC:

```
C:\Users\<your-user>\AppData\Local\SmartEnergyAssistant\
```

- `smart_energy.db` - your history, devices, billing, settings
- `logs\` - error and activity logs

Your data is kept between launches. Uninstalling/copying the `.exe` alone will
NOT delete this folder.

## 4. Troubleshooting

### Dashboard does not open
- Wait a few seconds after double-clicking - the app starts the backend first.
- Check the small running window for messages.
- If a Windows Firewall prompt appeared, make sure you clicked **Allow**.
- Look in `C:\Users\<your-user>\AppData\Local\SmartEnergyAssistant\logs\launcher.log` for errors.

### Port 8000 is already in use
The app needs port 8000. If another program already uses it, close that
program and start Smart Energy Assistant again. The app shows an error
message explaining this - it never closes other programs on its own.
Running Smart Energy Assistant twice is fine: the second time it simply
brings the dashboard up and does not start a second copy.

### ESP32 connected but no readings
- Confirm your PC is connected to Wi-Fi named `SmartEnergy`.
- Confirm your PC's IP is `192.168.4.2`.
  - Open Command Prompt and run `ipconfig`.
  - The Wi-Fi adapter in the `SmartEnergy` network should show IPv4
    `192.168.4.2`.
- Make sure the app is running and the running window is open.
- The dashboard "Device Status" should show **Online/Connected**. If it shows
  Offline, the ESP32 cannot reach the app - usually a firewall or IP issue.

### Laptop not using 192.168.4.2
Rarely a PC keeps an old IP. To renew:
1. Open Command Prompt as Administrator.
2. Run `ipconfig /release` then `ipconfig /renew`.
3. Reconnect to the `SmartEnergy` Wi-Fi if needed.
4. Check with `ipconfig` that the IP is now `192.168.4.2`.

### Firewall blocks port 8000
The app listens on port 8000 so the ESP32 can send data to your PC. If the
first-run prompt was declined, allow TCP port 8000 for
`SmartEnergyAssistant.exe` in Windows Defender Firewall (or add an inbound
rule for TCP port 8000). Do not disable the firewall itself.

## 5. Updating the app

When you get a new `.exe`, just replace the old file and double-click again.
Your data in `AppData\Local\SmartEnergyAssistant` is not touched and no data
is lost.