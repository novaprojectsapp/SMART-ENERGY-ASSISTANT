import sys
import os

# Isolated test DB must be active BEFORE importing app modules.
os.environ["APP_TESTING"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    """Reset the test DB once for this module so voice/appliance resolution tests
    run against a controlled, empty appliance set (no cross-test contamination
    from test_api.py, which shares the same isolated test_smart_energy.db)."""
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


def test_voice_create_schedule_confirms():
    did = _device("vsched-dev")
    _appliance("Pump 1", "PUMP", 1, did)
    d = _voice("turn on pump 1 at 6 PM and turn it off at 11 PM every day", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"]
    assert "at 18:00" in d["response"]
    assert "at 23:00" in d["response"]
    # Schedule persisted as an ON/OFF pair (start_time=on, end_time=off)
    scheds = client.get("/api/v1/schedules").json()
    assert any(s["appliance_id"] for s in scheds)
    pair = [s for s in scheds if s["appliance_id"]][0]
    assert pair["on_time"] == "18:00"
    assert pair["off_time"] == "23:00"


def test_voice_create_pair_from_to():
    did = _device("vpair-dev")
    _appliance("Bulb 1", "BULB", 1, did)
    d = _voice("schedule bulb 1 from 7 PM to 10 PM Monday and Friday", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"]
    assert "at 19:00" in d["response"]
    assert "at 22:00" in d["response"]
    scheds = client.get("/api/v1/schedules").json()
    pair = [s for s in scheds if s["on_time"] == "19:00" and s["off_time"] == "22:00"]
    assert pair
    assert pair[0]["schedule_type"] == "WEEKLY"


def test_voice_clarify_missing_off_time():
    did = _device("vclarif-off-dev")
    _appliance("Fan 1", "FAN", 1, did)
    d = _voice("turn on fan 1 at 6 PM", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "What time should I turn it off" in d["response"]
    # No incomplete schedule created for the requested ON time.
    scheds = client.get("/api/v1/schedules").json()
    assert not any(s["on_time"] == "18:00" and s["off_time"] is None for s in scheds)


def test_voice_clarify_missing_on_time():
    did = _device("vclarif-on-dev")
    _appliance("Fan 2", "FAN", 2, did)
    d = _voice("turn off fan 2 at 11 PM", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "What time should I turn it on" in d["response"]
    # No incomplete schedule created for the requested OFF time.
    scheds = client.get("/api/v1/schedules").json()
    assert not any(s["off_time"] == "23:00" and s["on_time"] is None for s in scheds)


def test_voice_manual_on_honest_simulated():
    did = _device("vfan-dev")
    _appliance("Fan 3", "FAN", 3, did)
    d = _voice("turn on fan 3", did)
    assert d["intent"] == "MANUAL_APPLIANCE_ON"
    assert "Hardware control is not connected yet" in d["response"]
    # Control command recorded as SIMULATED
    cmds = client.get("/api/v1/control-commands").json()
    assert any(c["source"] == "VOICE" and c["status"] == "SIMULATED" for c in cmds)


def test_voice_list_schedules_and_appliances():
    did = _device("vlist-dev")
    _voice("show my schedules", did)
    _voice("list my appliances", did)


def test_voice_disable_schedule():
    did = _device("vdis-dev")
    a = _appliance("Living Light", "LIGHT", 2, did)
    client.post("/api/v1/schedules", json={"appliance_id": a["id"], "action": "ON", "start_time": "07:30", "schedule_type": "DAILY"})
    d = _voice("disable the light schedule", did)
    assert d["intent"] == "DISABLE_SCHEDULE"
    assert "Disabled" in d["response"] or "disabled" in d["response"]


def test_voice_clarification_ambiguous_appliance():
    did = _device("vamb-dev")
    _appliance("Bulb A", "BULB", 1, did)
    _appliance("Bulb B", "BULB", 2, did)
    d = _voice("schedule the bulb", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Which appliance do you mean" in d["response"]


def test_voice_clarification_missing_time():
    did = _device("vtime-dev")
    _appliance("Hall Socket", "SOCKET", 3, did)
    d = _voice("schedule the socket", did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "What time" in d["response"]


def test_voice_delete_schedule():
    did = _device("vdel-dev")
    a = _appliance("TV 1", "TV", 3, did)
    s = client.post("/api/v1/schedules", json={"appliance_id": a["id"], "action": "OFF", "start_time": "23:00", "schedule_type": "DAILY"}).json()
    d = _voice("remove the tv schedule", did)
    assert d["intent"] == "DELETE_SCHEDULE"
    assert "Removed" in d["response"]
    assert client.get(f"/api/v1/schedules/{s['id']}").status_code == 404
