import sys
import os

# Isolated test DB must be active BEFORE importing app modules.
os.environ["APP_TESTING"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    """Reset the test DB once so Phase 2 scheduling tests run against a
    controlled, empty appliance set."""
    from app.database import init_db, engine, Base
    Base.metadata.drop_all(bind=engine)
    init_db()


from app.main import app  # noqa: E402

client = TestClient(app)


def _device(did):
    r = client.post("/api/v1/devices", json={"id": did, "name": did, "device_type": "PZEM-004T"})
    assert r.status_code == 201, r.text
    return did


def _appliance(name, ctype, channel, did, capable=True):
    r = client.post("/api/v1/appliances", json={
        "name": name, "type": ctype, "channel": channel, "device_id": did, "control_capable": capable,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _voice(text, device_id):
    return client.post("/api/v1/voice/query", json={"text": text, "device_id": device_id}).json()


def _post_reading(did, voltage):
    r = client.post(f"/api/v1/devices/{did}/readings", json={
        "voltage": voltage, "current": 1.0, "power": voltage * 1.0,
        "energy": 1.0, "frequency": 50.0, "power_factor": 0.95,
        "data_source": "SIMULATOR",
    })
    assert r.status_code == 201, r.text


def _schedules():
    return client.get("/api/v1/schedules").json()


# ---------------------------------------------------------------------------
# Single-event scheduling (no forced ON/OFF pair)
# ---------------------------------------------------------------------------
def test_p2_single_on_daily():
    did = _device("p2-on-daily")
    _appliance("Bedroom Bulb", "BULB", 1, did)
    d = _voice("turn on the bedroom bulb at 6 PM every day", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"]
    assert "at 18:00" in d["response"]
    rows = [s for s in _schedules() if s["on_time"] == "18:00" and s["off_time"] is None]
    assert rows
    assert rows[0]["action"] == "ON"
    assert rows[0]["schedule_type"] == "DAILY"


def test_p2_single_off_tonight():
    did = _device("p2-off-tonight")
    _appliance("Kitchen Light", "LIGHT", 2, did)
    d = _voice("turn off the kitchen light at 10 tonight", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"]
    assert "at 22:00" in d["response"]
    rows = [s for s in _schedules() if s["on_time"] == "22:00" and s["off_time"] is None]
    assert rows
    assert rows[0]["action"] == "OFF"
    assert rows[0]["schedule_type"] == "DAILY"


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------
def test_p2_weekdays_and_weekends():
    did = _device("p2-recur")
    fan = _appliance("Bathroom Fan", "FAN", 1, did)
    bulb = _appliance("Desk Bulb", "BULB", 2, did)
    d = _voice("turn off the bathroom fan at 10 PM on weekdays", did)
    assert "Scheduled" in d["response"]
    weekday = [s for s in _schedules() if s["appliance_id"] == fan["id"] and s["action"] == "OFF"]
    assert weekday and weekday[0]["start_time"] == "22:00"
    assert weekday[0]["schedule_type"] == "WEEKLY"
    assert weekday[0]["days_of_week"] == [0, 1, 2, 3, 4]

    d = _voice("turn on the desk bulb at 8 PM on weekends", did)
    assert "Scheduled" in d["response"]
    weekend = [s for s in _schedules() if s["appliance_id"] == bulb["id"] and s["action"] == "ON"]
    assert weekend and weekend[0]["start_time"] == "20:00"
    assert weekend[0]["schedule_type"] == "WEEKLY"
    assert weekend[0]["days_of_week"] == [5, 6]


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------
def test_p2_contextual_morning_and_noon():
    did = _device("p2-time")
    _appliance("Fan 1", "FAN", 1, did)
    _appliance("Fan 2", "FAN", 2, did)
    d = _voice("turn on fan 1 at 7 in the morning", did)
    assert "at 07:00" in d["response"]
    d = _voice("turn off fan 2 at noon", did)
    assert "at 12:00" in d["response"]


def test_p2_midnight_and_wordtime():
    did = _device("p2-midnight")
    _appliance("Fan 1", "FAN", 1, did)
    _appliance("Fan 2", "FAN", 2, did)
    d = _voice("turn off fan 1 at midnight", did)
    assert "at 00:00" in d["response"]
    d = _voice("turn off fan 2 at half past six", did)
    assert "at 06:30" in d["response"]


def test_p2_ambiguous_time_asks_am_pm_then_fills():
    did = _device("p2-bare")
    fan = _appliance("Fan 1", "FAN", 1, did)
    d = _voice("turn on the fan at 6", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "6 AM or 6 PM" in d["response"]
    assert not [s for s in _schedules() if s["appliance_id"] == fan["id"]]
    d = _voice("6 PM", did)
    assert "Scheduled" in d["response"]
    assert "at 18:00" in d["response"]
    rows = [s for s in _schedules() if s["appliance_id"] == fan["id"]]
    assert rows


# ---------------------------------------------------------------------------
# Multi-turn clarification
# ---------------------------------------------------------------------------
def test_p2_multiturn_action_and_time():
    did = _device("p2-mt")
    _appliance("Fan 1", "FAN", 1, did)
    d = _voice("schedule the fan", did)
    assert "ON or OFF" in d["response"]
    d = _voice("turn it on", did)
    assert "What time" in d["response"]
    d = _voice("6 PM", did)
    assert "Scheduled" in d["response"]
    assert "at 18:00" in d["response"]


# ---------------------------------------------------------------------------
# Control vs schedule
# ---------------------------------------------------------------------------
def test_p2_control_vs_schedule():
    did = _device("p2-cvs")
    _appliance("Bulb 1", "BULB", 1, did)
    _appliance("Pump 1", "PUMP", 1, did)
    d = _voice("turn on the bulb", did)
    assert d["intent"] == "MANUAL_APPLIANCE_ON"
    assert "Waiting for confirmation" in d["response"]
    d = _voice("turn on the pump at 6 PM", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
def test_p2_update_reschedule_time():
    did = _device("p2-upd")
    a = _appliance("Fan 1", "FAN", 1, did)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "ON", "start_time": "19:00",
        "schedule_type": "DAILY",
    }).json()
    d = _voice("move the fan schedule to 8 PM", did)
    assert d["intent"] == "UPDATE_SCHEDULE"
    assert "rescheduled" in d["response"]
    assert "8:00 PM" in d["response"]
    updated = client.get(f"/api/v1/schedules/{s['id']}").json()
    assert updated["start_time"] == "20:00"
    assert updated["action"] == "ON"
    assert updated["schedule_type"] == "DAILY"


def test_p2_update_disambiguation():
    did = _device("p2-upd2")
    a = _appliance("Fan 1", "FAN", 1, did)
    client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "ON", "start_time": "07:00", "schedule_type": "DAILY"})
    s2 = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "OFF", "start_time": "19:00", "schedule_type": "DAILY"}).json()
    d = _voice("move the fan schedule to 9 PM", did)
    assert "2 schedules" in d["response"]
    assert "Which one should I change" in d["response"]
    d = _voice("the second one", did)
    assert "rescheduled" in d["response"]
    updated = client.get(f"/api/v1/schedules/{s2['id']}").json()
    assert updated["start_time"] == "21:00"
    # Unselected schedule untouched.
    assert any(s["start_time"] == "07:00" for s in _schedules())


def test_p2_update_change_phrase():
    did = _device("p2-upd3")
    a = _appliance("Bulb 1", "BULB", 1, did)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "ON", "start_time": "10:00", "schedule_type": "DAILY"}).json()
    d = _voice("change bulb 1 to turn off at 11 PM", did)
    assert d["intent"] == "UPDATE_SCHEDULE"
    assert "rescheduled" in d["response"]
    updated = client.get(f"/api/v1/schedules/{s['id']}").json()
    assert updated["start_time"] == "23:00"


# ---------------------------------------------------------------------------
# Enable / disable (with disambiguation)
# ---------------------------------------------------------------------------
def test_p2_disable_enable():
    did = _device("p2-de")
    a = _appliance("Living Light", "LIGHT", 2, did)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "ON", "start_time": "07:30", "schedule_type": "DAILY"}).json()
    d = _voice("disable the light schedule", did)
    assert d["intent"] == "DISABLE_SCHEDULE"
    assert "Disabled" in d["response"]
    assert client.get(f"/api/v1/schedules/{s['id']}").json()["enabled"] is False
    d = _voice("enable the light schedule", did)
    assert d["intent"] == "ENABLE_SCHEDULE"
    assert "Enabled" in d["response"]
    assert client.get(f"/api/v1/schedules/{s['id']}").json()["enabled"] is True


def test_p2_disable_disambiguation():
    did = _device("p2-dd")
    a = _appliance("Hall Socket", "SOCKET", 3, did)
    s1 = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "ON", "start_time": "06:00", "schedule_type": "DAILY"}).json()
    client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "OFF", "start_time": "22:00", "schedule_type": "DAILY"})
    d = _voice("disable the socket schedule", did)
    assert "2 schedules" in d["response"]
    assert "Which one should I disable" in d["response"]
    d = _voice("the first one", did)
    assert "Disabled" in d["response"]
    assert client.get(f"/api/v1/schedules/{s1['id']}").json()["enabled"] is False


# ---------------------------------------------------------------------------
# Delete & list
# ---------------------------------------------------------------------------
def test_p2_delete_then_list():
    did = _device("p2-del")
    a = _appliance("TV 1", "TV", 3, did)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": a["id"], "action": "OFF", "start_time": "23:00", "schedule_type": "DAILY"}).json()
    d = _voice("remove the tv schedule", did)
    assert d["intent"] == "DELETE_SCHEDULE"
    assert "Removed" in d["response"]
    assert client.get(f"/api/v1/schedules/{s['id']}").status_code == 404
    d = _voice("what is scheduled", did)
    assert d["intent"] == "LIST_SCHEDULES"
    assert "You don't have any schedules yet" in d["response"]


# ---------------------------------------------------------------------------
# Safety: never claim execution; ESP32 stays authoritative
# ---------------------------------------------------------------------------
def test_p2_safety_high_voltage_no_execution_claim():
    did = _device("p2-safe")
    _appliance("Pump 2", "PUMP", 2, did)
    _post_reading(did, 260.0)
    d = _voice("turn on the pump 2", did)
    assert d["intent"] == "MANUAL_APPLIANCE_ON"
    resp = d["response"]
    assert "Command sent to the ESP32" in resp
    assert "Waiting for confirmation" in resp
    assert "safety limit" in resp
    assert "confirmed" not in resp.lower()


# ---------------------------------------------------------------------------
# Device scoping
# ---------------------------------------------------------------------------
def test_p2_device_scoping():
    d1, d2 = _device("p2-d1"), _device("p2-d2")
    a1 = _appliance("Bulb", "BULB", 1, d1)
    a2 = _appliance("Bulb", "BULB", 1, d2)
    d = _voice("turn on the bulb at 6 PM", d2)
    assert "Scheduled" in d["response"]
    rows = [s for s in _schedules() if s["appliance_id"] in (a1["id"], a2["id"])]
    assert rows
    assert rows[0]["on_time"] == "18:00"
    assert rows[0]["appliance_id"] == a2["id"]
    # The other device's bulb must not be scheduled.
    assert not [s for s in rows if s["appliance_id"] == a1["id"]]