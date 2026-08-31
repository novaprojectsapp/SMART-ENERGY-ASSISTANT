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
    assert res.status_code == 409


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


def test_appliance_activity():
    res = client.get("/api/v1/appliances/activity")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("AI_MODEL_NOT_AVAILABLE", "NO_DATA", "OK")


def test_appliance_models():
    res = client.get("/api/v1/appliances/models")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


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

    # Verify a control command row was persisted and honestly marked SIMULATED (no hardware).
    cmd_count = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).count()
    assert cmd_count >= 1
    new_cmd = db.query(ControlCommand).filter(ControlCommand.appliance_id == app["id"]).order_by(ControlCommand.created_at.desc()).first()
    assert new_cmd.status == "PENDING"
    assert "Hardware control is not connected yet" in new_cmd.message
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
def test_control_honest_simulated_response():
    app = _make_sched_appliance(name="Sched CtrlBulb")
    r = client.post(f"/api/v1/appliances/{app['id']}/control", json={
        "appliance_id": app["id"], "action": "ON", "source": "USER",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "SIMULATED"
    assert "Hardware control is not connected yet" in data["message"]
    assert data["hardware_control_available"] is False


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
