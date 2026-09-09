"""UDP backend discovery broadcaster for the ESP32 Smart Energy Access Point.

The laptop that runs SmartEnergyAssistant.exe joins the ESP32 SoftAP
("SmartEnergyESP32") over Wi-Fi and receives a DYNAMIC IPv4 address from the AP
DHCP server (192.168.4.2, 192.168.4.5, 192.168.4.100, ... - never hardcoded).

The FastAPI backend listens on 0.0.0.0:8000, but the ESP32 has no idea which
address the laptop got. This module periodically announces the laptop's actual
IPv4 over UDP so the ESP32 can discover the backend and start streaming with
zero manual configuration (no ipconfig, no static IP, no 192.168.4.2 assumption).

Wire message (JSON, one datagram per announcement):

  {"service":"SMART_ENERGY_BACKEND","version":1,"host":"192.168.4.7","port":8000}

The ESP32 firmware validates every packet (service id, supported version, IPv4
inside its own 192.168.4.0/24 subnet, valid port) before accepting it.

Constants are centralized here and mirrored in firmware/smart-energy/config.h.
"""

import ipaddress
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from . import esp32_bridge as bridge

logger = logging.getLogger("sea.udp_discovery")

# ---- Centralized discovery protocol constants -------------------------------
# Mirrored in firmware/smart-energy/config.h (BACKEND_DISCOVERY_*).
DISCOVERY_SERVICE = "SMART_ENERGY_BACKEND"
DISCOVERY_VERSION = 1
DISCOVERY_PORT = 44441
# Directed broadcast for the ESP32 AP subnet (192.168.4.0/24).
DISCOVERY_BROADCAST_IP = "192.168.4.255"
ANNOUNCE_INTERVAL_SECONDS = 2.0
MAX_PACKET_SIZE = 512

BACKEND_PORT = bridge.BACKEND_PORT

# Destinations the announcement is sent to. The unicast to the AP IP is a
# belt-and-braces fallback for stacks/networks that filter directed broadcasts.
def announcement_destinations() -> List[Tuple[str, int]]:
    return [(DISCOVERY_BROADCAST_IP, DISCOVERY_PORT), (bridge.ESP32_AP_IP, DISCOVERY_PORT)]


# ---------------------------------------------------------------------------
# Message building / parsing / validation
# ---------------------------------------------------------------------------
def build_discovery_payload(host: str, port: int) -> bytes:
    """Serialize one discovery announcement (ArduinoJson-compatible compact JSON)."""
    payload = {
        "service": DISCOVERY_SERVICE,
        "version": DISCOVERY_VERSION,
        "host": str(host),
        "port": int(port),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def parse_discovery_payload(data: bytes) -> Optional[dict]:
    """Validate a received announcement the same way the firmware does.

    Returns {"host": str, "port": int} when the packet is acceptable, else None.
    Strict rules:
      - decodes as JSON
      - service == SMART_ENERGY_BACKEND (exact)
      - version == 1 (exact integer)
      - host is a valid IPv4 inside 192.168.4.0/24, not x.0 / x.255
      - port is an int in 1..65535
    """
    if not data:
        return None
    try:
        text = data.decode("utf-8").strip()
    except (UnicodeDecodeError, AttributeError):
        return None
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None

    if obj.get("service") != DISCOVERY_SERVICE:
        return None
    if obj.get("version") != DISCOVERY_VERSION:
        return None

    host = obj.get("host")
    if not isinstance(host, str):
        return None
    if not _is_valid_discovery_host(host):
        return None

    port = obj.get("port")
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if not (1 <= port <= 65535):
        return None

    return {"host": host, "port": port}


def _is_valid_discovery_host(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    if not bridge.in_sea_subnet(host):
        return False
    if addr in (bridge.SEA_SUBNET.network_address, bridge.SEA_SUBNET.broadcast_address):
        return False
    return True


def backend_url_from_discovery(host: str, port: int) -> str:
    """Build the URL the ESP32 should upload to after discovery."""
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Broadcaster
# ---------------------------------------------------------------------------
@dataclass
class BroadcastSnapshot:
    """Latest broadcaster state, exposed for logs/status."""
    announcing: bool
    host: Optional[str]
    port: Optional[int]
    last_announced_at: Optional[float]
    errors: int


class BackendDiscoveryBroadcaster(threading.Thread):
    """Periodically announce the laptop's SEA-subnet IPv4 to the ESP32 over UDP.

    - Re-detects the IPv4 every interval: laptop IP changes (.2 -> .5 -> .100)
      are announced automatically, with no restart required.
    - Only announces an address actually inside 192.168.4.0/24 (the ESP32 AP
      subnet); when the laptop is on some other network, nothing is sent and
      announcing is reported as False.
    - Sends to both the directed broadcast (192.168.4.255) and the AP itself
      (192.168.4.1) so discovery survives stacks that filter broadcasts.
    """

    def __init__(
        self,
        port: int = BACKEND_PORT,
        interval: float = ANNOUNCE_INTERVAL_SECONDS,
    ):
        super().__init__(name="sea-udp-discovery", daemon=True)
        self.port = port
        self.interval = interval
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._host: Optional[str] = None
        self._last_announced_at: Optional[float] = None
        self._errors = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def _detect_ip(self) -> Optional[str]:
        """Prefer the sync service's already-detected address (EXE), else detect."""
        from .esp32_sync import get_sync_status

        status = get_sync_status()
        ip = status.get("backend_ip")
        if not ip or not bridge.is_usable_ipv4(str(ip)):
            ip = bridge.detect_laptop_ipv4()
        return ip

    def _send_datagram(self, payload: bytes, dest: Tuple[str, int]) -> None:
        """Send one UDP datagram to dest. Raises on failure."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(1.0)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass
            sock.sendto(payload, dest)
        finally:
            sock.close()

    def _announce(self, ip: str) -> None:
        payload = build_discovery_payload(ip, self.port)
        sent = 0
        for dest in announcement_destinations():
            try:
                self._send_datagram(payload, dest)
                sent += 1
            except OSError:
                self._errors += 1
                logger.warning("UDP discovery send to %s failed", dest)
        with self._lock:
            self._host = ip
            self._last_announced_at = time.time()
        logger.info("UDP discovery announcing: %s:%d (sent=%d/%d)",
                    ip, self.port, sent, len(announcement_destinations()))

    def _tick(self) -> None:
        ip = self._detect_ip()
        if not ip:
            with self._lock:
                self._host = None
            logger.debug("UDP discovery: no SmartEnergyESP32 subnet address (waiting)")
            return
        if not bridge.in_sea_subnet(ip):
            with self._lock:
                self._host = None
            logger.info("UDP discovery: address %s is not on 192.168.4.0/24; not announcing", ip)
            return
        self._announce(ip)

    def run(self) -> None:
        logger.info(
            "UDP backend discovery started (port=%d, interval=%.1fs)",
            self.port, self.interval,
        )
        while not self.stopped:
            try:
                self._tick()
            except Exception:
                logger.exception("UDP discovery tick failed")
            self._stop_event.wait(self.interval)
        logger.info("UDP backend discovery stopped")

    def snapshot(self) -> BroadcastSnapshot:
        with self._lock:
            return BroadcastSnapshot(
                announcing=self._host is not None,
                host=self._host,
                port=self.port,
                last_announced_at=self._last_announced_at,
                errors=self._errors,
            )


# ---------------------------------------------------------------------------
# Process-lifetime singleton (started from the FastAPI lifespan)
# ---------------------------------------------------------------------------
_broadcaster: Optional[BackendDiscoveryBroadcaster] = None


def start_broadcaster() -> bool:
    """Start the broadcaster once. Returns True when it is running."""
    global _broadcaster
    if _broadcaster is not None and _broadcaster.is_alive() and not _broadcaster.stopped:
        return True
    _broadcaster = BackendDiscoveryBroadcaster()
    _broadcaster.start()
    return True


def stop_broadcaster() -> None:
    global _broadcaster
    if _broadcaster is not None:
        _broadcaster.stop()
        _broadcaster.join(timeout=2.0)
        _broadcaster = None


def get_broadcast_status() -> dict:
    if _broadcaster is None:
        return {"announcing": False, "host": None, "port": None, "last_announced_at": None}
    snap = _broadcaster.snapshot()
    return {
        "announcing": snap.announcing,
        "host": snap.host,
        "port": snap.port,
        "last_announced_at": snap.last_announced_at,
    }