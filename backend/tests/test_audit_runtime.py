"""End-to-end runtime architecture audit tests.

SOFTWARE TESTED (not real hardware): registration idempotency, reading
ingestion -> last_seen -> status ONLINE/OFFLINE, /readings/latest primary
ordering, frontend data shape, ESP32 connection status payload, and the
frozen (PyInstaller) database path selection.

No hardware is required: these tests exercise the same HTTP contract the
ESP32 firmware uses (POST /api/v1/devices, POST .../readings, GET
.../control/pending, POST .../ack).
"""

import os
import sys

# Must be set BEFORE importing app modules so tests use an isolated test DB.
os.environ["APP_TESTING"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Device  # noqa: E402
from app.utils.time import utcnow  # noqa: E402
from datetime import timedelta  # noqa: E402

client = TestClient(app)

# Same clean-slate pattern as test_api.py: run against an isolated test DB and
# start from a known-empty state on every invocation (standalone or full run).
Base.metadata.drop_all(bind=engine)
init_db()

PRIMARY_ID = "ESP32-S3-01"

VALID_READING = {
    "voltage": 230.4,
    "current": 1.35,
    "power": 311.0,
    "energy": 12.34,
    "frequency": 50.0,
    "power_factor": 0.99,
    "data_source": "HARDWARE",
}


def _register(device_id, name, capabilities=None):
    payload = {"id": device_id, "name": name, "device_type": "PZEM-004T"}
    if capabilities is not None:
        payload["capabilities"] = capabilities
    return client.post("/api/v1/devices", json=payload)


def _device_count(device_id):
    db = SessionLocal()
    try:
        return db.query(Device).filter(Device.id == device_id).count()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Device registration idempotency (STEP 7)
# ---------------------------------------------------------------------------

def test_register_new_device_returns_201():
    res = _register("audit-dev-new", "Audit New")
    assert res.status_code == 201
    assert res.json()["id"] == "audit-dev-new"


def test_register_same_device_again_returns_200():
    assert _register("audit-dev-again", "Audit New").status_code == 201
    res = _register("audit-dev-again", "Audit New Renamed")
    assert res.status_code == 200
    assert res.json()["name"] == "Audit New Renamed"


def test_repeated_primary_registration_never_duplicates_rows():
    _register(PRIMARY_ID, "ESP32-S3 Smart Energy")
    for _ in range(3):
        res = _register(PRIMARY_ID, "ESP32-S3 Smart Energy")
        assert res.status_code == 200
    assert _device_count(PRIMARY_ID) == 1


def test_power_cycle_reregistration_returns_200():
    """The exact HTTP sequence the firmware performs must succeed end-to-end."""
    _register(PRIMARY_ID, "ESP32-S3 Smart Energy")
    res = _register(PRIMARY_ID, "ESP32-S3 Smart Energy")  # power-cycle re-register
    assert res.status_code == 200
    assert res.json()["capabilities"]["relay_control"] is True


# ---------------------------------------------------------------------------
# Reading ingestion -> last_seen -> ONLINE (STEP 2 + STEP 9)
# ---------------------------------------------------------------------------

def test_upload_reading_updates_last_seen_and_marks_connected():
    _register(PRIMARY_ID, "ESP32-S3 Smart Energy")
    res = client.post(f"/api/v1/devices/{PRIMARY_ID}/readings", json=VALID_READING)
    assert res.status_code == 201
    body = res.json()
    for key, value in VALID_READING.items():
        if key != "data_source":
            assert body[key] == value, f"field {key} mismatch"
    assert body["data_source"] == "HARDWARE"

    status = client.get(f"/api/v1/devices/{PRIMARY_ID}/status").json()
    assert status["status"] == "CONNECTED"
    assert status["last_seen"] is not None
    assert status["latest_reading"]["power"] == 311.0


def test_latest_readings_endpoint_returns_primary_first():
    """/readings/latest must lead with ESP32-S3-01 even if another HARDWARE
    device reported more recently (primary wins, then recency)."""
    _register(PRIMARY_ID, "ESP32-S3 Smart Energy")
    _register("audit-other-hw", "Other HW")
    client.post(f"/api/v1/devices/{PRIMARY_ID}/readings", json=VALID_READING)
    client.post("/api/v1/devices/audit-other-hw/readings", json={**VALID_READING, "power": 9.0})

    latest = client.get("/api/v1/readings/latest").json()
    assert latest and latest[0]["device_id"] == PRIMARY_ID
    assert latest[0]["power"] == 311.0
    assert latest[0]["data_source"] == "HARDWARE"


def test_frontend_reading_shape_matches_dashboard_usage():
    """Fields the dashboard JS reads must be present and typed correctly."""
    client.post(f"/api/v1/devices/{PRIMARY_ID}/readings", json=VALID_READING)
    latest = client.get("/api/v1/readings/latest").json()
    assert latest, "expected at least one reading"
    row = latest[0]
    for field in ("timestamp", "voltage", "current", "power", "energy",
                  "frequency", "power_factor", "data_source", "device_id"):
        assert field in row, f"missing frontend field: {field}"
    assert isinstance(row["timestamp"], str) and row["timestamp"].endswith("Z")
    assert isinstance(row["power"], (int, float))


# ---------------------------------------------------------------------------
# OFFLINE only after freshness timeout (STEP 9)
# ---------------------------------------------------------------------------

def test_device_offline_only_after_freshness_timeout():
    from app.utils.freshness import CONNECTED_THRESHOLD_SECONDS, STALE_THRESHOLD_SECONDS

    db = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.id == PRIMARY_ID).first()
        assert dev is not None
        dev.last_seen = utcnow().replace(tzinfo=None)
        db.commit()
        db.refresh(dev)
    finally:
        db.close()

    now_fresh = client.get(f"/api/v1/devices/{PRIMARY_ID}/status").json()
    assert now_fresh["status"] == "CONNECTED"

    # Simulate age just below the OFFLINE threshold -> STALE, not OFFLINE.
    db = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.id == PRIMARY_ID).first()
        dev.last_seen = utcnow().replace(tzinfo=None) - timedelta(seconds=CONNECTED_THRESHOLD_SECONDS + 1)
        db.commit()
    finally:
        db.close()
    stale = client.get(f"/api/v1/devices/{PRIMARY_ID}/status").json()
    assert stale["status"] == "STALE"

    db = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.id == PRIMARY_ID).first()
        dev.last_seen = utcnow().replace(tzinfo=None) - timedelta(seconds=STALE_THRESHOLD_SECONDS + 10)
        db.commit()
    finally:
        db.close()
    offline = client.get(f"/api/v1/devices/{PRIMARY_ID}/status").json()
    assert offline["status"] == "OFFLINE"


# ---------------------------------------------------------------------------
# ESP32 connection status payload (STEP 6)
# ---------------------------------------------------------------------------

def test_connection_endpoint_always_returns_expected_shape():
    conn = client.get("/api/v1/setup/connection").json()
    for field in ("managed", "phase", "message", "esp32_ip", "backend_ip",
                  "backend_url", "configured", "online", "runtime"):
        assert field in conn, f"missing /setup/connection field: {field}"
    assert conn["esp32_ip"] == "192.168.4.1"
    assert isinstance(conn["runtime"], dict)


def test_connection_runtime_carries_firewall_and_backend():
    from app.utils.esp32_sync import set_runtime_info

    set_runtime_info({"backend": "RUNNING", "firewall": "READY", "port": 8000})
    conn = client.get("/api/v1/setup/connection").json()
    assert conn["runtime"]["backend"] == "RUNNING"
    assert conn["runtime"]["firewall"] == "READY"
    assert conn["runtime"]["port"] == 8000


# ---------------------------------------------------------------------------
# Frozen (PyInstaller) database path selection (STEP 4)
# ---------------------------------------------------------------------------

def test_frozen_mode_database_path_under_localappdata(monkeypatch, tmp_path):
    import backend.app.paths as paths_mod

    monkeypatch.delenv("SEA_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    target = tmp_path / "AppData" / "Local" / paths_mod.APP_NAME
    assert paths_mod.data_dir() == target
    assert paths_mod.database_path() == target / "smart_energy.db"
    assert paths_mod.resource_dir() != paths_mod.data_dir()


def test_dev_mode_database_path_is_repo_root(monkeypatch):
    import backend.app.paths as paths_mod

    monkeypatch.delenv("SEA_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths_mod.data_dir() == paths_mod.resource_dir()
    assert paths_mod.database_path() == paths_mod.resource_dir() / "smart_energy.db"


def test_primary_device_config_matches_hardware_id():
    assert settings.PRIMARY_DEVICE_ID == "ESP32-S3-01"
    assert PRIMARY_ID == settings.PRIMARY_DEVICE_ID