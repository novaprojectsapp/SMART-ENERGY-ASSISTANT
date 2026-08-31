"""
ESP32 control adapter.

This is an abstraction for future relay-actuation hardware.

The current ESP32 firmware only measures (PZEM). It does NOT expose relay
control endpoints yet. Until a control endpoint exists AND the ESP32 returns
an acknowledgement, we MUST NOT claim physical hardware control.

Methods return truthful status:
- HARDWARE_CONTROL_NOT_AVAILABLE when no ESP32 control firmware is configured.
"""
import logging
from ..config import settings

logger = logging.getLogger("smart_energy.esp32_control")

HARDWARE_CONTROL_NOT_AVAILABLE = "HARDWARE_CONTROL_NOT_AVAILABLE"

# Control endpoint is not implemented; keep empty for future firmware.
ESP32_CONTROL_ENDPOINT = getattr(settings, "ESP32_CONTROL_ENDPOINT", "")


class ESP32ControlService:
    """Interface for future relay control. Currently reports hardware unavailable."""

    def hardware_available(self) -> bool:
        # Physical relay control requires firmware + hardware acknowledgement.
        # Until that exists (and is verified with a real acknowledgement),
        # hardware control is NOT available.
        return bool(ESP32_CONTROL_ENDPOINT)

    def turn_on(self, appliance) -> dict:
        return self._not_available(appliance, "ON")

    def turn_off(self, appliance) -> dict:
        return self._not_available(appliance, "OFF")

    def get_state(self, appliance) -> dict:
        return {
            "appliance_id": appliance.id,
            "status": HARDWARE_CONTROL_NOT_AVAILABLE,
            "state": "UNKNOWN",
            "hardware_control_available": False,
            "message": "Physical relay control is not connected. Control hardware and ESP32 firmware required.",
        }

    def _not_available(self, appliance, action: str) -> dict:
        return {
            "appliance_id": appliance.id,
            "action": action,
            "status": HARDWARE_CONTROL_NOT_AVAILABLE,
            "hardware_control_available": False,
            "message": "Hardware control is not connected yet.",
        }
