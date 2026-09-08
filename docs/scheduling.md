# Smart Appliance Scheduling & Control

This document describes the appliance scheduling and control feature.

> **STATUS: REAL ESP32 RELAY CONTROL — ACTIVE-LOW GPIO 40.**
>
> Scheduling is fully wired to the **ESP32-S3-01** firmware over the device's
> access-point network. The backend never touches GPIO directly: every ON/OFF
> request is persisted as a **PENDING control command** that the ESP32 polls every
> ~1 second, executes on the relay (GPIO 40, active-low), and acknowledges. A
> command is only marked **EXECUTED** after a real ESP32 acknowledgement. The
> system never claims it turned a device on or off on real hardware without an ACK.

---

## Overview

Scheduling is an **actuation** feature, distinct from PZEM energy measurement.
It adds:

- An **appliance registry** (name, type, channel, device, control capability)
- **Recurring schedules** (ONCE / DAILY / WEEKLY) where a single schedule holds an
  **ON/OFF time pair** (`on_time` / `off_time`), supporting overnight schedules
  (e.g. ON 23:00 → OFF 06:00 the next day) and independent ON / OFF events
- A **scheduler engine** that tracks the next ON and next OFF separately, finds
  due events with a duplicate-prevention guard, and produces control commands
- **Overlapping-schedule protection**: an automatic OFF event is suppressed when
  another enabled schedule window still requires the appliance to be ON
- A **background scheduler loop** (single daemon thread, started with the FastAPI
  lifespan) that runs due schedules automatically — no manual trigger needed
- **Manual control** for registered appliances, enqueued as PENDING commands
- An **ESP32 control adapter** backed by a poll/ack command queue
- **Voice / AI scheduling intents** with deterministic natural-language extraction
  and clarification ("Which appliance do you mean: …?", "What time should I turn
  it off?", "What time should I turn it on?")
- A **Smart Scheduler** page in the dashboard that shows live ESP32 connection
  status, confirmed relay state, and the command lifecycle

Existing PZEM ingestion, billing, Tamil Nadu tariff, the G4 appliance AI safety
gate, the simulator, voice machinery, PZEM GPIO 17/18, and the readings API are
**unchanged**.

---

## Architecture

The control path is a **command queue**, not a direct backend→ESP32 connection.
The backend persists a `PENDING` command; the ESP32 polls it, drives the relay,
and acknowledges the result.

```
Voice / AI intent -----------------------.
                                           v
                      +------------------------------------------+
Frontend (Smart      | backend/app/api/routers/scheduling.py    |
Scheduler page) ---->|  appliances / schedules / control        |
                      +------------------------------------------+
                                           |
              +---------------------------+----------------------------+
              v                            v                            v
  +---------------------+        +--------------------+   +------------------------------+
  | SchedulerService    |        | ScheduleActions    |   | ControlService               |
  | (engine, tz-aware)  |        | (voice resolution) |   | create/pending/dispatch/ack  |
  +---------------------+        +--------------------+   +------------------------------+
              |                                |                            |
              v                                v                            v
        ControlCommand (PENDING) -------> SQLite (schedules, appliances, control_commands)
                                                        ^
                                    HTTP poll + ack     |
                      +-----------------legal-----------+ /api/v1/devices/{id}/control/{pending|ack}
                      |                    |
              +-------+--------+    +------+----------------------+
              | ESP32-S3-01    |    | RelayManager GPIO 40        |
              | firmware: poll |--> | active-low (ON=LOW/OFF=HIGH)|
              | every ~1s      |    +-----------------------------+
              +----------------+
```

### New models

| Model | Table | Purpose |
|-------|-------|---------|
| `appliance.py`  | `appliances`        | Registered appliances (type, channel, `control_capable`, `last_confirmed_state`, `last_control_at`) |
| `schedule.py`   | `schedules`         | Recurring ON/OFF schedules (type, time, days, enabled) |
| `control_command.py` | `control_commands` | Persistent record of every control attempt + lifecycle state |

### New services / AI

| File | Purpose |
|------|---------|
| `services/scheduler.py` | Timezone-aware engine (`Asia/Kolkata` default): computes next execution, finds due schedules with a duplicate-prevention guard, suppresses overlapping OFF events, creates PENDING commands |
| `services/scheduler_loop.py` | Background loop: single daemon thread started with the FastAPI lifespan, own DB session per iteration, survives failures, disabled under `APP_TESTING=1` |
| `services/control_service.py` | Control command lifecycle: create (PENDING + TTL), pending lookup, dispatch/expiry, idempotent ESP32 acknowledgement |
| `services/esp32_control.py` | Hardware adapter used by the scheduling API to enqueue PENDING commands |
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
| `/api/v1/appliances/{id}/control` | POST | Manual control (ON/OFF), source USER/VOICE/SCHEDULE; creates a PENDING command and returns it |
| `/api/v1/devices/{device_id}/control/pending` | GET | ESP32 polling endpoint: returns the next non-expired PENDING/DISPATCHED command for the device as a compact JSON (or `{"has_command": false, "command": null}`) |
| `/api/v1/devices/{device_id}/control/{command_id}/ack` | POST | ESP32 acknowledgement: marks EXECUTED (success) or FAILED; device-mismatched ACKs are rejected with 403 |
| `/api/v1/devices/{device_id}/control/status` | GET | Live control status for a device (hardware availability + appliances + confirmed states) |
| `/api/v1/control-commands` | GET | Recent control command history (full lifecycle fields) |

### Pending-command wire contract (ESP32)

The polling response is deliberately **compact** — the ESP32 firmware parses it into a
fixed `StaticJsonDocument<512>` (ArduinoJson v6). A bloated payload (~305 bytes with
`id`/`appliance_id`/timestamps previously included) overflowed the 512-byte parse pool,
`deserializeJson()` returned `NoMemory`, and every command quietly expired. The contract
now carries only what the firmware needs:

```json
{"has_command": true, "command": {"command_id": "cf318789-...", "device_id": "ESP32-S3-01", "channel": 1, "action": "ON"}}
```

- `has_command: false` → `"command": null` (no pending work; do nothing).
- `has_command: true` → actuate `channel` to `action`, then
  `POST /api/v1/devices/{device_id}/control/{command_id}/ack`.
- The full lifecycle fields (`appliance_id`, `created_at`, `expires_at`, ...) remain
  available via `GET /control-commands`.

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

- A schedule is created with an **ON time** (`on_time`, required) and an optional
  **OFF time** (`off_time`). Internally `on_time` maps to `start_time` and
  `off_time` maps to `end_time`, so the existing columns are reused (no migration).
- `action` must be `ON` or `OFF`; a schedule with an `off_time` always leads with `ON`.
- `schedule_type` must be `ONCE`, `DAILY`, `WEEKLY`, or `AFTER_DURATION` (reserved).
- Times are `HH:MM` (24h); `days_of_week` are integers 0 (Mon)–6 (Sun).
- **ON time ≠ OFF time** for same-day schedules — equal times are rejected with
  *"ON time and OFF time cannot be the same."* (422)
- **Overnight pairs are allowed**: ON 23:00 / OFF 06:00 schedules the OFF on the
  **next day**, so the OFF is never treated as before the ON.
- **Weekly schedules require ≥ 1 day** (422 otherwise).
- Missing appliance → `404`; invalid action / time / type → `422`;
  non-control-capable appliance → `400`.
- Disabling a schedule clears `next_execution_at`; already-executed and deleted
  schedules are never re-run. After a restart, a fully-executed ON event is not
  re-fired past its time because `next_execution_at` is persisted.

### Next ON / Next OFF display

Each API schedule response includes the computed **`next_on_at`** and **`next_off_at`**
(naive-UTC datetimes). For overnight pairs the OFF is correctly reported on the day
after the ON.

### Control lifecycle (real ESP32 relay)

Commands move through a strict lifecycle. The backend **never** toggles GPIO and
**never** marks a command `EXECUTED` until the ESP32 acknowledges it:

```
PENDING (created, valid for 60s by default)
   │  ESP32 polls /control/pending (every ~1s)
   ▼
DISPATCHED (returned to the device, attempt_count += 1)
   │  ESP32 actuates relay on GPIO 40 (active-low) then POSTs /control/{id}/ack
   ├── success=true  ──►  EXECUTED  (+ confirmed_relay_state, appliance.last_confirmed_state)
   └── success=false ──►  FAILED
   │  (expires_at passed before any ack) ──► EXPIRED (never executed)
```

Honesty rules:

- Every manual, voice, or scheduled command returns **`PENDING`** — the backend
  confirms it queued the command for the ESP32, nothing more.
- **`EXECUTED`** is only set by an acknowledgement from the device that owns the
  command; ACKs from a different device are rejected (403).
- ACK handling is **idempotent**: a duplicate ACK never corrupts state or re-runs
  the relay (the firmware also keeps the last command id and re-ACKs, not
  re-executes, a repeated poll).
- Commands expire after the TTL (`SEA_CONTROL_TTL_SECONDS`, default **60s**) and
  are never delivered to or executed by the ESP32 after expiry.
- Scheduled automatic **OFF** events are suppressed when any other enabled
  schedule window still requires the appliance ON (no relay flapping at 22:00
  when another schedule runs until 23:00).

---

## Voice / AI scheduling

Deterministic extraction runs locally (no LLM needed for the core flow):

- **Time**: `6 PM`, `10:30 PM`, `18:00`, `at six`, `at 6`, `half past ten`,
  `quarter past nine`, `every night at 10 PM`
- **Recurrence**: `every day` (DAILY), `once`/`tomorrow` (ONCE),
  `every monday and friday` / `weekdays` (WEEKLY)
- **ON/OFF pair**: `at 6 PM and off at 11 PM`, `from 7 PM to 10 PM`,
  `turn it off at 11 PM` (as a follow-up), overturning `23:00 → 06:00`
- **Appliance**: `bulb 1`, `fan 2`, `bedroom light`, `pump`, `ac`, …

Examples:

| Utterance | Result |
|-----------|--------|
| `turn on bulb 1 at 6 PM and turn it off at 11 PM every day` | Creates a DAILY ON 18:00 → OFF 23:00 pair |
| `schedule bulb 1 from 7 PM to 10 PM Monday and Friday` | Creates a WEEKLY pair 19:00 → 22:00 |
| `turn on pump 1 at 6 PM every day` (ON only) | *"… What time should I turn it off?"* (clarification) |
| `turn off fan 2 at 11 PM` (OFF only) | *"… What time should I turn it on?"* (clarification) |
| `show my schedules` | Lists schedules |
| `turn off fan 1` | Queues a PENDING OFF command for the ESP32 (waits for ACK) |
| `disable the pump schedule` | Disables matching schedule(s) |
| `schedule the bulb` (two bulbs) | *"Which appliance do you mean: Bulb A, Bulb B?"* |
| `schedule the socket` (no time) | *"… What time?"* |

Rules:
- Missing required fields → the assistant asks a clarifying question, and an
  **ON-only or OFF-only request is completed into a pair** by asking for the
  missing opposite time.
- Multiple matching appliances → the assistant asks "Which appliance do you mean: …?".
- The assistant **never guesses** and **never creates an incomplete schedule**.

---

## Frontend (Smart Scheduler page)

Located at `frontend/js/scheduler.js`, reachable via the **Smart Scheduler** nav item:

- **ESP32 status banner**: polls `GET /devices/{primary}/control/status` every ~3s —
  shows the device as **ESP32-S3-01 online** (with the last confirmed relay state)
  or offline, plus per-appliance confirmed state
- **Connected Appliances** cards with manual ON/OFF and delete. Manual controls run
  a live flow: *"Sending command…" → "Waiting for ESP32…" → "ESP32 confirmed ON" /
  "ESP32 reported failure"*, polled via the pending/ack endpoints
- **Add Appliance** form (name, type, channel, device)
- **Schedules** table with ON/OFF times and **Next (next ON / next OFF)** column,
  plus edit, enable/disable, and delete; weekly day checkboxes
- **Add/Edit Schedule** form with ONCE/DAILY/WEEKLY repeat, an **ON Time** and an
  **OFF Time** input (overnight pairs allowed), and a day picker
- **Control Command History** with lifecycle badges — PENDING, DISPATCHED,
  **EXECUTED**, **FAILED**, **EXPIRED** — including the confirmed relay state
- Page lifecycle: the polling timer is torn down via `destroyScheduler()` when the
  dashboard unloads the page, so background polling stops (single interval, no leaks)

---

## Testing

```bash
# All tests (isolated test DB, production untouched)
python -m pytest backend/tests/ -v
```

- `backend/tests/test_api.py`: appliance/schedule/control CRUD, scheduler engine
  (due-once, disabled/deleted skip, duplicate-prevention, next-execution),
  **ON/OFF pair creation (daily/weekly), overnight pairs, ON≠OFF validation,
  weekly-requires-day validation, pair execution, overnight next-ON/next-OFF**,
  and the **real ESP32 control lifecycle** (manual ON/OFF → PENDING, pending
  returned only to the owning device, ACK success → EXECUTED + confirmed state,
  ACK failure → FAILED, idempotent re-ACK, wrong-device ACK → 403, expiry,
  DAILY/WEEKLY/ONCE/overnight scheduling, overlapping-schedule OFF suppression,
  disabled/deleted schedules emit nothing, background loop start-once, primary
  ESP32-S3-01 unchanged, and PZEM ingestion still intact).
- `backend/tests/test_scheduling_voice.py`: voice create (pair + from/to ranges),
  clarify missing ON / missing OFF, list / **manual (PENDING)** / disable / delete
  and clarification paths, in a freshly reset isolated DB.

Tests run with `APP_TESTING=1` set before import so they use
`test_smart_energy.db` and never touch `smart_energy.db`.

---

## Production database safety

The production database (`smart_energy.db`) is upgraded **in place** on first run
by a safe migration (`database.py::_safe_migrate`) that only adds the new
`control_commands` / `appliances` columns (`command_id`, `device_id`, `channel`,
`confirmed_relay_state`, `expires_at`, `dispatched_at`, `acknowledged_at`,
`executed_at`, `attempt_count`, `last_confirmed_state`, `last_control_at`) — no
existing data is dropped or rewritten. The primary ESP32 device stays
**ESP32-S3-01**; PZEM readings, billing, analytics, voice, and the EXE packaging
are unchanged.
