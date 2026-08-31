import sys
import os
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
