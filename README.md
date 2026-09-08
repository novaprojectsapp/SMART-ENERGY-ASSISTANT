# Smart Energy Assistant

Local-First AI Energy Monitoring + Voice Assistant

## Architecture

```
Electrical Load → PZEM-004T → UART → ESP32-S3 → Wi-Fi → Client Laptop
                                                          ↓
                                              SmartEnergyAssistant
                                              ├── Python FastAPI Backend
                                              ├── HTML/CSS/JS Dashboard
                                              ├── SQLite Database
                                              ├── Energy Analytics
                                              ├── Billing Engine
                                              ├── Appliance ML (scikit-learn)
                                              ├── Natural Language AI
                                              ├── Voice Assistant
                                              └── Energy Coach
```

## Tech Stack

- **Backend**: Python 3.14, FastAPI, SQLAlchemy, SQLite
- **Frontend**: HTML, CSS, Vanilla JavaScript (no framework)
- **ML**: scikit-learn, joblib, numpy, pandas
- **LLM**: Google Gemini (optional, free tier)
- **Voice**: Web Speech API (browser-based)

## Quick Start

### Start Backend

```bash
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Open Dashboard

Open `frontend/index.html` in your browser, or navigate to `http://localhost:8000`

### Run Simulator

```bash
python simulator/simulator.py --mode varying --interval 5
```

### Run Tests

```bash
python -m pytest backend/tests/test_api.py -v
```

## Database

The application uses a local SQLite database located in the **project root**:

```
smart-energy-assistant/
└── smart_energy.db
```

- **Database type**: SQLite (local, no cloud required)
- **Location**: project root
- **Created/used by**: the Python FastAPI backend
- The database path is derived from the project root at runtime, so the entire project folder can be copied to another machine and will work without reconfiguration.

## Project Structure

```
smart-energy-assistant/
├── backend/               # Python FastAPI backend
│   ├── app/              # Application code
│   │   ├── main.py       # FastAPI app entry
│   │   ├── config.py     # Settings
│   │   ├── database.py   # SQLAlchemy setup
│   │   ├── models/       # DB models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── api/routers/  # API endpoints
│   │   ├── services/     # Business logic
│   │   ├── ai/           # NLU + LLM fallback
│   │   ├── billing/      # Billing engine
│   │   └── utils/        # Utilities
│   ├── config/tariffs/   # Tariff JSON configs
│   ├── tests/            # pytest tests
│   └── requirements.txt
├── frontend/             # HTML/CSS/JS dashboard
│   ├── index.html        # Main SPA
│   ├── css/              # Styles
│   └── js/               # Scripts
├── simulator/            # PZEM data simulator
├── ai/                   # ML pipeline (reserved for hardware)
├── data/                 # Data directories
├── database/
│   └── migrations/       # SQL migrations (reserved)
├── docs/
│   └── hardware-validation/  # Reserved for hardware docs
├── scripts/              # Reserved for helper scripts
├── smart_energy.db       # SQLite database (runtime)
└── requirements.txt
```

## Features

### Implemented
- FastAPI backend with SQLite
- Device management (register, list, status)
- PZEM-004T reading ingestion with validation
- Idempotent reading storage
- Dashboard with live power, voltage, current, frequency, PF cards
- Billing engine (Tamil Nadu Domestic Tariff)
- Slab calculation with transparent breakdown
- Monthly and bimonthly cost prediction
- Energy analytics (daily, weekly, monthly)
- Anomaly detection (statistical)
- Usage pattern analysis
- Local NLU intent engine (20+ intents)
- Gemini LLM fallback (optional)
- Voice assistant (Web Speech API)
- Text-to-speech responses
- Energy Coach recommendations
- What-If simulator
- Settings page
- Smart Appliance Scheduling & Control (see `docs/scheduling.md`)
- PZEM data simulator

### Requires Hardware
- ESP32-S3 + PZEM-004T for real energy measurements
- Appliance ML model training (needs hardware data collection)

### Requires Internet
- Google Gemini API for LLM fallback on uncertain queries

### Optional
- Voice input (requires browser with Web Speech API)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Health check |
| `/api/v1/devices` | GET/POST | List/register devices |
| `/api/v1/devices/{id}` | GET | Get device |
| `/api/v1/devices/{id}/status` | GET | Device status |
| `/api/v1/devices/{id}/readings` | GET/POST | Readings |
| `/api/v1/readings/latest` | GET | Latest readings |
| `/api/v1/billing/today` | GET | Today's billing |
| `/api/v1/billing/predict` | GET | Bill prediction |
| `/api/v1/billing/tariff` | GET | Tariff info |
| `/api/v1/analytics/summary` | GET | Analytics summary |
| `/api/v1/analytics/hourly` | GET | Hourly data |
| `/api/v1/analytics/daily` | GET | Daily data |
| `/api/v1/analytics/anomalies` | GET | Anomaly detection |
| `/api/v1/analytics/patterns` | GET | Usage patterns |
| `/api/v1/ai/insights` | GET | AI insights |
| `/api/v1/voice/query` | POST | Voice query |
| `/api/v1/recommendations` | GET | Recommendations |
| `/api/v1/what-if` | POST | What-If simulation |
| `/api/v1/reports/energy-summary` | GET | Energy report |
| `/api/v1/settings` | GET | Settings |
| `/api/v1/appliances` | GET/POST | List/register appliances |
| `/api/v1/appliances/{id}` | GET/PUT/DELETE | Get/update/delete appliance |
| `/api/v1/appliances/{id}/control` | POST | Manual ON/OFF (queues a PENDING ESP32 command) |
| `/api/v1/control-commands` | GET | Control command history (full lifecycle) |
| `/api/v1/devices/{id}/control/pending` | GET | ESP32 polling endpoint (compact JSON with `has_command` + `command_id`/`device_id`/`channel`/`action`) |
| `/api/v1/devices/{id}/control/{cmd}/ack` | POST | ESP32 acknowledgement (→ EXECUTED/FAILED) |
| `/api/v1/devices/{id}/control/status` | GET | Live device control status |
| `/api/v1/schedules` | GET/POST | List/create schedules |
| `/api/v1/schedules/{id}` | GET/PUT/DELETE | Get/update/delete schedule |
| `/api/v1/schedules/{id}/enable` `/disable` | POST | Enable/disable schedule |
| `/api/v1/scheduler/run` | POST | Run scheduler manually (safe, no GPIO) |

## ESP32 Connection

1. Find your laptop's local IP
2. Configure ESP32 to send POST requests to `http://<LAPTOP_IP>:8000/api/v1/devices/{device_id}/readings`
3. Ensure firewall allows port 8000
4. Both devices must be on same Wi-Fi network

The ESP32-S3-01 also **polls** `http://192.168.4.2:8000/api/v1/devices/ESP32-S3-01/control/pending`
about every second and acknowledges executed commands, so the relay on GPIO 40 is
driven reliably with honest confirmation back to the dashboard.

## Billing Engine

Tamil Nadu Domestic Tariff (prototype):

| Slab | Units | Rate |
|------|-------|------|
| 1 | 1-100 | Free |
| 2 | 101-200 | ₹2.35/unit |
| 3 | 201-500 | ₹4.45/unit |
| 4 | 501+ | ₹6.45/unit |

Billing period: 2 months (bimonthly)

## Smart Appliance Scheduling & Control

Register appliances and build recurring **ON/OFF time-pair** schedules
(ONCE / DAILY / WEEKLY) — a single schedule holds an ON time and an OFF time
(e.g. ON 18:00 → OFF 23:00, including overnight pairs like ON 23:00 → OFF 06:00).
Create them from the dashboard or by voice ("turn on bulb 1 at 6 PM and turn it off
at 11 PM every day"), and the scheduler runs automatically. See `docs/scheduling.md`.

> **Relay control is real and honest.** ON/OFF commands are queued as **PENDING**
> and executed by the **ESP32-S3-01** firmware on **GPIO 40 (active-low relay)**:
> the firmware polls the backend every second, drives the relay, and ACKs the
> result. A command is only marked **EXECUTED** after a real ESP32
> acknowledgement — the system never claims to have physically switched a device
> without an ACK. Commands expire after 60 seconds if the ESP32 never polls them.
> PZEM measurement, billing, analytics, and voice are unaffected.

## Safety Rules

1. Never fabricate sensor data
2. Never claim hardware validation without testing
3. LLM never calculates bills directly
4. LLM never invents measurements
5. All billing goes through central engine
6. Missing data shown as "NO DATA AVAILABLE"
7. Unavailable AI shown as "AI UNAVAILABLE"

## Client EXE Roadmap

Designed for future PyInstaller packaging:

1. `SmartEnergyAssistant.exe`
2. Configuration
3. ESP32 hardware
4. Wi-Fi
5. Browser or embedded browser view

No Python installation required for final client package.
