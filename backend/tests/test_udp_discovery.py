"""UDP backend discovery tests (backend side of the protocol).

Covers the broadcaster + message contract that the ESP32 firmware consumes:
  - laptop IP variants (192.168.4.2 / .5 / .100) are announced correctly
  - invalid / malformed / foreign packets are rejected by the shared parser
  - laptop IP changes are re-announced without restart
  - temporary backend loss stops announcements; rediscovery resumes them
  - the wire constants match the firmware config (contract test)
"""

import json
import os
import sys
from pathlib import Path

os.environ["APP_TESTING"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils import udp_discovery  # noqa: E402
from app.utils.udp_discovery import (  # noqa: E402
    DISCOVERY_BROADCAST_IP,
    DISCOVERY_PORT,
    DISCOVERY_SERVICE,
    DISCOVERY_VERSION,
    BackendDiscoveryBroadcaster,
    announcement_destinations,
    backend_url_from_discovery,
    build_discovery_payload,
    parse_discovery_payload,
)

FIRMWARE_CONFIG_H = Path(__file__).resolve().parents[2] / "firmware" / "smart-energy" / "config.h"


class _RecordingBroadcaster(BackendDiscoveryBroadcaster):
    """No network: injectable IP source + datagram recorder."""

    def __init__(self, ip_provider):
        super().__init__(port=8000)
        self._ip_provider = ip_provider
        self.sent = []

    def _detect_ip(self):
        return self._ip_provider()

    def _send_datagram(self, payload, dest):
        self.sent.append((payload, dest))


def _parse_sent(broadcaster):
    return [parse_discovery_payload(payload) for payload, _ in broadcaster.sent]


# ---------------------------------------------------------------------------
# Building / parsing (laptop IP variants)
# ---------------------------------------------------------------------------

def test_payload_carries_expected_fields():
    payload = json.loads(build_discovery_payload("192.168.4.2", 8000).decode("utf-8"))
    assert payload == {
        "service": "SMART_ENERGY_BACKEND",
        "version": 1,
        "host": "192.168.4.2",
        "port": 8000,
    }


def test_round_trip_laptop_ip_variants():
    for host in ("192.168.4.2", "192.168.4.5", "192.168.4.100"):
        parsed = parse_discovery_payload(build_discovery_payload(host, 8000))
        assert parsed == {"host": host, "port": 8000}, host


def test_backend_url_from_discovery():
    assert backend_url_from_discovery("192.168.4.7", 8000) == "http://192.168.4.7:8000"
    assert backend_url_from_discovery("192.168.4.100", 8000) == "http://192.168.4.100:8000"


def test_parse_rejects_garbage_and_malformed():
    assert parse_discovery_payload(b"") is None
    assert parse_discovery_payload(b"not-a-packet") is None
    assert parse_discovery_payload(b'{"broken": ') is None
    assert parse_discovery_payload(b"[1, 2, 3]") is None  # not an object
    assert parse_discovery_payload(b'{"service":"OTHER","version":1,"host":"192.168.4.2","port":8000}') is None
    assert parse_discovery_payload(b'{"service":"SMART_ENERGY_BACKEND","version":2,"host":"192.168.4.2","port":8000}') is None
    assert parse_discovery_payload(b'{"service":"SMART_ENERGY_BACKEND","version":1,' +
                                  b'"host":"192.168.4.2","port":8000}  extra') is None


def test_parse_rejects_bad_host():
    good = {"service": DISCOVERY_SERVICE, "version": DISCOVERY_VERSION, "host": "x", "port": 8000}
    for host in ("not-an-ip", "192.168.5.2", "10.0.0.1", "192.168.4.0", "192.168.4.255",
                 "192.168.4", "::1", "", 123):
        bad = dict(good, host=host)
        packet = json.dumps(bad).encode("utf-8")
        assert parse_discovery_payload(packet) is None, host


def test_parse_rejects_bad_port():
    good = {"service": DISCOVERY_SERVICE, "version": DISCOVERY_VERSION,
            "host": "192.168.4.2", "port": 8000}
    for port in (0, -1, 65536, 999999, "8000", None):
        bad = dict(good, port=port)
        packet = json.dumps(bad).encode("utf-8")
        assert parse_discovery_payload(packet) is None, port


# ---------------------------------------------------------------------------
# Broadcaster behaviour
# ---------------------------------------------------------------------------

def test_broadcaster_announces_to_broadcast_and_ap():
    b = _RecordingBroadcaster(lambda: "192.168.4.5")
    b._tick()
    dests = sorted(d for _, d in b.sent)
    # Two datagrams: directed broadcast + unicast to the AP itself.
    assert ("192.168.4.255", DISCOVERY_PORT) in dests
    assert ("192.168.4.1", DISCOVERY_PORT) in dests
    parsed = _parse_sent(b)
    assert all(p == {"host": "192.168.4.5", "port": 8000} for p in parsed)


def test_broadcaster_silent_when_no_sea_address():
    b = _RecordingBroadcaster(lambda: None)
    b._tick()
    assert b.sent == []
    assert b.snapshot().announcing is False


def test_broadcaster_does_not_announce_foreign_subnet():
    b = _RecordingBroadcaster(lambda: "192.168.1.10")
    b._tick()
    assert b.sent == []


def test_broadcaster_reannounces_when_laptop_ip_changes():
    ips = iter(["192.168.4.2", "192.168.4.7", "192.168.4.100"])
    b = _RecordingBroadcaster(lambda: next(ips))
    b._tick()
    b._tick()
    b._tick()
    seen = {parsed["host"] for parsed in _parse_sent(b)}
    assert seen == {"192.168.4.2", "192.168.4.7", "192.168.4.100"}


def test_broadcaster_gap_then_rediscovery():
    state = {"ip": "192.168.4.5"}

    def provider():
        return state["ip"]

    b = _RecordingBroadcaster(provider)
    b._tick()
    assert len(b.sent) == 2

    state["ip"] = None  # laptop backend temporarily disappears
    before_gap = len(b.sent)
    b._tick()
    assert len(b.sent) == before_gap  # nothing announced during the gap
    assert b.snapshot().announcing is False

    state["ip"] = "192.168.4.5"  # laptop reconnects -> rediscovery resumes
    b._tick()
    assert len(b.sent) == before_gap + 2
    assert _parse_sent(b)[-1] == {"host": "192.168.4.5", "port": 8000}


def test_announcement_destinations_are_stable():
    assert announcement_destinations() == [
        ("192.168.4.255", DISCOVERY_PORT),
        ("192.168.4.1", DISCOVERY_PORT),
    ]


def test_broadcast_status_shape():
    b = _RecordingBroadcaster(lambda: "192.168.4.100")
    b._tick()
    snap = b.snapshot()
    assert snap.announcing is True
    assert snap.host == "192.168.4.100"
    assert snap.port == 8000
    assert snap.last_announced_at is not None
    assert snap.errors == 0


# ---------------------------------------------------------------------------
# Firmware contract (wire constants must match firmware config.h)
# ---------------------------------------------------------------------------

def test_firmware_config_matches_wire_constants():
    text = FIRMWARE_CONFIG_H.read_text(encoding="utf-8")
    assert f'BACKEND_DISCOVERY_SERVICE "{DISCOVERY_SERVICE}"' in text.replace("\r\n", "\n")
    assert f"BACKEND_DISCOVERY_VERSION {DISCOVERY_VERSION}" in text
    assert f"BACKEND_DISCOVERY_UDP_PORT {DISCOVERY_PORT}" in text
    assert DISCOVERY_BROADCAST_IP == "192.168.4.255"


def test_firmware_ap_subnet_matches_backend():
    from app.utils.esp32_bridge import SEA_SUBNET, in_sea_subnet

    assert str(SEA_SUBNET) == "192.168.4.0/24"
    for ip in ("192.168.4.1", "192.168.4.2", "192.168.4.100"):
        assert in_sea_subnet(ip)


def test_firmware_config_contains_lost_threshold():
    text = FIRMWARE_CONFIG_H.read_text(encoding="utf-8")
    assert "BACKEND_LOST_FAILURE_THRESHOLD" in text