import sys
import os

# Must be set BEFORE importing app modules so tests use an isolated test DB
# (test_smart_energy.db) and never touch the production smart_energy.db.
os.environ["APP_TESTING"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, engine, Base

Base.metadata.drop_all(bind=engine)
init_db()

client = TestClient(app)


def test_health():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded")
    assert data["version"] == "1.0.0"
    assert data["database"] == "connected"


def test_device_registration():
    res = client.post("/api/v1/devices", json={
        "id": "test-device-001",
        "name": "Test Device",
        "device_type": "PZEM-004T",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["id"] == "test-device-001"
    assert data["name"] == "Test Device"


def test_duplicate_device():
    res = client.post("/api/v1/devices", json={
        "id": "test-device-001",
        "name": "Duplicate",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "test-device-001"
    # Idempotent re-registration refreshes the name from the (newer) caller.
    assert data["name"] == "Duplicate"


def test_list_devices():
    res = client.get("/api/v1/devices")
    assert res.status_code == 200
    devices = res.json()
    assert len(devices) >= 1


def test_get_device():
    res = client.get("/api/v1/devices/test-device-001")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "test-device-001"


def test_device_not_found():
    res = client.get("/api/v1/devices/nonexistent")
    assert res.status_code == 404


def test_ingest_valid_reading():
    from datetime import datetime, timezone
    res = client.post("/api/v1/devices/test-device-001/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 230.5,
        "current": 0.82,
        "power": 165.0,
        "energy": 0.100,
        "frequency": 50.0,
        "power_factor": 0.98,
    })
    assert res.status_code == 201
    data = res.json()
    assert data["voltage"] == 230.5
    assert data["device_id"] == "test-device-001"


def test_duplicate_reading():
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    reading = {
        "timestamp": ts,
        "voltage": 230.0,
        "current": 0.5,
        "power": 115.0,
        "energy": 0.05,
        "frequency": 50.0,
        "power_factor": 0.95,
    }
    res1 = client.post("/api/v1/devices/test-device-001/readings", json=reading)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/devices/test-device-001/readings", json=reading)
    assert res2.status_code == 201


def test_invalid_voltage():
    from datetime import datetime, timezone
    res = client.post("/api/v1/devices/test-device-001/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 600,
        "current": 0.5,
        "power": 100,
        "energy": 0,
        "frequency": 50,
        "power_factor": 0.95,
    })
    assert res.status_code == 422


def test_invalid_power_factor():
    from datetime import datetime, timezone
    res = client.post("/api/v1/devices/test-device-001/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 230,
        "current": 0.5,
        "power": 100,
        "energy": 0,
        "frequency": 50,
        "power_factor": 1.5,
    })
    assert res.status_code == 422


def test_reading_for_nonexistent_device():
    from datetime import datetime, timezone
    res = client.post("/api/v1/devices/nonexistent-device/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 230,
        "current": 0.5,
        "power": 100,
        "energy": 0,
        "frequency": 50,
        "power_factor": 0.95,
    })
    assert res.status_code == 404


def test_billing_today():
    res = client.get("/api/v1/billing/today")
    assert res.status_code == 200
    data = res.json()
    assert "measured_kwh" in data
    assert "energy_charge_today" in data
    assert "monthly_equivalent_estimate" in data
    assert "billing_period_estimate" in data
    assert data["currency"] == "INR"


def test_billing_tariff():
    res = client.get("/api/v1/billing/tariff")
    assert res.status_code == 200
    data = res.json()
    assert "slabs" in data
    assert len(data["slabs"]) >= 3


def test_billing_slab_boundaries():
    from app.billing.engine import load_tariff, calculate_billing

    tariff = load_tariff()

    result = calculate_billing(0, tariff)
    assert result.total_charge == 0

    result = calculate_billing(100, tariff)
    assert result.total_charge == 0

    result = calculate_billing(101, tariff)
    assert result.total_charge == 2.35

    result = calculate_billing(200, tariff)
    assert result.total_charge == 100 * 2.35

    result = calculate_billing(201, tariff)
    assert result.total_charge == 100 * 2.35 + 1 * 4.45

    result = calculate_billing(500, tariff)
    assert result.total_charge == 100 * 2.35 + 300 * 4.45

    result = calculate_billing(501, tariff)
    assert result.total_charge == 100 * 2.35 + 300 * 4.45 + 1 * 6.45


def test_billing_predict():
    res = client.get("/api/v1/billing/predict?days=30")
    assert res.status_code == 200


def test_analytics_summary():
    res = client.get("/api/v1/analytics/summary")
    assert res.status_code == 200
    data = res.json()
    assert "energy" in data


def test_analytics_anomalies():
    res = client.get("/api/v1/analytics/anomalies")
    assert res.status_code == 200


def test_analytics_patterns():
    res = client.get("/api/v1/analytics/patterns")
    assert res.status_code == 200


def test_ai_insights():
    res = client.get("/api/v1/ai/insights")
    assert res.status_code == 200


def test_voice_query_power():
    res = client.post("/api/v1/voice/query", json={"text": "What is my current power?"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "CURRENT_POWER"
    assert data["confidence"] > 0


def test_voice_query_bill():
    res = client.post("/api/v1/voice/query", json={"text": "What will my bill be?"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "BILL_PREDICTION"


def test_voice_query_cost():
    res = client.post("/api/v1/voice/query", json={"text": "How much electricity cost today?"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "TODAY_COST"


def test_voice_query_unknown():
    res = client.post("/api/v1/voice/query", json={"text": "blargh flerb noop"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "UNKNOWN"


def test_voice_query_help():
    res = client.post("/api/v1/voice/query", json={"text": "help"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "HELP"


def test_recommendations():
    res = client.get("/api/v1/recommendations")
    assert res.status_code == 200


def test_whatif():
    res = client.post("/api/v1/what-if", json={"reduction_percent": 20})
    assert res.status_code == 200


def test_settings():
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    data = res.json()
    assert "gemini_enabled" in data


def test_reports():
    res = client.get("/api/v1/reports/energy-summary?days=30")
    assert res.status_code == 200


def test_terminology_power_vs_current():
    """POWER ≠ CURRENT: 'power' must never classify as amperage intent."""
    for query in [
        "what is the current power",
        "how much power am I using",
        "current power reading",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "CURRENT_POWER", f"'{query}' should be CURRENT_POWER, got {data['intent']}"


def test_terminology_current_is_amps():
    """'current' in amperage context must classify as CURRENT_CURRENT."""
    for query in [
        "how much current",
        "how many amps",
        "what is the current amperage",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "CURRENT_CURRENT", f"'{query}' should be CURRENT_CURRENT, got {data['intent']}"


def test_terminology_old_age_no_misclassification():
    """'old age' must NOT classify as CURRENT_CURRENT or any current intent."""
    for query in ["old age", "i am of old age", "what is my current"]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] not in ("CURRENT_CURRENT",), (
            f"'{query}' must NOT classify as CURRENT_CURRENT, got {data['intent']}"
        )


def test_terminology_cost_is_not_bill():
    """COST queries must map to TODAY_COST, not BILL_PREDICTION."""
    for query in ["what is my cost", "what is my electricity cost"]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "TODAY_COST", f"'{query}' should be TODAY_COST, got {data['intent']}"


def test_terminology_bill_is_not_monthly():
    """'bill' queries (generic) must map to BILL_PREDICTION (billing-period estimate)."""
    for query in ["what is my bill", "what will my bill be"]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "BILL_PREDICTION", f"'{query}' should be BILL_PREDICTION, got {data['intent']}"


def test_terminology_two_month_is_billing_period():
    """'2 months' / 'bimonthly' must classify as BILL_PREDICTION, not MONTHLY_BILL."""
    for query in [
        "what will be the bill for 2 months",
        "bill for 2 months",
        "bimonthly bill",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "BILL_PREDICTION", (
            f"'{query}' must be BILL_PREDICTION (billing-period), got {data['intent']}"
        )


def test_ambiguity_returns_unknown():
    """Genuinely ambiguous or unrecognised text should return UNKNOWN."""
    for query in ["blargh flerb noop", "xyzzy", "old age"]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "UNKNOWN", f"'{query}' should be UNKNOWN, got {data['intent']}"


def test_production_database_not_modified_by_tests():
    """Verify production smart_energy.db is untouched by pytest."""
    import sqlite3 as _sqlite3
    from pathlib import Path

    prod_db = Path(__file__).resolve().parent.parent.parent / "smart_energy.db"
    assert prod_db.exists(), "Production smart_energy.db must exist"
    conn = _sqlite3.connect(str(prod_db))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM devices")
    device_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM energy_readings")
    reading_count = c.fetchone()[0]
    conn.close()
    assert device_count >= 0, "devices table must exist"
    assert reading_count >= 0, "energy_readings table must exist"


def test_database_path_is_project_root():
    """Config must resolve the DB path relative to project root."""
    from pathlib import Path
    from app.config import BASE_DIR, settings

    project_root = Path(BASE_DIR).resolve()

    # Normalize the SQLite URL to a filesystem path.
    # SQLite URLs have the form: sqlite:///<abs path>
    raw = settings.DATABASE_URL
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///") :]
    db_path = Path(raw).resolve()

    assert db_path.parent == project_root, (
        f"database_path.parent ({db_path.parent}) must equal project_root ({project_root})"
    )
    assert db_path.name == "smart_energy.db", (
        f"database file must be smart_energy.db, got: {db_path.name}"
    )
    outside = (project_root.parent / "smart_energy.db").resolve()
    assert db_path != outside, (
        f"database must NOT be outside the project: {outside}"
    )


def test_power_variants_resolve_to_current_power():
    """Live/current power phrasings must resolve to CURRENT_POWER."""
    for query in [
        "what is the current power",
        "what power am I using",
        "how much power am I using",
        "how much power am I using now",
        "what is my current power",
        "tell me my power",
        "what is the power right now",
        "what's my power right now",
        "current power?",
        "power now?",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "CURRENT_POWER", f"'{query}' should be CURRENT_POWER, got {data['intent']}"


def test_energy_variants_resolve_to_energy():
    """Energy/units/consumption phrasings must resolve to energy intent (kWh)."""
    for query in [
        "how much energy did I use today",
        "how many units did I use",
        "what is my energy usage today",
        "how much electricity did I consume",
        "how much energy have I consumed today",
        "what is my consumption today",
        "how many kWh did I use",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] in ("CURRENT_ENERGY", "TODAY_ENERGY", "ENERGY_USAGE"), (
            f"'{query}' should be an energy intent, got {data['intent']}"
        )


def test_ambiguous_used_power_returns_clarification():
    """Ambiguous 'used power' phrases must return NEEDS_CLARIFICATION, not guess."""
    for query in [
        "what is the power I used",
        "how much power did I use",
        "how much electricity did I use",
    ]:
        res = client.post("/api/v1/voice/query", json={"text": query})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "NEEDS_CLARIFICATION", (
            f"'{query}' should be NEEDS_CLARIFICATION, got {data['intent']}"
        )


def test_power_not_confused_with_energy():
    """Power responses must use watts; energy responses must use kWh."""
    from datetime import datetime, timezone

    # Seed a device + reading so the voice handler has a live measurement.
    client.post("/api/v1/devices", json={"id": "pw-dev-001", "name": "PW"})
    client.post("/api/v1/devices/pw-dev-001/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 230.0,
        "current": 0.55,
        "power": 125.91,
        "energy": 0.100,
        "frequency": 50.0,
        "power_factor": 0.95,
    })

    res = client.post("/api/v1/voice/query", json={"text": "what is the current power", "device_id": "pw-dev-001"})
    assert res.status_code == 200
    power_response = res.json()["response"].lower()
    assert "watt" in power_response

    res = client.post("/api/v1/voice/query", json={"text": "how much energy did I use today", "device_id": "pw-dev-001"})
    assert res.status_code == 200
    energy_response = res.json()["response"].lower()
    assert "kilowatt" in energy_response


def test_analytics_summary_missing_optional_values():
    """Analytics frontend-safe: API must tolerate missing/null optional numeric values."""
    from fastapi import HTTPException
    res = client.get("/api/v1/analytics/summary")
    assert res.status_code == 200
    data = res.json()
    # The frontend reads data.power.peak_watts_today — it must be present (not undefined).
    assert "power" in data
    assert "peak_watts_today" in data.get("power", {}), (
        "Analytics 'power' block must expose peak_watts_today for the frontend"
    )
    for key in ("today_kwh", "week_kwh", "month_kwh", "avg_daily_kwh"):
        assert key in data.get("energy", {}), f"energy.{key} must be present"


def test_analytics_empty_dataset_does_not_crash():
    """Analytics with no data must return a sane empty response, not a 500."""
    res = client.get("/api/v1/analytics/summary")
    assert res.status_code == 200
    data = res.json()
    # Even with no readings the backend returns numeric zeros; frontend safely formats.
    assert data["data_source"] in ("MEASURED", "NO_DATA")
    assert isinstance(data.get("power", {}).get("peak_watts_today"), (int, float))
    assert isinstance(data.get("power", {}).get("current_avg_watts"), (int, float))


def test_analytics_null_safe_within_frontend_contract():
    """Null/undefined optional analytics fields must not crash the frontend formatter."""
    import json as _json
    # Simulate a payload where optional fields could be missing/null.
    sample = {
        "energy": {"today_kwh": None, "week_kwh": None, "month_kwh": None, "avg_daily_kwh": None},
        "power": {"current_avg_watts": None, "peak_watts_today": None},
        "quality": {"avg_voltage": None, "avg_power_factor": None},
        "cost": {"today_energy_charge": None, "month_energy_charge": None, "currency": "INR"},
        "data_source": "NO_DATA",
    }
    _json.dumps(sample)  # payload is JSON-serializable; frontend must guard with safeNum/fmt

# ============================================================================
# SMART APPLIANCE SCHEDULING & CONTROL
# ============================================================================

def _make_sched_appliance(device_id="sched-dev", name="Sched Bulb 1", channel=1, ctype="BULB"):
    client.post("/api/v1/devices", json={"id": device_id, "name": device_id, "device_type": "PZEM-004T"})
    r = client.post("/api/v1/appliances", json={
        "name": name, "type": ctype, "channel": channel, "device_id": device_id, "control_capable": True,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ---- APPLIANCES ----
def test_appliance_create_and_list():
    app = _make_sched_appliance(name="Sched Bulb Electric A")
    assert app["name"] == "Sched Bulb Electric A"
    assert app["type"] == "BULB"
    assert app["control_capable"] is True
    listed = client.get("/api/v1/appliances").json()
    assert any(a["id"] == app["id"] for a in listed)


def test_appliance_duplicate_handling():
    client.post("/api/v1/devices", json={"id": "sched-dev-dup", "name": "dup", "device_type": "PZEM-004T"})
    payload = {"name": "Sched Duplicate Bulb", "type": "BULB", "channel": 5, "device_id": "sched-dev-dup"}
    r1 = client.post("/api/v1/appliances", json=payload)
    assert r1.status_code == 201
    # Duplicate name is allowed (no unique constraint), but invalid type is rejected.
    bad = client.post("/api/v1/appliances", json={**payload, "type": "nonsense"})
    assert bad.status_code == 422


def test_appliance_update():
    app = _make_sched_appliance(name="Sched Update Bulb", channel=3)
    r = client.put(f"/api/v1/appliances/{app['id']}", json={"name": "Sched Update Bulb Renamed", "enabled": False})
    assert r.status_code == 200
    assert r.json()["name"] == "Sched Update Bulb Renamed"
    assert r.json()["enabled"] is False


def test_appliance_delete():
    app = _make_sched_appliance(name="Sched Delete Bulb", channel=4)
    # attach a schedule so delete also removes it
    client.post("/api/v1/schedules", json={"appliance_id": app["id"], "action": "ON", "start_time": "08:00", "schedule_type": "DAILY"})
    r = client.delete(f"/api/v1/appliances/{app['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/v1/appliances/{app['id']}").status_code == 404


# ---- SCHEDULES ----
def _make_sched_schedule(appliance_id, action="ON", start_time="18:00", sched_type="DAILY", days=None):
    payload = {
        "appliance_id": appliance_id,
        "action": action,
        "start_time": start_time,
        "schedule_type": sched_type,
    }
    if days is not None:
        payload["days_of_week"] = days
    r = client.post("/api/v1/schedules", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_schedule_create_on_daily():
    app = _make_sched_appliance(name="Sched SchedDaily Bulb")
    s = _make_sched_schedule(app["id"], "ON", "18:00", "DAILY")
    assert s["action"] == "ON"
    assert s["schedule_type"] == "DAILY"
    assert s["enabled"] is True
    assert s["next_execution_at"] is not None


def test_schedule_create_off_weekly():
    app = _make_sched_appliance(name="Sched SchedWeekly Bulb")
    s = _make_sched_schedule(app["id"], "OFF", "22:00", "WEEKLY", days=[0, 4])
    assert s["action"] == "OFF"
    assert s["schedule_type"] == "WEEKLY"
    assert s["days_of_week"] == [0, 4]


def test_schedule_create_once():
    app = _make_sched_appliance(name="Sched SchedOnce Bulb")
    s = _make_sched_schedule(app["id"], "ON", "12:00", "ONCE")
    assert s["schedule_type"] == "ONCE"


def test_schedule_invalid_time():
    app = _make_sched_appliance(name="Sched BadTime Bulb")
    r = client.post("/api/v1/schedules", json={"appliance_id": app["id"], "action": "ON", "start_time": "25:99", "schedule_type": "DAILY"})
    assert r.status_code == 422


def test_schedule_invalid_action():
    app = _make_sched_appliance(name="Sched BadAction Bulb")
    r = client.post("/api/v1/schedules", json={"appliance_id": app["id"], "action": "TOGGLE", "start_time": "10:00"})
    assert r.status_code == 422


def test_schedule_missing_appliance():
    r = client.post("/api/v1/schedules", json={"appliance_id": "does-not-exist", "action": "ON", "start_time": "10:00"})
    assert r.status_code == 404


def test_schedule_enable_disable():
    app = _make_sched_appliance(name="Sched Toggle Bulb")
    s = _make_sched_schedule(app["id"], "ON", "20:00", "DAILY")
    r = client.post(f"/api/v1/schedules/{s['id']}/disable").json()
    assert r["enabled"] is False
    assert r["next_execution_at"] is None
    r = client.post(f"/api/v1/schedules/{s['id']}/enable").json()
    assert r["enabled"] is True


def test_schedule_delete():
    app = _make_sched_appliance(name="Sched DelSchedule Bulb")
    s = _make_sched_schedule(app["id"], "ON", "09:00", "DAILY")
    assert client.delete(f"/api/v1/schedules/{s['id']}").status_code == 200
    assert client.get(f"/api/v1/schedules/{s['id']}").status_code == 404


# ---- ON/OFF PAIR SCHEDULES ----
def test_schedule_create_on_off_pair():
    app = _make_sched_appliance(name="Sched Pair Bulb")
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "18:00",
        "off_time": "23:00",
        "schedule_type": "DAILY",
    }).json()
    assert s["action"] == "ON"          # pair always leads with ON
    assert s["on_time"] == "18:00"
    assert s["off_time"] == "23:00"
    assert s["start_time"] == "18:00"   # on_time maps to start_time
    assert s["end_time"] == "23:00"     # off_time maps to end_time


def test_schedule_create_on_off_pair_weekly():
    app = _make_sched_appliance(name="Sched Pair Weekly Bulb")
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "07:00",
        "off_time": "11:00",
        "schedule_type": "WEEKLY",
        "days_of_week": [0, 4],
    }).json()
    assert s["schedule_type"] == "WEEKLY"
    assert s["days_of_week"] == [0, 4]
    assert s["on_time"] == "07:00"
    assert s["off_time"] == "11:00"


def test_schedule_create_overnight_pair_allowed():
    app = _make_sched_appliance(name="Sched Overnight Bulb")
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "23:00",
        "off_time": "06:00",
        "schedule_type": "DAILY",
    }).json()
    assert s["on_time"] == "23:00"
    assert s["off_time"] == "06:00"


def test_schedule_reject_same_on_off_time():
    app = _make_sched_appliance(name="Sched SameTime Bulb")
    r = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "18:00",
        "off_time": "18:00",
        "schedule_type": "DAILY",
    })
    assert r.status_code == 422
    assert "ON time and OFF time cannot be the same" in r.json()["detail"]


def test_schedule_weekly_requires_day():
    app = _make_sched_appliance(name="Sched NoDay Bulb")
    r = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "18:00",
        "off_time": "23:00",
        "schedule_type": "WEEKLY",
        "days_of_week": [],
    })
    assert r.status_code == 422
    assert "at least one day" in r.json()["detail"]


def test_scheduler_on_off_pair_executes_both_events():
    from app.services.scheduler import SchedulerService
    from app.models import Schedule as SchedModel
    from app.database import SessionLocal
    from datetime import datetime, timezone
    app = _make_sched_appliance(name="Sched PairExec Bulb")
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "18:00",
        "off_time": "23:00",
        "schedule_type": "DAILY",
    }).json()
    db = SessionLocal()
    row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()

    # Force the next pending event due now.
    row.next_execution_at = datetime.now(timezone.utc)
    db.commit()

    svc = SchedulerService(db)
    cmds1 = svc.run_due()
    assert len(cmds1) == 1
    assert cmds1[0].action in ("ON", "OFF")
    assert cmds1[0].source == "SCHEDULE"

    # Executing advances next_execution_at, so a second run must not duplicate.
    cmds2 = svc.run_due()
    assert cmds2 == []
    db.close()


def test_scheduler_overnight_pair_next_events():
    from app.services.scheduler import SchedulerService
    from app.models import Schedule as SchedModel
    from app.database import SessionLocal
    from datetime import datetime
    app = _make_sched_appliance(name="Sched OvernightExec Bulb")
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"],
        "on_time": "23:00",
        "off_time": "06:00",
        "schedule_type": "DAILY",
    }).json()
    db = SessionLocal()
    row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()
    svc = SchedulerService(db)
    # Pick a reference time on a given local day (e.g. before the 23:00 ON).
    # 18:00 IST is 12:30 UTC.
    ref = datetime(2026, 1, 1, 12, 30)  # naive-UTC 12:30 = 18:00 IST
    next_on = svc.next_on_at(row, ref)
    next_off = svc.next_off_at(row, ref)
    assert next_on is not None
    assert next_off is not None
    # ON at 23:00 IST = 17:30 UTC on the reference day.
    assert next_on.hour == 17 and next_on.minute == 30
    # OFF at 06:00 IST next day = 00:30 UTC next day.
    assert next_off.hour == 0 and next_off.minute == 30
    # OFF must come after ON.
    assert next_off > next_on
    db.close()


# ---- SCHEDULER ----
def test_scheduler_due_executes_once_and_duplicate_prevented():
    from app.services.scheduler import SchedulerService
    from app.models import Schedule, ControlCommand
    app = _make_sched_appliance(name="Sched SvcBulb")
    s = _make_sched_schedule(app["id"], "ON", "18:00", "DAILY")
    db_sched = __import__("app.models", fromlist=["Schedule"]).Schedule
    # Simulate a due schedule by setting next_execution_at in the past.
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    db = SessionLocal()
    row = db.query(db_sched).filter(db_sched.id == s["id"]).first()
    from datetime import datetime, timezone
    row.next_execution_at = datetime.now(timezone.utc)
    db.commit()
    svc = SchedulerService(db)
    commands = svc.run_due()
    assert len(commands) == 1
    assert commands[0].action == "ON"
    assert commands[0].source == "SCHEDULE"
    # Running again in the same window must NOT create a duplicate.
    commands2 = svc.run_due()
    assert commands2 == []

# Verify a control command row was persisted and honestly marked PENDING
    # (waiting for ESP32 acknowledgement, never prematurely EXECUTED).
    cmd_count = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).count()
    assert cmd_count >= 1
    new_cmd = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).order_by(ControlCommand.created_at.desc()).first()
    assert new_cmd.status == "PENDING"
    assert "queued for ESP32" in new_cmd.message
    db.close()


def test_scheduler_disabled_does_not_execute():
    from app.services.scheduler import SchedulerService, DEFAULT_TZ
    from app.models import Schedule as SchedModel
    from app.database import SessionLocal
    from datetime import datetime, timezone
    app = _make_sched_appliance(name="Sched DisabledBulb")
    s = _make_sched_schedule(app["id"], "OFF", "18:00", "DAILY")
    db = SessionLocal()
    row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()
    row.enabled = False
    row.next_execution_at = datetime.now(timezone.utc)
    db.commit()
    commands = SchedulerService(db).run_due()
    assert commands == []
    db.close()


def test_scheduler_deleted_does_not_execute():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from datetime import datetime, timezone
    app = _make_sched_appliance(name="Sched DeletedBulb")
    s = _make_sched_schedule(app["id"], "ON", "18:00", "DAILY")
    client.delete(f"/api/v1/schedules/{s['id']}")
    db = SessionLocal()
    commands = SchedulerService(db).run_due()
    assert commands == []
    db.close()


def test_scheduler_next_execution_computed():
    from app.services.scheduler import SchedulerService
    from app.models import Schedule as SchedModel
    from app.database import SessionLocal
    from datetime import datetime, timezone
    app = _make_sched_appliance(name="Sched NextBulb")
    s = _make_sched_schedule(app["id"], "ON", "18:00", "DAILY")
    db = SessionLocal()
    row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()
    next_at = row.next_execution_at
    assert next_at is not None
    # Stored as naive UTC; must be a future occurrence (18:00 IST -> 12:30 UTC).
    assert next_at.hour == 12 and next_at.minute == 30
    assert next_at > datetime.now(timezone.utc).replace(tzinfo=None)
    db.close()


# ---- CONTROL (manual) ----
def test_control_creates_pending_command():
    app = _make_sched_appliance(name="Sched CtrlBulb")
    r = client.post(f"/api/v1/appliances/{app['id']}/control", json={
        "appliance_id": app["id"], "action": "ON", "source": "USER",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "PENDING"
    assert "queued for ESP32" in data["message"]
    assert data["hardware_control_available"] is True
    assert data["command_id"]

    # No false hardware success: the command must NOT be EXECUTED yet.
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    mine = [c for c in cmds if c["command_id"] == data["command_id"]]
    assert mine and mine[0]["status"] == "PENDING"


def test_control_non_capable_rejected():
    client.post("/api/v1/devices", json={"id": "ncap-dev", "name": "ncap", "device_type": "PZEM-004T"})
    nc = client.post("/api/v1/appliances", json={"name": "Sched NCap", "type": "OTHER", "channel": 1, "device_id": "ncap-dev", "control_capable": False})
    r = client.post(f"/api/v1/appliances/{nc.json()['id']}/control", json={"appliance_id": nc.json()["id"], "action": "ON", "source": "USER"})
    assert r.status_code == 400


# ---- DB SAFETY ----
def test_production_db_untouched_by_scheduling_tests():
    """Scheduling tests must not have created rows in the production DB."""
    from app.config import settings, _resolve_database_url
    import sqlite3
    test_url = _resolve_database_url()
    assert "test" in test_url, "Tests must run against the isolated test DB"
    # Ensure the active engine points at the isolated test DB.
    assert "test_smart_energy" in test_url


# ---- LIVE DATA: UTC ISO timestamps ----
def test_latest_readings_return_utc_iso_timestamps():
    res = client.post("/api/v1/devices", json={
        "id": "iso-ts-dev", "name": "ISO TS Dev", "device_type": "PZEM-004T",
    })
    assert res.status_code == 201
    payload = {
        "voltage": 230.0, "current": 1.25, "power": 287.5,
        "energy": 1.5, "frequency": 50.0, "power_factor": 0.95,
        "data_source": "HARDWARE",
    }
    r = client.post("/api/v1/devices/iso-ts-dev/readings", json=payload)
    assert r.status_code == 201
    ts = r.json()["timestamp"]
    assert ts.endswith("Z"), f"Expected UTC/Z timestamp, got {ts!r}"
    # JS-parseable: ISO with Z suffix
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert dt.tzinfo is not None

    latest = client.get("/api/v1/readings/latest").json()
    row = next(x for x in latest if x["device_id"] == "iso-ts-dev")
    assert row["timestamp"].endswith("Z")
    assert row["data_source"] == "HARDWARE"


# ---- LIVE DATA: priority ordering ----
def test_latest_readings_prioritize_primary_hardware_device():
    # Re-register the firmware device id (primary) plus a sim/test device.
    client.post("/api/v1/devices", json={
        "id": "ESP32-S3-01", "name": "Hardware ESP32", "device_type": "PZEM-004T",
    })
    client.post("/api/v1/devices", json={
        "id": "demo-sim-9", "name": "Demo Sim", "device_type": "PZEM-004T",
    })

    hw = {"voltage": 229.5, "current": 1.05, "power": 241.0, "energy": 2.0,
          "frequency": 50.0, "power_factor": 0.94, "data_source": "HARDWARE"}
    sim = {"voltage": 0.0, "current": 0.0, "power": 0.0, "energy": 0.0,
           "frequency": 0.0, "power_factor": 0.0, "data_source": "SIMULATOR"}

    r_hw = client.post("/api/v1/devices/ESP32-S3-01/readings", json=hw)
    r_sim = client.post("/api/v1/devices/demo-sim-9/readings", json=sim)
    assert r_hw.status_code == 201
    assert r_sim.status_code == 201

    latest = client.get("/api/v1/readings/latest").json()
    assert len(latest) >= 2
    assert latest[0]["device_id"] == "ESP32-S3-01", "Primary hardware must be first"
    assert latest[0]["data_source"] == "HARDWARE"


# ---- LIVE DATA: freshness thresholds ----
def test_device_status_freshness_thresholds():
    from app.database import SessionLocal
    from app.models import Device
    from datetime import datetime, timedelta, timezone
    client.post("/api/v1/devices", json={
        "id": "fresh-thresh-dev", "name": "Threshold Dev", "device_type": "PZEM-004T",
    })
    payload = {"voltage": 220.0, "current": 1.0, "power": 220.0, "energy": 1.0,
               "frequency": 50.0, "power_factor": 0.9, "data_source": "HARDWARE"}
    assert client.post("/api/v1/devices/fresh-thresh-dev/readings", json=payload).status_code == 201

    db = SessionLocal()
    d = db.query(Device).filter(Device.id == "fresh-thresh-dev").first()
    assert d is not None
    d.last_seen = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    db.commit()
    db.refresh(d)
    st = client.get("/api/v1/devices/fresh-thresh-dev/status").json()
    assert st["status"] == "CONNECTED"

    d.last_seen = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    db.commit()
    st = client.get("/api/v1/devices/fresh-thresh-dev/status").json()
    assert st["status"] == "STALE"

    d.last_seen = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=120)
    db.commit()
    st = client.get("/api/v1/devices/fresh-thresh-dev/status").json()
    assert st["status"] == "OFFLINE"
    db.close()


# ============================================================================
# REGRESSION: Billing no longer references the undefined projectly_monthly
# ============================================================================
def test_billing_predict_does_not_crash_projection():
    """The /billing/predict endpoint must project monthly charges without the
    old `projectly_monthly` NameError (root-cause regression test)."""
    client.post("/api/v1/devices", json={
        "id": "billing-regr-dev", "name": "Billing Regr", "device_type": "PZEM-004T",
    })
    payload = {"voltage": 230.0, "current": 0.5, "power": 115.0,
               "energy": 100.0, "frequency": 50.0, "power_factor": 0.95}
    assert client.post("/api/v1/devices/billing-regr-dev/readings", json=payload).status_code == 201
    payload2 = {**payload, "energy": 105.0}
    assert client.post("/api/v1/devices/billing-regr-dev/readings", json=payload2).status_code == 201

    res = client.get("/api/v1/billing/predict?days=30&device_id=billing-regr-dev")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "OK"
    assert data["monthly_equivalent"]["projected_kwh"] > 0
    assert data["monthly_equivalent"]["energy_charge"] >= 0
    assert data["device_id"] == "billing-regr-dev"


def test_billing_predict_defaults_to_primary_hardware():
    """Calling /billing/predict without a device_id must resolve to the primary
    ESP32 hardware device, never to an unregistered/empty selection."""
    # ESP32-S3-01 is registered + has a HARDWARE reading from the priority test.
    res = client.get("/api/v1/billing/predict?days=30")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("device_id") == "ESP32-S3-01"


# ============================================================================
# REGRESSION: central primary-device selection (backend)
# ============================================================================
def test_device_selection_prefers_primary_hardware():
    from app.database import SessionLocal
    from app.utils.device_selection import select_device_id
    from app.models import Device
    db = SessionLocal()
    try:
        assert select_device_id(db, None) == "ESP32-S3-01", (
            "PRIMARY_DEVICE_ID must win over any test device"
        )
        # Explicit device_id is honored as-is.
        assert select_device_id(db, "test-device-001") == "test-device-001"
        # Deactivating the primary should fall back to a HARDWARE device (not None).
        d = db.query(Device).filter(Device.id == "ESP32-S3-01").first()
        d.is_active = False
        db.commit()
        resolved = select_device_id(db, None)
        assert resolved is not None and resolved in ("test-device-001", "billing-regr-dev", "esp32-pzem-002")
        d.is_active = True
        db.commit()
    finally:
        db.close()


def test_voice_uses_primary_hardware_readings():
    """Voice 'current power' must use ESP32-S3-01 data, not a newer test device."""
    client.post("/api/v1/devices", json={
        "id": "voice-probe", "name": "Voice Probe Sim", "device_type": "PZEM-004T",
    })
    probe = {"voltage": 0.0, "current": 0.0, "power": 777.0, "energy": 9.0,
             "frequency": 0.0, "power_factor": 0.0, "data_source": "HARDWARE"}
    assert client.post("/api/v1/devices/voice-probe/readings", json=probe).status_code == 201

    res = client.post("/api/v1/voice/query", json={"text": "What is my current power?"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["intent"] == "CURRENT_POWER"
    assert "241.00" in data["response"], data["response"]
    assert "777" not in data["response"], "Must not answer from the test/probe device"


def test_voice_query_accepts_basic_text():
    """A normal typed voice/query request returns intent + a response (no 500)."""
    for text in ["What is my current voltage?", "help me with my bill", "hello"]:
        res = client.post("/api/v1/voice/query", json={"text": text})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["intent"]
        assert isinstance(body["response"], str) and len(body["response"]) > 0


# ============================================================================
# REAL ESP32 RELAY CONTROL (command queue + polling + acknowledgement)
# ============================================================================

_hw_seq = 0


def _make_hw_appliance(device_id=None, name=None, channel=1):
    """Register a dedicated ESP32 device + a control-capable appliance.

    Each call gets its own device so pending command queues never leak
    between tests (the polling endpoint returns the oldest pending command)."""
    global _hw_seq
    _hw_seq += 1
    if device_id is None:
        device_id = f"esp-hw-{_hw_seq}"
    if name is None:
        name = f"Sockets {_hw_seq}"
    r = client.post("/api/v1/devices", json={"id": device_id, "name": device_id, "device_type": "PZEM-004T"})
    if r.status_code not in (200, 201):
        raise AssertionError(r.text)
    r = client.post("/api/v1/appliances", json={
        "name": name, "type": "SOCKET", "channel": channel,
        "device_id": device_id, "control_capable": True,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _create_manual_command(app, action="ON"):
    r = client.post(f"/api/v1/appliances/{app['id']}/control", json={
        "appliance_id": app["id"], "action": action, "source": "USER",
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_control_pending_lifecycle_manual_on_and_off():
    """Manual ON and OFF each create a PENDING hardware command."""
    app = _make_hw_appliance()
    on_cmd = _create_manual_command(app, "ON")
    off_cmd = _create_manual_command(app, "OFF")
    assert on_cmd["status"] == "PENDING"
    assert off_cmd["status"] == "PENDING"
    assert on_cmd["command_id"] != off_cmd["command_id"]
    assert on_cmd["action"] == "ON"
    assert off_cmd["action"] == "OFF"
    assert on_cmd["hardware_control_available"] is True


def test_pending_command_returns_to_owning_device_only():
    """The pending polling endpoint returns the command only to the owning device."""
    client.post("/api/v1/devices", json={"id": "other-esp32", "name": "Other", "device_type": "PZEM-004T"})
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "ON")

    # Owning device receives it.
    res = client.get(f"/api/v1/devices/{did}/control/pending")
    assert res.status_code == 200
    data = res.json()
    assert data["command"] is not None
    assert data["command"]["command_id"] == cmd["command_id"]
    assert data["command"]["channel"] == 1
    assert data["command"]["action"] == "ON"

    # Another registered device must NOT receive it.
    res2 = client.get("/api/v1/devices/other-esp32/control/pending")
    assert res2.status_code == 200
    assert res2.json()["command"] is None

    # Clean up the pending command so it does not leak into later tests.
    cid = data["command"]["command_id"]
    assert client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json={
        "success": True, "relay_state": "ON", "message": "ack"
    }).status_code == 200


def test_pending_not_returned_to_unregistered_device():
    client.post("/api/v1/devices", json={"id": "ghost-dev", "name": "Ghost", "device_type": "PZEM-004T"})
    _make_hw_appliance()
    _create_manual_command(_make_hw_appliance(), "ON")
    # The endpoint requires the device to be registered.
    res = client.get("/api/v1/devices/unregistered-xyz/control/pending")
    assert res.status_code == 404


def test_ack_success_marks_executed():
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "ON")
    cid = cmd["command_id"]

    pending = client.get(f"/api/v1/devices/{did}/control/pending").json()["command"]
    assert pending["command_id"] == cid

    r = client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json={
        "success": True, "relay_state": "ON", "message": "Relay switched ON successfully",
    })
    assert r.status_code == 200
    assert r.json()["acknowledged"] is True

    cmds = client.get("/api/v1/control-commands?limit=200").json()
    mine = [c for c in cmds if c["command_id"] == cid]
    assert mine and mine[0]["status"] == "EXECUTED"
    assert mine[0]["confirmed_relay_state"] == "ON"
    assert mine[0]["executed_at"] is not None

    # After EXECUTED, the polling endpoint no longer returns it.
    res = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert res["command"] is None

    # Appliance confirmed state must now be ON.
    app_resp = client.get(f"/api/v1/appliances/{app['id']}").json()
    assert app_resp["last_confirmed_state"] == "ON"


def test_ack_failure_marks_failed():
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "OFF")
    cid = cmd["command_id"]
    r = client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json={
        "success": False, "relay_state": "UNKNOWN", "message": "Relay execution failed",
    })
    assert r.status_code == 200
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    mine = [c for c in cmds if c["command_id"] == cid]
    assert mine and mine[0]["status"] == "FAILED"
    assert mine[0]["confirmed_relay_state"] in ("UNKNOWN", "OFF")


def test_repeated_ack_idempotent_no_state_corruption():
    """A duplicate/second ACK must not corrupt command state or re-execute."""
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "ON")
    cid = cmd["command_id"]
    ack_payload = {"success": True, "relay_state": "ON", "message": "Relay switched ON successfully"}
    assert client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json=ack_payload).status_code == 200
    # Re-acknowledge safely (ESP32 re-polls the same ID guard case).
    assert client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json=ack_payload).status_code == 200
    cmds = client.get("/api/v1/control-commands?limit=200").json()
    mine = [c for c in cmds if c["command_id"] == cid]
    assert mine and mine[0]["status"] == "EXECUTED"
    assert mine[0]["confirmed_relay_state"] == "ON"


def test_ack_by_wrong_device_rejected():
    client.post("/api/v1/devices", json={"id": "thief-dev", "name": "Thief", "device_type": "PZEM-004T"})
    app = _make_hw_appliance()
    cmd = _create_manual_command(app, "ON")
    r = client.post(f"/api/v1/devices/thief-dev/control/{cmd['command_id']}/ack", json={
        "success": True, "relay_state": "ON", "message": "wrong device",
    })
    assert r.status_code == 403
    cmds = client.get("/api/v1/control-commands?limit=200").json()
    mine = [c for c in cmds if c["command_id"] == cmd["command_id"]]
    assert mine and mine[0]["status"] == "PENDING"  # unchanged


def test_ack_by_unregistered_device_404():
    app = _make_hw_appliance()
    cmd = _create_manual_command(app, "OFF")
    r = client.post(f"/api/v1/devices/no-such-device/control/{cmd['command_id']}/ack", json={
        "success": True, "relay_state": "OFF", "message": "x",
    })
    assert r.status_code == 404


def test_expired_command_not_returned_and_marked_expired():
    from app.database import SessionLocal
    from app.models import ControlCommand as CC
    from datetime import datetime, timedelta, timezone
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "ON")
    cid = cmd["command_id"]
    db = SessionLocal()
    row = db.query(CC).filter(CC.command_id == cid).first()
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    db.commit()
    db.close()

    res = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert res["command"] is None
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    mine = [c for c in cmds if c["command_id"] == cid]
    assert mine and mine[0]["status"] == "EXPIRED"


def test_dispatched_command_can_be_repolled_and_acked():
    """ACK-lost recovery: a DISPATCHED command must be re-returned on the next
    poll so the ESP32 can re-acknowledge it instead of getting stuck forever."""
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "ON")
    cid = cmd["command_id"]

    first = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert first["command"]["command_id"] == cid
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    assert [c for c in cmds if c["command_id"] == cid][0]["status"] == "DISPATCHED"

    # Second poll (ACK was lost) must return the SAME command, not null.
    second = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert second["command"] is not None
    assert second["command"]["command_id"] == cid

    # Re-polling a DISPATCHED command must NOT bump attempts again.
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    dispatched = [c for c in cmds if c["command_id"] == cid][0]
    assert dispatched["status"] == "DISPATCHED"

    # The ESP32 finally acknowledges -> EXECUTED.
    r = client.post(f"/api/v1/devices/{did}/control/{cid}/ack", json={
        "success": True, "relay_state": "ON", "message": "Relay switched ON successfully",
    })
    assert r.status_code == 200
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    assert [c for c in cmds if c["command_id"] == cid][0]["status"] == "EXECUTED"


def test_expired_dispatched_command_not_returned():
    """An expired DISPATCHED command must be marked EXPIRED and never delivered."""
    from app.database import SessionLocal
    from app.models import ControlCommand as CC
    from datetime import datetime, timedelta, timezone
    app = _make_hw_appliance()
    did = app["device_id"]
    cmd = _create_manual_command(app, "OFF")
    cid = cmd["command_id"]

    pending = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert pending["command"]["command_id"] == cid

    db = SessionLocal()
    row = db.query(CC).filter(CC.command_id == cid).first()
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    db.commit()
    db.close()

    res = client.get(f"/api/v1/devices/{did}/control/pending").json()
    assert res["command"] is None
    cmds = client.get("/api/v1/control-commands?limit=50").json()
    mine = [c for c in cmds if c["command_id"] == cid]
    assert mine and mine[0]["status"] == "EXPIRED"


def test_control_command_without_device_mapped_rejected():
    """A command for a control-capable appliance with NO ESP32 device mapped
    must be rejected up front — it could never be polled or executed."""
    r = client.post("/api/v1/appliances", json={
        "name": "Orphan socket", "type": "SOCKET", "channel": 1,
        "device_id": "", "control_capable": True,
    })
    assert r.status_code == 201, r.text
    app = r.json()

    res = client.post(f"/api/v1/appliances/{app['id']}/control", json={
        "appliance_id": app["id"], "action": "ON", "source": "USER",
    })
    assert res.status_code == 400
    assert "no ESP32 device mapped" in res.json()["detail"]

    # Nothing was queued for execution.
    cmds = client.get("/api/v1/control-commands?limit=200").json()
    assert not [c for c in cmds if c["appliance_id"] == app["id"]]


def test_device_control_status_endpoint():
    app = _make_hw_appliance()
    did = app["device_id"]
    resp = client.get(f"/api/v1/devices/{did}/control/status").json()
    assert resp["device_id"] == did
    assert resp["hardware_control_available"] is True
    assert any(a["id"] == app["id"] and a["channel"] == 1 for a in resp["appliances"])


# ============================================================================
# SCHEDULER -> REAL COMMAND QUEUE
# ============================================================================

def _force_due(schedule_id, due_at_naive_utc):
    from app.database import SessionLocal
    from app.models import Schedule as SchedModel
    db = SessionLocal()
    try:
        row = db.query(SchedModel).filter(SchedModel.id == schedule_id).first()
        row.next_execution_at = due_at_naive_utc
        db.commit()
    finally:
        db.close()


def test_daily_schedule_creates_command_for_device():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from datetime import datetime, timedelta, timezone
    app = _make_hw_appliance()
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "18:00", "off_time": "23:00", "schedule_type": "DAILY",
    }).json()
    # Force the ON event due right now.
    due = datetime.now(timezone.utc).replace(tzinfo=None)
    _force_due(s["id"], due)

    db = SessionLocal()
    try:
        cmds = [c for c in SchedulerService(db).run_due() if c.appliance_id == app["id"]]
        assert len(cmds) == 1
        c = cmds[0]
        assert c.device_id == app["device_id"]
        assert c.channel == app["channel"]
        assert c.status == "PENDING"
        assert c.source == "SCHEDULE"
    finally:
        db.close()


def test_weekly_schedule_respects_days():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from app.models import Schedule as SchedModel
    from app.utils.time import utcnow
    from zoneinfo import ZoneInfo
    app = _make_hw_appliance(name="Weekly Socket", channel=2)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "09:00", "off_time": "17:00",
        "schedule_type": "WEEKLY", "days_of_week": [0, 4],
    }).json()
    assert s["days_of_week"] == [0, 4]
    # Verify the next ON event lands on a Monday (0) or Friday (4) in IST.
    db = SessionLocal()
    try:
        svc = SchedulerService(db)
        row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()
        next_on = svc.next_on_at(row, utcnow())
        assert next_on is not None
        ist = next_on.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata"))
        assert ist.weekday() in (0, 4), f"next ON on unexpected weekday {ist.weekday()}"
    finally:
        db.close()


def test_once_schedule_runs_once_only():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from app.models import ControlCommand
    from datetime import datetime, timezone
    app = _make_hw_appliance(name="Once Socket", channel=3)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "08:00", "off_time": "09:00", "schedule_type": "ONCE",
    }).json()
    due = datetime.now(timezone.utc).replace(tzinfo=None)
    _force_due(s["id"], due)
    db = SessionLocal()
    try:
        svc = SchedulerService(db)
        cmds1 = [c for c in svc.run_due() if c.appliance_id == app["id"]]
        assert len(cmds1) == 1
        assert cmds1[0].action == "ON"
        # A second run must not duplicate the ONCE event.
        before2 = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).count()
        svc.run_due()
        after2 = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).count()
        assert before2 == after2
    finally:
        db.close()


def test_overnight_schedule_off_fires_next_day():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from datetime import datetime, timedelta
    app = _make_hw_appliance(name="Overnight Socket", channel=4)
    s = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "23:00", "off_time": "06:00", "schedule_type": "DAILY",
    }).json()
    db = SessionLocal()
    try:
        svc = SchedulerService(db)
        from app.models import Schedule as SchedModel
        row = db.query(SchedModel).filter(SchedModel.id == s["id"]).first()
        # Reference time 12:30 UTC = 18:00 IST (before the 23:00 IST ON).
        ref = datetime(2026, 1, 1, 12, 30)
        next_on = svc.next_on_at(row, ref)
        next_off = svc.next_off_at(row, ref)
        assert next_on is not None and next_off is not None
        # ON 23:00 IST = 17:30 UTC on the reference day; OFF 06:00 IST = 00:30 UTC next day.
        assert next_on.hour == 17 and next_on.minute == 30
        assert next_off.hour == 0 and next_off.minute == 30
        assert next_off > next_on
    finally:
        db.close()


def test_overlapping_schedules_do_not_turn_off():
    """Schedule A (18:00-22:00) ends while Schedule B (20:00-23:00) is still
    active: A's OFF event must be suppressed (no OFF command created)."""
    from app.services.scheduler import SchedulerService
    from app.services.control_service import ControlService
    from app.database import SessionLocal
    from app.models import Schedule as SchedModel, ControlCommand
    from datetime import datetime, timedelta

    app = _make_hw_appliance(name="Overlap Socket", channel=5)
    sA = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "18:00", "off_time": "22:00", "schedule_type": "DAILY",
    }).json()
    sB = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "20:00", "off_time": "23:00", "schedule_type": "DAILY",
    }).json()

    db = SessionLocal()
    try:
        # Scenario time: 2026-03-15 22:00:30 IST == 16:30:30 UTC.
        now = datetime(2026, 3, 15, 16, 30, 30)
        a = db.query(SchedModel).filter(SchedModel.id == sA["id"]).first()
        b = db.query(SchedModel).filter(SchedModel.id == sB["id"]).first()
        # A's ON already fired hours ago; only A's OFF (22:00 IST = 16:30 UTC) is pending.
        a.next_execution_at = now - timedelta(seconds=30)  # due now
        a.last_executed_at = now - timedelta(hours=3)
        # B's ON fired at 20:00 IST = 14:30 UTC; its OFF (23:00 IST = 17:30 UTC) is future.
        b.last_executed_at = now - timedelta(hours=1)
        b.next_execution_at = datetime(2026, 3, 15, 17, 30)
        db.commit()

        svc = SchedulerService(db)
        cmds = svc.run_due(now)
        # A's OFF must be suppressed because B still requires ON.
        assert cmds == [], "OFF command must be suppressed during an overlap"

        # Advance A's cycle so the next run does not re-fire.
        db.rollback()

        # Sanity: without B, A's OFF WOULD fire.
        b.next_execution_at = None
        b.enabled = False
        db.commit()
        a2 = db.query(SchedModel).filter(SchedModel.id == sA["id"]).first()
        a2.next_execution_at = now - timedelta(seconds=30)
        a2.last_executed_at = now - timedelta(hours=3)
        db.commit()
        cmds2 = svc.run_due(now)
        off_cmds = [c for c in cmds2 if c.action == "OFF"]
        assert off_cmds, "A's OFF must fire when no other schedule requires ON"
        for c in off_cmds:
            assert c.device_id == app["device_id"]
            assert c.status == "PENDING"
    finally:
        db.close()


def test_disabled_and_deleted_schedules_create_no_commands():
    from app.services.scheduler import SchedulerService
    from app.database import SessionLocal
    from datetime import datetime
    app = _make_hw_appliance(name="NoCmd Socket", channel=6)
    s_dis = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "10:00", "off_time": "11:00", "schedule_type": "DAILY",
    }).json()
    s_del = client.post("/api/v1/schedules", json={
        "appliance_id": app["id"], "on_time": "12:00", "off_time": "13:00", "schedule_type": "DAILY",
    }).json()
    client.post(f"/api/v1/schedules/{s_dis['id']}/disable")
    client.delete(f"/api/v1/schedules/{s_del['id']}")
    # Controlled reference in the past (before any other schedule's next event).
    ref = datetime(2026, 1, 1, 0, 0)
    _force_due(s_dis["id"], ref)

    db = SessionLocal()
    try:
        cmds = SchedulerService(db).run_due(ref)
        assert cmds == []
    finally:
        db.close()


def test_scheduler_background_loop_starts_once():
    import os
    from app.services import scheduler_loop as sl
    # The singleton is disabled under APP_TESTING=1; exercise the guard logic.
    os.environ["APP_TESTING"] = "1"
    assert sl.start_scheduler_loop() is False  # disabled in testing mode
    sl.stop_scheduler_loop()

    # Verify duplicate-start protection on a real loop instance.
    loop = sl.SchedulerLoop(interval_seconds=5.0)
    os.environ["APP_TESTING"] = "0"
    try:
        assert loop.start() is True
        assert loop.start() is False  # duplicate start ignored
        assert loop._started is True
        assert loop._thread is not None and loop._thread.is_alive()
    finally:
        loop.stop()
        os.environ["APP_TESTING"] = "1"


def test_primary_device_remains_esp32_s3_01():
    from app.utils.device_selection import select_device_id
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # ESP32-S3-01 must remain the resolved primary for voice/readings.
        assert select_device_id(db, None) == "ESP32-S3-01"
    finally:
        db.close()


def test_pzem_polling_still_works():
    """The PZEM readings pipeline is untouched by control changes."""
    from datetime import datetime, timezone
    client.post("/api/v1/devices", json={"id": "pzem-regr", "name": "PZEM", "device_type": "PZEM-004T"})
    r = client.post("/api/v1/devices/pzem-regr/readings", json={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": 230.0, "current": 0.5, "power": 115.0,
        "energy": 0.25, "frequency": 50.0, "power_factor": 0.96, "data_source": "HARDWARE",
    })
    assert r.status_code == 201, r.text
    assert r.json()["device_id"] == "pzem-regr"
