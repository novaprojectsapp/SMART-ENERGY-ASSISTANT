# Smart Appliance Scheduling & Control

This document describes the appliance scheduling and control feature.

> **STATUS: SCHEDULING SOFTWARE READY — PHYSICAL APPLIANCE CONTROL PENDING HARDWARE.**
>
> The software can register appliances, build recurring ON/OFF schedules, run a
> scheduler engine, and record control commands. Real physical switching (turning
> a relay on/off on the ESP32) is **not yet connected**. Until the ESP32 relay
> firmware/hardware exists, every control command is returned honestly as
> **SIMULATED / PENDING** with the message
> *"Hardware control is not connected yet."* The system never claims it turned a
> device on or off on real hardware.

---

## Overview

Scheduling is an **actuation** feature, distinct from PZEM energy measurement.
It adds:

- An **appliance registry** (name, type, channel, device, control capability)
- **Recurring schedules** (ONCE / DAILY / WEEKLY) with an ON / OFF action and time
- A **scheduler engine** that finds due schedules and produces control commands
- **Manual control** for registered appliances
- An **ESP32 control adapter** that returns `HARDWARE_CONTROL_NOT_AVAILABLE` until
  relay hardware is present
- **Voice / AI scheduling intents** with deterministic natural-language extraction
  and clarification ("Which appliance do you mean: …?", "What time?")
- A **Smart Scheduler** page in the dashboard

Existing PZEM ingestion, billing, Tamil Nadu tariff, the G4 appliance AI safety
gate, the simulator, voice machinery, GPIO17/18, and the readings API are
**unchanged**.

---

## Architecture

```
Voice / AI intent -----------------------.
                                          v
                     +-----------------------------------------+
Frontend (Smart      | backend/app/api/routers/scheduling.py   |
Scheduler page) ---->|  appliances / schedules / control      |
                     +-----------------------------------------+
                                          |
              +---------------------------+----------------------------+
              v                            v                            v
  +---------------------+        +--------------------+   +--------------------------+
  | SchedulerService    |        | ScheduleActions    |   | ESP32ControlService       |
  | (engine, tz-aware)  |        | (voice resolution) |   | (adapter)                 |
  +---------------------+        +--------------------+   | HARDWARE_CONTROL_         |
              |                                |          | NOT_AVAILABLE             |
              v                                v          +--------------------------+
        ControlCommand -------> SQLite (schedules, appliances, control_commands)
```

### New models

| Model | Table | Purpose |
|-------|-------|---------|
| `appliance.py`  | `appliances`        | Registered appliances (type, channel, `control_capable`) |
| `schedule.py`   | `schedules`         | Recurring ON/OFF schedules (type, time, days, enabled) |
| `control_command.py` | `control_commands` | Persistent record of every control attempt + its status |

### New services / AI

| File | Purpose |
|------|---------|
| `services/scheduler.py` | Timezone-aware engine (`Asia/Kolkata` default): computes next execution, finds due schedules with a duplicate-prevention guard, executes and records commands |
| `services/esp32_control.py` | Hardware adapter. Returns `HARDWARE_CONTROL_NOT_AVAILABLE` when no relay hardware is connected |
| `ai/schedule_parser.py` | Deterministic NL extraction (time, recurrence, action, appliance ref) with no external LLM dependency |
| `ai/schedule_actions.py` | Appliance resolution (exact + fuzzy with ambiguity detection), schedule CRUD, clarification, multi-turn draft store |

### New / updated AI layers

- `ai/intent_engine.py` — added `CREATE_SCHEDULE`, `UPDATE_SCHEDULE`,
  `DELETE_SCHEDULE`, `ENABLE_SCHEDULE`, `DISABLE_SCHEDULE`, `LIST_SCHEDULES`,
  `LIST_APPLIANCES`, `MANUAL_APPLIANCE_ON/OFF` intents, attaching parsed `extra`.
- `ai/llm_fallback.py` — extended the valid-intent list for optional Gemini fallback.
- `api/routers/voice.py` — `_handle_intent` handles all scheduling intents via
  `ScheduleActions`, with a multi-turn draft store keyed by device.

---

## API Endpoints

### Appliances

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/appliances` | GET | List appliances |
| `/api/v1/appliances` | POST | Register an appliance |
| `/api/v1/appliances/{id}` | GET | Get one appliance |
| `/api/v1/appliances/{id}` | PUT | Update an appliance |
| `/api/v1/appliances/{id}` | DELETE | Delete an appliance (and its schedules) |

### Control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/appliances/{id}/control` | POST | Manual control (ON/OFF), source USER/VOICE; returns honest status |
| `/api/v1/control-commands` | GET | Recent control command history |

### Schedules

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/schedules` | GET | List schedules (refreshes next execution) |
| `/api/v1/schedules` | POST | Create a schedule |
| `/api/v1/schedules/{id}` | GET | Get one schedule |
| `/api/v1/schedules/{id}` | PUT | Update a schedule |
| `/api/v1/schedules/{id}` | DELETE | Delete a schedule |
| `/api/v1/schedules/{id}/enable`  | POST | Enable a schedule |
| `/api/v1/schedules/{id}/disable` | POST | Disable a schedule |
| `/api/v1/scheduler/run` | POST | Manually run the scheduler (safe, no GPIO) |

### Schedule validation

- `action` must be `ON` or `OFF`.
- `schedule_type` must be `ONCE`, `DAILY`, `WEEKLY`, or `AFTER_DURATION` (reserved).
- `start_time` must be `HH:MM` (24h), `days_of_week` integers 0 (Mon)–6 (Sun).
- Missing appliance → `404`; invalid action / time / type → `422`;
  non-control-capable appliance → `400`.
- Disabling a schedule clears `next_execution_at`; already-executed and deleted
  schedules are never re-run.

### Control honesty rules

- Routing an ON/OFF goes through `ESP32ControlService`. Until relay hardware
  acknowledges, the response is:
  - `status = "SIMULATED"` (manual / voice) or `"PENDING"` (scheduler)
  - `message = "SIMULATED: <name> would turn ON/OFF. Hardware control is not connected yet."`
  - `hardware_control_available = false`
- The system never claims it physically turned a device on or off.

---

## Voice / AI scheduling

Deterministic extraction runs locally (no LLM needed for the core flow):

- **Time**: `6 PM`, `10:30 PM`, `18:00`, `at six`, `at 6`, `half past ten`,
  `quarter past nine`, `every night at 10 PM`
- **Recurrence**: `every day` (DAILY), `once`/`tomorrow` (ONCE),
  `every monday and friday` / `weekdays` (WEEKLY)
- **Appliance**: `bulb 1`, `fan 2`, `bedroom light`, `pump`, `ac`, …

Examples:

| Utterance | Result |
|-----------|--------|
| `turn on bulb 1 at 6 PM every day` | Creates a DAILY ON schedule at 18:00 |
| `show my schedules` | Lists schedules |
| `turn off fan 1` | Records a SIMULATED OFF command |
| `disable the pump schedule` | Disables matching schedule(s) |
| `schedule the bulb` (two bulbs) | *"Which appliance do you mean: Bulb A, Bulb B?"* |
| `schedule the socket` (no time) | *"… What time?"* |

Rules:
- Missing required fields → the assistant asks a clarifying question.
- Multiple matching appliances → the assistant asks "Which appliance do you mean: …?".
- The assistant **never guesses** and **never creates an incomplete schedule**.

---

## Frontend (Smart Scheduler page)

Located at `frontend/js/scheduler.js`, reachable via the **Smart Scheduler** nav item:

- **Connected Appliances** cards with manual ON/OFF (recorded as SIMULATED) and delete
- **Add Appliance** form (name, type, channel, device)
- **Schedules** table with edit, enable/disable, and delete; weekly day checkboxes
- **Add/Edit Schedule** form with ONCE/DAILY/WEEKLY repeat and day picker
- **Control Command History** with an honest footnote:
  *"Hardware control is not connected yet — commands are recorded as SIMULATED/PENDING until ESP32 relay control firmware is integrated."*

---

## Testing

```bash
# All tests (isolated test DB, production untouched)
python -m pytest backend/tests/ -v
```

- `backend/tests/test_api.py`: appliance/schedule/control CRUD, scheduler engine
  (due-once, disabled/deleted skip, duplicate-prevention, next-execution),
  control honesty, and a test that asserts tests run against the isolated test DB.
- `backend/tests/test_scheduling_voice.py`: voice create / list / manual /
  disable / delete and clarification paths, in a freshly reset isolated DB.

Tests run with `APP_TESTING=1` set before import so they use
`test_smart_energy.db` and never touch `smart_energy.db`.

---

## Production database safety

The production database (`smart_energy.db`) is intentionally left at its original
state — **2 devices / 8 HARDWARE readings** — with no appliances, schedules, or
control commands created by the feature. As soon as real hardware is available,
follow `docs/hardware-validation/` for integrating the ESP32 relay control path.
