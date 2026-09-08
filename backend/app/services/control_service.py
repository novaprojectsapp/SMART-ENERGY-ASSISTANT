"""
Control command lifecycle service.

The backend NEVER actuates GPIO directly. Instead it persists a ControlCommand
in the PENDING state and exposes a polling endpoint the ESP32 firmware calls
every ~1s. The ESP32 performs the physical relay action and acknowledges the
result; only then is a command marked EXECUTED (or FAILED). This guarantees we
never claim hardware success before a real acknowledgement.

Lifecycle: PENDING -> DISPATCHED -> EXECUTED | FAILED | EXPIRED
"""
import logging
import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Appliance, ControlCommand, Device
from ..utils.time import utcnow, naive_utc
from ..utils.capabilities import normalize_capabilities

logger = logging.getLogger("smart_energy.control")


DEFAULT_COMMAND_TTL_SECONDS = 60
MAX_ATTEMPTS = 3


def new_command_id() -> str:
    return str(uuid.uuid4())


def default_ttl_seconds() -> int:
    try:
        return int(os.environ.get("SEA_CONTROL_TTL_SECONDS", DEFAULT_COMMAND_TTL_SECONDS))
    except Exception:
        return DEFAULT_COMMAND_TTL_SECONDS


class ControlService:
    """Creates and resolves control commands with reliable lifecycle handling."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ create
    def create_command(
        self,
        appliance_id: str,
        action: str,
        source: str = "USER",
        ttl_seconds: int | None = None,
    ) -> ControlCommand:
        """Validate the appliance then create a PENDING command.

        Returns the persisted ControlCommand or raises ValueError/raises.
        Caller is responsible for committing when appropriate.
        """
        appliance = self.db.query(Appliance).filter(Appliance.id == appliance_id).first()
        if not appliance:
            raise ValueError("Appliance not found")
        if not appliance.control_capable:
            raise ValueError(f"Appliance '{appliance.name}' is not control capable")
        if action not in ("ON", "OFF"):
            raise ValueError("Invalid action: must be ON or OFF")
        if not appliance.device_id:
            # A command with an empty/None device can never be polled by any
            # ESP32. Reject it instead of silently queueing dead work.
            raise ValueError(f"Appliance '{appliance.name}' has no ESP32 device mapped")

        caps = self.device_capabilities(appliance.device_id)
        if not caps.get("relay_control"):
            # The device itself declared it has no relay hardware. Queuing a
            # command would be a lie: nothing physical would ever actuate.
            raise ValueError(
                f"Appliance '{appliance.name}' is mapped to a device without relay control capability"
            )

        ttl = ttl_seconds if ttl_seconds is not None else default_ttl_seconds()
        now = utcnow()

        command = ControlCommand(
            command_id=new_command_id(),
            device_id=appliance.device_id,
            appliance_id=appliance.id,
            channel=appliance.channel or 1,
            action=action,
            source=source,
            status="PENDING",
            message="Control command queued for ESP32",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            attempt_count=0,
            confirmed_relay_state="UNKNOWN",
        )
        self.db.add(command)
        logger.info(
            "[CONTROL] Command created | command_id=%s device=%s appliance=%s action=%s channel=%s source=%s expires_at=%s",
            command.command_id, command.device_id, command.appliance_id,
            command.action, command.channel, command.source, command.expires_at,
        )
        return command

    def device_capabilities(self, device_id: str) -> dict:
        """Return the device's normalized capabilities (relay_control, channels,
        telemetry). Defaults describe the ESP32-S3 hardware when unspecified."""
        device = self.db.query(Device).filter(Device.id == device_id).first()
        return normalize_capabilities(device.capabilities if device else None)

    # ------------------------------------------------------------------ queue
    def resolve_device(self, device_id: str) -> Device | None:
        return self.db.query(Device).filter(Device.id == device_id).first()

    def pending_command(self, device_id: str) -> ControlCommand | None:
        """Return the next PENDING or DISPATCHED (still-unacknowledged,
        non-expired) command for this device, or None.

        DISPATCHED commands are re-returned deliberately so an ESP32 that lost
        its ACK can re-poll the same command and re-acknowledge it — a command
        must never get permanently stuck because an ACK failed. Safe to call
        every second (idempotent, no state change)."""
        now = naive_utc(utcnow())
        return (
            self.db.query(ControlCommand)
            .filter(
                ControlCommand.device_id == device_id,
                ControlCommand.status.in_(["PENDING", "DISPATCHED"]),
                ControlCommand.expires_at.isnot(None),
                ControlCommand.expires_at > now,
            )
            .order_by(ControlCommand.created_at.asc())
            .first()
        )

    def dispatch_or_expire(self, command: ControlCommand) -> ControlCommand:
        """Mark commands that have expired as EXPIRED; otherwise mark a PENDING
        command DISPATCHED (increments attempt_count). Applies to both PENDING
        and DISPATCHED states so an expired dispatched command is also handled."""
        now = naive_utc(utcnow())
        if command.expires_at is not None and naive_utc(command.expires_at) <= now:
            command.status = "EXPIRED"
            command.message = "Command expired before the ESP32 executed it."
            return command
        if command.status == "PENDING":
            command.status = "DISPATCHED"
            command.dispatched_at = utcnow()
            command.attempt_count = (command.attempt_count or 0) + 1
        return command

    # ------------------------------------------------------------------- ack
    def acknowledge(
        self,
        command_id: str,
        success: bool,
        relay_state: str = "UNKNOWN",
        message: str = "",
    ) -> ControlCommand | None:
        """Apply an ESP32 acknowledgement. Returns the command or None.

        Ack is idempotent: an already-EXECUTED/FAILED command may be re-acked
        without corrupting state or re-running the relay.
        """
        # Resolve by the public command_id first, then by internal id.
        command = (
            self.db.query(ControlCommand)
            .filter(ControlCommand.command_id == command_id)
            .first()
        )
        if not command:
            command = (
                self.db.query(ControlCommand)
                .filter(ControlCommand.id == command_id)
                .first()
            )
        if not command:
            return None

        now = utcnow()
        logger.info(
            "[CONTROL] ACK received | command_id=%s device=%s action=%s success=%s relay_state=%s ack_msg=%s",
            command_id, command.device_id, command.action, success,
            relay_state if relay_state != "UNKNOWN" else "UNKNOWN", message,
        )
        if success:
            command.status = "EXECUTED"
            command.message = message or (
                f"ESP32 confirmed relay switched {relay_state if relay_state != 'UNKNOWN' else command.action}."
            )
            command.confirmed_relay_state = relay_state if relay_state != "UNKNOWN" else command.action
            command.executed_at = now
            command.acknowledged_at = now

            appliance = self.db.query(Appliance).filter(Appliance.id == command.appliance_id).first()
            if appliance:
                appliance.last_confirmed_state = command.confirmed_relay_state
                appliance.last_control_at = now
        else:
            command.status = "FAILED"
            command.message = message or "ESP32 reported relay execution failure."
            command.confirmed_relay_state = relay_state or "UNKNOWN"
            command.acknowledged_at = now
        return command

    # ------------------------------------------------------------------ list
    def to_dict(self, command: ControlCommand) -> dict:
        return {
            "id": command.id,
            "command_id": command.command_id,
            "device_id": command.device_id,
            "appliance_id": command.appliance_id,
            "channel": command.channel,
            "action": command.action,
            "source": command.source,
            "status": command.status,
            "message": command.message,
            "confirmed_relay_state": command.confirmed_relay_state,
            "created_at": _iso(command.created_at),
            "expires_at": _iso(command.expires_at),
            "dispatched_at": _iso(command.dispatched_at),
            "acknowledged_at": _iso(command.acknowledged_at),
            "executed_at": _iso(command.executed_at),
            "attempt_count": command.attempt_count,
        }


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")
