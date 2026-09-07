"""
ESP32 control adapter.

Architecture: the backend does NOT open a direct connection to the ESP32.
Instead it writes a PENDING ControlCommand into the command queue. The ESP32
polls the backend every ~1s, executes the relay, and acknowledges the result.
Only after a real acknowledgement is a command marked EXECUTED (or FAILED).

Any control-capable appliance mapped to a real ESP32 device creates a genuine
PENDING command queued for hardware execution.
"""
import logging
from ..config import settings
from .control_service import ControlService

logger = logging.getLogger("smart_energy.esp32_control")

DEFAULT_TTL_SECONDS = 60


class ESP32ControlService:
    """Creates PENDING control commands queued for the ESP32 to execute."""

    def __init__(self, db=None):
        self._db = db

    def hardware_available(self) -> bool:
        # Hardware control is configured; availability is now determined by the
        # presence of the control-capable appliance mapped to the ESP32 device.
        return True

    def _control(self, appliance, action: str, source: str = "USER", db=None) -> dict:
        control = ControlService(db or self._db)
        try:
            cmd = control.create_command(
                appliance_id=appliance.id,
                action=action,
                source=source,
            )
        except ValueError as exc:
            return {
                "appliance_id": appliance.id,
                "action": action,
                "status": "FAILED",
                "hardware_control_available": True,
                "message": str(exc),
            }
        if db:
            db.commit()
        return {
            "appliance_id": appliance.id,
            "action": action,
            "status": "PENDING",
            "hardware_control_available": True,
            "message": "Control command queued for ESP32",
            "command_id": cmd.command_id,
            "expires_at": cmd.expires_at,
        }

    def turn_on(self, appliance, source: str = "USER", db=None) -> dict:
        return self._control(appliance, "ON", source, db)

    def turn_off(self, appliance, source: str = "USER", db=None) -> dict:
        return self._control(appliance, "OFF", source, db)

    def get_state(self, appliance) -> dict:
        state = getattr(appliance, "last_confirmed_state", "UNKNOWN")
        return {
            "appliance_id": appliance.id,
            "status": "OK",
            "state": state or "UNKNOWN",
            "hardware_control_available": True,
            "message": "Last confirmed relay state reported by the ESP32.",
        }
