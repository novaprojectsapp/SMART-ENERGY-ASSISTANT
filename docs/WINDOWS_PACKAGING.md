# Windows Packaging Guide

How to build and test the one-click Windows application
`SmartEnergyAssistant.exe`.

## Overview

The packaged app is a single-file, no-console executable produced by
PyInstaller. It embeds:

- the FastAPI backend (`backend/app/`)
- the static dashboard (`frontend/`)
- the tariff configuration (`backend/config/tariffs/`)

At runtime a small Python launcher (`launcher.py`) starts the backend
in-process on `0.0.0.0:8000`, waits for the health endpoint, opens the
dashboard browser window, and keeps a small window open that shuts the
backend down when closed.

## Prerequisites

- Windows 10/11
- Python 3.12+ (developed/tested with 3.14)
- Backend dependencies installed (see `backend/requirements.txt`):
  `pip install -r backend/requirements.txt`
- PyInstaller (auto-installed by the build script if missing):
  `pip install pyinstaller`

## Build command

From the repository root, run either:

```batch
python scripts\build_windows.py
```

or double-click `scripts\build_windows.bat`.

Output:

```
dist\SmartEnergyAssistant.exe
```

Build options live at the top of `scripts/build_windows.py` (data files,
hidden imports, excluded heavy packages). The heavy ML/data-science packages
in `requirements.txt` are intentionally excluded because they are imported
nowhere at runtime and would bloat the EXE.

## How the app chooses its paths

`backend/app/paths.py` centralizes path logic and distinguishes between:

- **Read-only resources** (`resource_dir()`): the packed `frontend/` and
  `backend/config/tariffs/`. Inside the EXE these are extracted to a temp
  directory (`sys._MEIPASS`); in development they are the repository folders.
- **Writable client data** (`data_dir()`):
  `%LOCALAPPDATA%\SmartEnergyAssistant\` in the packaged app (override with
  the `SEA_DATA_DIR` environment variable); in development it falls back to
  the repository root.

The database URL is derived via `database_url()` in `paths.py`, so the SQLite
file always lands in the writable folder, never inside the read-only
extraction directory. Logs go to `%LOCALAPPDATA%\SmartEnergyAssistant\logs\`.

## How database persistence works

- On first launch the launcher creates the app-data directory and, if no
  `smart_energy.db` exists yet, it seeds it from the repository database
  (only when running from source). In the packaged app a fresh database is
  created automatically.
- Subsequent launches reuse the existing file - data is never overwritten.
- WAL journaling is enabled (see `backend/app/database.py`), so the database
  survives even a hard kill of the process.

## Runtime behavior (launcher.py)

1. Redirects `sys.stdout`/`sys.stderr` to `devnull` when frozen (windowed
   apps have no console).
2. Claims a single-instance Windows mutex; a second launch simply opens the
   dashboard again and exits.
3. Probes port 8000. If it is occupied by an unrelated program, shows a clear
   error dialog and exits (never kills the other process).
4. Starts uvicorn in a background thread on `0.0.0.0:8000`.
5. Polls `GET /api/v1/health` (bounded retry) until genuinely ready.
6. Opens the dashboard in the default browser (once).
7. Keeps a small Tk window alive; closing it requests a graceful backend
   shutdown.

## Testing the EXE

1. Build (see above).
2. Copy `dist\SmartEnergyAssistant.exe` to a folder OUTSIDE the repository
   (e.g. `C:\Users\<you>\Desktop\sea-test\`) - this proves no relative
   development paths are used.
3. Double-click it. Verify in a browser at `http://127.0.0.1:8000/`:
   - Dashboard loads.
   - `GET http://127.0.0.1:8000/api/v1/health` -> `{"status":"ok",...}`.
   - Database file created at `%LOCALAPPDATA%\SmartEnergyAssistant\smart_energy.db`.
   - Post the ESP32 payload:
     `POST http://127.0.0.1:8000/api/v1/devices/ESP32-S3-01/readings`
     with `{"voltage":276.4,"current":0.313,"power":41.2,"energy":0.065,"frequency":50.0,"power_factor":0.48}`
     -> 200/201, stored with `data_source: HARDWARE`.
   - Restart the EXE and confirm the reading/device are still present.
4. Automated regression tests: from `backend/`, run `python -m pytest -q`.

## Networking constraints (important)

- The backend binds `0.0.0.0:8000`, NOT `127.0.0.1`, so the ESP32 can reach
  it over the laptop's Wi-Fi hotspot interface.
- The ESP32 firmware posts to `http://192.168.4.2:8000` (hardcoded). The
  laptop must have IP `192.168.4.2` while connected to the `SmartEnergy`
  SSID. This is not changed by the app.
- Windows Firewall will prompt on the first run; it must be allowed for
  inbound TCP 8000. The app never disables or alters the firewall itself.

## Known limitations

- Built for Windows only (uses a Win32 mutex; on other platforms the
  single-instance behavior relies on the port/health probe).
- The EXE is unsigned; Windows SmartScreen may warn when it is first run or
  copied from another machine. Choose "More info -> Run anyway".
- Voice Assistant speech recognition runs in the browser (Web Speech API) and
  needs Chrome/Edge; it is unaffected by packaging.
- If `GEMINI_API_KEY` is configured via environment variables, set them in
  the same session that starts the EXE (the packaged app reads environment
  variables at startup).