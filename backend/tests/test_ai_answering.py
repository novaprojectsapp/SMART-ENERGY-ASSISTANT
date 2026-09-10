"""
Comprehensive tests for the AI answering pipeline.

Tests intent classification, response quality, safety handling,
hallucination prevention, and follow-up conversation support.
"""
import sys
import os

os.environ["APP_TESTING"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, engine, Base
from app.models import Device, EnergyReading, Appliance, ControlCommand

Base.metadata.drop_all(bind=engine)
init_db()

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures: seed a device with realistic readings
# ---------------------------------------------------------------------------
DEVICE_ID = "ai-test-device"


def _seed_device():
    client.post("/api/v1/devices", json={
        "id": DEVICE_ID, "name": "AI Test Device", "device_type": "PZEM-004T",
    })


def _seed_reading(voltage=230.9, current=1.24, power=286.3, energy=12.42,
                  frequency=50.0, power_factor=0.96, hours_ago=0):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    client.post(f"/api/v1/devices/{DEVICE_ID}/readings", json={
        "timestamp": ts.isoformat(),
        "voltage": voltage, "current": current, "power": power,
        "energy": energy, "frequency": frequency, "power_factor": power_factor,
        "data_source": "SIMULATOR",
    })


def _seed_appliance(name="Test Bulb 1", channel=1, capable=True):
    r = client.post("/api/v1/appliances", json={
        "name": name, "type": "BULB", "channel": channel,
        "device_id": DEVICE_ID, "control_capable": capable,
    })
    return r.json()


def _voice(text, device_id=DEVICE_ID):
    return client.post("/api/v1/voice/query", json={"text": text, "device_id": device_id}).json()


@pytest.fixture(scope="module", autouse=True)
def _seeded_device():
    """Seed the device and 7 days of readings at test-time.

    Deferred to a fixture (rather than module import) so the seed survives
    other test modules that drop all tables at import time.
    """
    _seed_device()
    for day in range(7):
        _seed_reading(
            voltage=230.0 + (day * 0.5),
            current=1.0 + (day * 0.1),
            power=230.0 + (day * 15),
            energy=1.0 + (day * 2.0),
            hours_ago=day * 24,
        )
    _seed_reading(voltage=230.9, current=1.24, power=286.3, energy=12.42, hours_ago=0)


# ============================================================================
# 1. POWER QUERIES
# ============================================================================
def test_what_is_my_power():
    d = _voice("what is my power")
    assert d["intent"] == "CURRENT_POWER"
    assert d["confidence"] > 0.8
    resp = d["response"].lower()
    assert "watt" in resp
    assert "286" in resp or "286.3" in resp


def test_how_much_power_am_i_using():
    d = _voice("how much power am I using now")
    assert d["intent"] == "CURRENT_POWER"
    resp = d["response"].lower()
    assert "watt" in resp


def test_whats_happening_now():
    d = _voice("what is happening now")
    assert d["intent"] == "CURRENT_POWER"
    assert d["confidence"] > 0.5
    resp = d["response"].lower()
    assert "watt" in resp or "power" in resp


def test_how_much_load():
    d = _voice("how much load is running")
    assert d["intent"] == "CURRENT_POWER"


# ============================================================================
# 2. VOLTAGE QUERIES
# ============================================================================
def test_what_voltage_do_i_have():
    d = _voice("what voltage do I have")
    assert d["intent"] == "CURRENT_VOLTAGE"
    assert d["confidence"] > 0.8
    resp = d["response"].lower()
    assert "volt" in resp
    assert "230" in resp


def test_is_my_voltage_high():
    d = _voice("is my voltage high")
    assert d["intent"] == "CURRENT_VOLTAGE"
    resp = d["response"].lower()
    assert "volt" in resp


# ============================================================================
# 3. ENERGY / CONSUMPTION QUERIES
# ============================================================================
def test_how_much_electricity_today():
    d = _voice("how much electricity did I use today")
    assert d["intent"] in ("CURRENT_ENERGY", "TODAY_ENERGY")
    resp = d["response"].lower()
    assert "kilowatt" in resp or "kwh" in resp or "unit" in resp


def test_energy_cost_today():
    d = _voice("what is my electricity cost today")
    assert d["intent"] == "TODAY_COST"
    resp = d["response"].lower()
    assert "rupee" in resp or "\u20b9" in resp or "cost" in resp


# ============================================================================
# 4. BILLING QUERIES
# ============================================================================
def test_monthly_bill():
    d = _voice("what will my monthly bill be")
    assert d["intent"] == "MONTHLY_BILL"
    resp = d["response"].lower()
    assert "rupee" in resp or "\u20b9" in resp or "bill" in resp


def test_billing_period_bill():
    d = _voice("what will my bill be for two months")
    assert d["intent"] == "BILL_PREDICTION"
    resp = d["response"].lower()
    assert "rupee" in resp or "\u20b9" in resp or "bill" in resp


def test_why_is_my_bill_high():
    d = _voice("why is my bill high")
    assert d["intent"] in ("NORMAL_USAGE", "ENERGY_COMPARISON", "BILL_PREDICTION")


def test_is_my_usage_normal():
    d = _voice("is my usage normal")
    assert d["intent"] in ("NORMAL_USAGE", "ENERGY_COMPARISON")


def test_am_i_using_too_much():
    d = _voice("am I using too much electricity")
    assert d["intent"] in ("NORMAL_USAGE", "ENERGY_COMPARISON")


# ============================================================================
# 5. GENERAL / STATUS QUERIES
# ============================================================================
def test_whats_happening_just_now():
    d = _voice("what happened just now")
    assert d["intent"] in ("LAST_UPDATE", "CURRENT_POWER")


def test_is_device_online():
    d = _voice("is the device online")
    assert d["intent"] == "DEVICE_STATUS"
    resp = d["response"].lower()
    assert "online" in resp or "offline" in resp or "connected" in resp


def test_when_was_last_reading():
    d = _voice("when was the last reading")
    assert d["intent"] == "LAST_UPDATE"
    resp = d["response"].lower()
    assert "ago" in resp


# ============================================================================
# 6. FOLLOW-UP QUERIES (conversation context)
# ============================================================================
def test_followup_is_that_high():
    """After asking about power, 'is that high?' should still classify."""
    _voice("what is my power")
    d = _voice("is that high")
    assert d["intent"] in ("CURRENT_POWER", "NORMAL_USAGE", "ENERGY_COMPARISON")
    assert len(d["response"]) > 5


def test_followup_billing_period():
    """After 'what is my bill?', 'what about two months?' should map to BILL_PREDICTION."""
    _voice("what is my bill")
    d = _voice("what about two months")
    assert d["intent"] == "BILL_PREDICTION"


# ============================================================================
# 7. SAFETY TESTS
# ============================================================================
def test_over_voltage_active_blocks_control():
    """When voltage exceeds 250V, the safety context should be flagged."""
    # Seed a high-voltage reading
    ts = datetime.now(timezone.utc)
    client.post(f"/api/v1/devices/{DEVICE_ID}/readings", json={
        "timestamp": ts.isoformat(),
        "voltage": 255.0, "current": 1.0, "power": 255.0,
        "energy": 12.5, "frequency": 50.0, "power_factor": 0.95,
        "data_source": "SIMULATOR",
    })
    d = _voice("what is my voltage")
    assert d["intent"] == "CURRENT_VOLTAGE"
    resp = d["response"].lower()
    assert "255" in resp or "high" in resp or "safe" in resp or "protect" in resp

    # Restore normal voltage
    _seed_reading(voltage=230.9, current=1.24, power=286.3, energy=12.42, hours_ago=0)


def test_manual_control_creates_pending():
    """Manual ON creates a pending command (not instant execution)."""
    app = _seed_appliance("Safety Test Bulb")
    d = _voice("turn on safety test bulb")
    assert d["intent"] == "MANUAL_APPLIANCE_ON"
    assert "Waiting for confirmation" in d["response"] or "Command sent" in d["response"]


def test_control_pending_not_immediate():
    """Control response never claims immediate success."""
    app = _seed_appliance("Pending Test Bulb")
    d = _voice("turn on pending test bulb")
    resp = d["response"].lower()
    assert "turned on" not in resp or "waiting" in resp or "command sent" in resp


# ============================================================================
# 8. HALLUCINATION PREVENTION
# ============================================================================
def test_missing_voltage_data():
    """When no data is available, should not fabricate values."""
    client.post("/api/v1/devices", json={
        "id": "no-data-device", "name": "No Data", "device_type": "PZEM-004T",
    })
    d = _voice("what is my voltage", device_id="no-data-device")
    assert d["intent"] == "CURRENT_VOLTAGE"
    resp = d["response"].lower()
    assert "no data" in resp or "not available" in resp or "ensure" in resp or "no device" in resp or "no reading" in resp
    # Must not contain any fabricated voltage value
    assert "230" not in resp
    assert "240" not in resp


def test_missing_historical_baseline():
    """With no recent data, must not claim a comparison baseline."""
    client.post("/api/v1/devices", json={
        "id": "fresh-device", "name": "Fresh", "device_type": "PZEM-004T",
    })
    d = _voice("is my usage normal", device_id="fresh-device")
    resp = d["response"].lower()
    # Should either say no data, or not make a comparative claim
    assert "not enough" in resp or "no data" in resp or "no reading" in resp or "insufficient" in resp or "7 days" in resp or "don't have enough" in resp


def test_missing_billing_data():
    """With no recent readings, billing projection should say insufficient data."""
    client.post("/api/v1/devices", json={
        "id": "no-billing-device", "name": "No Billing", "device_type": "PZEM-004T",
    })
    d = _voice("what will my monthly bill be", device_id="no-billing-device")
    assert d["intent"] == "MONTHLY_BILL"
    resp = d["response"].lower()
    assert "not enough" in resp or "no data" in resp or "insufficient" in resp


# ============================================================================
# 9. RESPONSE FORMAT
# ============================================================================
def test_response_has_content():
    """All responses must be non-empty strings."""
    queries = [
        "what is my power", "what voltage do I have", "help",
        "what is my bill", "is the device online",
    ]
    for q in queries:
        d = _voice(q)
        assert isinstance(d["response"], str) and len(d["response"]) > 0, f"No response for '{q}'"


def test_response_schema_intact():
    """The response schema must not change."""
    d = _voice("what is my power")
    assert "query" in d
    assert "intent" in d
    assert "confidence" in d
    assert "response" in d
    assert "source" in d
    assert "processing_time_ms" in d


def test_response_source_is_local_or_ai():
    """Source should be LOCAL or AI (not broken)."""
    d = _voice("what is my power")
    assert d["source"] in ("LOCAL", "AI", "LLM")


def test_processing_time_is_positive():
    d = _voice("what is my power")
    assert d["processing_time_ms"] > 0


# ============================================================================
# 10. NUMERIC FORMATTING
# ============================================================================
def test_power_format_watts():
    """Power under 1000W should use watts format."""
    d = _voice("what is my power")
    resp = d["response"].lower()
    assert "watt" in resp


def test_currency_format():
    """Cost responses should use rupee symbol or word."""
    d = _voice("how much electricity cost today")
    resp = d["response"]
    assert "\u20b9" in resp or "rupee" in resp.lower()


# ============================================================================
# 11. CONFIRMATION: Existing intents still work
# ============================================================================
def test_existing_intent_power():
    d = _voice("what is the current power")
    assert d["intent"] == "CURRENT_POWER"


def test_existing_intent_voltage():
    d = _voice("current voltage")
    assert d["intent"] == "CURRENT_VOLTAGE"


def test_existing_intent_current():
    d = _voice("how much current")
    assert d["intent"] == "CURRENT_CURRENT"


def test_existing_intent_frequency():
    d = _voice("current frequency")
    assert d["intent"] == "CURRENT_FREQUENCY"


def test_existing_intent_power_factor():
    d = _voice("power factor reading")
    assert d["intent"] == "CURRENT_POWER_FACTOR"


def test_existing_intent_today_energy():
    d = _voice("how much energy did I use today")
    assert d["intent"] in ("CURRENT_ENERGY", "TODAY_ENERGY")


def test_existing_intent_help():
    d = _voice("help")
    assert d["intent"] == "HELP"
    assert len(d["response"]) > 20


def test_existing_intent_unknown():
    d = _voice("blargh flerb noop")
    assert d["intent"] == "UNKNOWN"


def test_existing_intent_schedule():
    """Scheduling intents should still work through the new pipeline."""
    did = "ai-sched-unique-device"
    client.post("/api/v1/devices", json={"id": did, "name": "Sched Unique", "device_type": "PZEM-004T"})
    client.post("/api/v1/appliances", json={
        "name": "AI Unique Schedule Bulb", "type": "BULB", "channel": 1,
        "device_id": did, "control_capable": True,
    })
    d = _voice("turn on AI Unique Schedule Bulb at 6 PM every day", device_id=did)
    assert d["intent"] == "CREATE_SCHEDULE"
    assert "Scheduled" in d["response"] or "What time" in d["response"] or "What" in d["response"]


# ============================================================================
# 12. GEMINI FALLBACK (disabled mode)
# ============================================================================
def test_gemini_disabled_mode():
    """When Gemini is disabled, system must still respond locally."""
    from app.config import settings
    original = settings.GEMINI_ENABLED
    settings.GEMINI_ENABLED = False
    try:
        d = _voice("what is my power")
        assert d["response"]
        assert d["source"] in ("LOCAL", "AI")
    finally:
        settings.GEMINI_ENABLED = original
