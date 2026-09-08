"""Background ESP32 <-> laptop backend auto-configuration service.

Runs in the Smart Energy Assistant desktop process. Detects the laptop IPv4 on
the SmartEnergyESP32 network, pushes the dynamically computed backend URL to
the ESP32 AP configuration server, verifies it, and continuously recovers when:
- Wi-Fi is not connected yet (retries every 2 s, no restart required)
- the laptop IP changes
- the ESP32 disappears (Wi-Fi drop / power cycle) and comes back

The current state is mirrored into a process-wide store that the backend
exposes via GET /api/v1/setup/connection.
"""

import logging
import threading
import time
from typing import Any, Callable, Optional

from . import esp32_bridge as bridge

logger = logging.getLogger("sea.esp32_sync")

PHASE_NO_WIFI = "NO_WIFI"
PHASE_WAITING_ESP32 = "WAITING_ESP32"
PHASE_CONFIGURING = "CONFIGURING"
PHASE_ONLINE = "ONLINE"
PHASE_DISCONNECTED = "DISCONNECTED"
PHASE_STOPPED = "STOPPED"

_NO_WIFI_MESSAGE = "Connect this laptop to SmartEnergyESP32 Wi-Fi to connect the hardware."

# Process-wide status store shared with the backend /setup/connection endpoint.
_status_lock = threading.Lock()
_status: dict = {
    "managed": False,
    "phase": PHASE_STOPPED,
    "message": "",
    "esp32_ip": bridge.ESP32_AP_IP,
    "backend_ip": None,
    "backend_url": None,
    "configured": False,
    "online": False,
    "last_attempt_at": None,
    "config_errors": 0,
}


def get_sync_status() -> dict:
    with _status_lock:
        return dict(_status)


def _set_status(**kwargs) -> None:
    with _status_lock:
        _status.update(kwargs)


class ESP32Sync(threading.Thread):
    def __init__(
        self,
        port: int = bridge.BACKEND_PORT,
        interval: float = 2.0,
        on_status: Optional[Callable[[dict], None]] = None,
    ):
        super().__init__(name="sea-esp32-sync", daemon=True)
        self.port = port
        self.interval = interval
        self.on_status = on_status
        self._stop_event = threading.Event()
        self._current_url: Optional[str] = None
        self._last_pushed_url: Optional[str] = None
        self._gear_gap_seen = False  # ESP32 reachable again after going silent

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def _publish(self, phase: str, message: str, **kwargs) -> None:
        snapshot = get_sync_status()
        snapshot["managed"] = True
        snapshot["phase"] = phase
        snapshot["message"] = message
        snapshot.update(kwargs)
        with _status_lock:
            _status.update(snapshot)
        signed = dict(_status)
        if self.on_status:
            try:
                self.on_status(signed)
            except Exception:  # never let UI callbacks kill the loop
                logger.exception("esp32 sync status callback failed")
        logger.debug("esp32 sync: %s | %s | url=%s", phase, message, signed.get("backend_url"))

    def run(self) -> None:
        logger.info("ESP32 auto-config service started (interval=%.1fs, port=%d)", self.interval, self.port)
        _set_status(managed=True)
        while not self.stopped:
            try:
                self._tick()
            except Exception:
                logger.exception("esp32 sync tick failed")
            self._stop_event.wait(self.interval)
        _set_status(managed=False, phase=PHASE_STOPPED, message="")
        logger.info("ESP32 auto-config service stopped")

    def _tick(self) -> None:
        interfaces = bridge.enumerate_interfaces()
        ip = bridge.pick_backend_ip(interfaces)
        if not ip:
            self._gear_gap_seen = False
            self._publish(
                PHASE_NO_WIFI,
                _NO_WIFI_MESSAGE,
                backend_ip=None,
                backend_url=None,
                configured=False,
                online=False,
            )
            return

        url = bridge.backend_url_for(ip, self.port)
        url_changed = url != self._current_url
        self._current_url = url

        sea_wifi = bridge.wifi_connected_to_sea(interfaces)
        if not sea_wifi and not bridge.esp32_reachable():
            self._gear_gap_seen = False
            self._publish(
                PHASE_NO_WIFI,
                _NO_WIFI_MESSAGE,
                backend_ip=ip,
                backend_url=url,
                configured=False,
                online=False,
            )
            return

        if not bridge.esp32_reachable():
            self._gear_gap_seen = True
            was_online = _status.get("online", False)
            self._publish(
                PHASE_DISCONNECTED if was_online else PHASE_WAITING_ESP32,
                "Waiting for ESP32 Smart Energy hardware (SmartEnergyESP32 Wi-Fi)..." if not was_online
                else "ESP32 went offline - waiting for it to come back...",
                backend_ip=ip,
                backend_url=url,
                configured=False,
                online=False,
            )
            return

        # ESP32 is reachable: confirm what it currently has configured.
        status = bridge.esp32_status()
        needs_push = (
            url_changed
            or url != self._last_pushed_url
            or status is None
            or not status.get("configured")
            or bridge.normalize_backend_url(status.get("backend_url", "")) != url
            or self._gear_gap_seen
        )

        if needs_push:
            self._publish(
                PHASE_CONFIGURING,
                f"Configuring ESP32 backend -> {url}...",
                backend_ip=ip,
                backend_url=url,
                configured=False,
                online=False,
            )
            ok, code, detail = bridge.configure_esp32(url)
            with _status_lock:
                _status["last_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if not ok:
                    _status["config_errors"] = _status.get("config_errors", 0) + 1
                else:
                    _status["config_errors"] = 0
            if not ok:
                logger.warning("ESP32 config failed (code=%s detail=%s)", code, detail)
                self._publish(
                    PHASE_WAITING_ESP32,
                    f"Could not configure ESP32 (HTTP {code}) - retrying...",
                    backend_ip=ip,
                    backend_url=url,
                    configured=False,
                    online=False,
                )
                return

            self._last_pushed_url = url
            self._gear_gap_seen = False
            if not bridge.verify_esp32_config(url):
                logger.warning("ESP32 config pushed but verification mismatch for %s", url)
                self._last_pushed_url = None
                return

        self._publish(
            PHASE_ONLINE,
            "ESP32-S3 Smart Energy - Online",
            backend_ip=ip,
            backend_url=url,
            configured=True,
            online=True,
        )