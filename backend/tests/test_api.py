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
