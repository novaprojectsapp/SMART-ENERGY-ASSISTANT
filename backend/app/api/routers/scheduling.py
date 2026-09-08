import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json
from ...database import get_db
from ...models import Appliance, Schedule, ControlCommand, Device
from ...schemas.schemas import (
    ApplianceCreate,
    ApplianceUpdate,
    ApplianceResponse,
    ApplianceControlResponse,
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    ControlCommandCreate,
    ControlCommandResponse,
    PendingCommandResponse,
    CommandAckRequest,
    CommandAckResponse,
)
from ...services.scheduler import SchedulerService
from ...services.control_service import ControlService
from ...services.esp32_control import ESP32ControlService
from ...utils.time import utcnow, naive_utc

router = APIRouter(prefix="/api/v1", tags=["scheduling"])

logger = logging.getLogger("smart_energy.api.scheduling")


# ---------------------------------------------------------------------------
# Appliances
# ---------------------------------------------------------------------------
@router.get("/appliances", response_model=list[ApplianceResponse])
def list_appliances(db: Session = Depends(get_db)):
    return db.query(Appliance).order_by(Appliance.created_at.asc()).all()


@router.post("/appliances", response_model=ApplianceResponse, status_code=201)
def create_appliance(appliance_in: ApplianceCreate, db: Session = Depends(get_db)):
    if appliance_in.device_id:
        device = db.query(Device).filter(Device.id == appliance_in.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{appliance_in.device_id}' not found")
    appliance = Appliance(
        device_id=appliance_in.device_id,
        name=appliance_in.name,
        type=appliance_in.type,
        channel=appliance_in.channel,
        control_capable=appliance_in.control_capable,
    )
    db.add(appliance)
    db.commit()
    db.refresh(appliance)
    return appliance


@router.get("/appliances/{appliance_id}", response_model=ApplianceResponse)
def get_appliance(appliance_id: str, db: Session = Depends(get_db)):
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    return appliance


@router.put("/appliances/{appliance_id}", response_model=ApplianceResponse)
def update_appliance(appliance_id: str, appliance_in: ApplianceUpdate, db: Session = Depends(get_db)):
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    data = appliance_in.model_dump(exclude_unset=True)
    if "device_id" in data and data["device_id"]:
        device = db.query(Device).filter(Device.id == data["device_id"]).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device '{data['device_id']}' not found")
    for key, value in data.items():
        if value is not None:
            setattr(appliance, key, value)
    db.commit()
    db.refresh(appliance)
    return appliance


@router.delete("/appliances/{appliance_id}")
def delete_appliance(appliance_id: str, db: Session = Depends(get_db)):
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    # Delete associated schedules to avoid orphans.
    db.query(Schedule).filter(Schedule.appliance_id == appliance_id).delete()
    db.delete(appliance)
    db.commit()
    return {"status": "DELETED", "id": appliance_id}


# ---------------------------------------------------------------------------
# Control (manual)
# ---------------------------------------------------------------------------
@router.post("/appliances/{appliance_id}/control", status_code=201)
def control_appliance(appliance_id: str, cmd_in: ControlCommandCreate, db: Session = Depends(get_db)):
    if cmd_in.appliance_id != appliance_id:
        raise HTTPException(status_code=400, detail="appliance_id mismatch")
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    if not appliance.control_capable:
        raise HTTPException(status_code=400, detail="Appliance is not control capable")

    hardware = ESP32ControlService(db=db)
    hw = hardware.turn_on(appliance, source=cmd_in.source, db=db) if cmd_in.action == "ON" else hardware.turn_off(appliance, source=cmd_in.source, db=db)

    if hw.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail=hw.get("message", "Control command failed"))

    db.refresh(appliance)
    return ApplianceControlResponse(
        status="PENDING",
        message="Control command queued for ESP32",
        hardware_control_available=True,
        command_id=hw.get("command_id"),
        appliance=appliance.name,
        action=cmd_in.action,
        source=cmd_in.source,
        expires_at=hw.get("expires_at"),
    )


# ---------------------------------------------------------------------------
# ESP32 command polling + acknowledgement
# ---------------------------------------------------------------------------
@router.get("/devices/{device_id}/control/pending", response_model=PendingCommandResponse)
def get_pending_control(device_id: str, db: Session = Depends(get_db)):
    """Called by the ESP32 every ~1s. Returns the next PENDING or still-
    unacknowledged DISPATCHED (non-expired) command for this device, or null.

    A DISPATCHED command is re-returned on purpose: if the ESP32's ACK was lost,
    it can re-poll the same command, re-execute idempotently, and re-ACK it.
    Expired commands are marked EXPIRED and never returned as active work."""
    control = ControlService(db)
    device = control.resolve_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    logger.info("[CONTROL] Poll received | device=%s", device_id)

    now = naive_utc(utcnow())
    # Expire any stale PENDING/DISPATCHED commands for this device before
    # dispatching. Only the ESP32 ACK may produce EXECUTED; an expired command
    # must never be executed or delivered again.
    stale = (
        db.query(ControlCommand)
        .filter(
            ControlCommand.device_id == device_id,
            ControlCommand.status.in_(["PENDING", "DISPATCHED"]),
            ControlCommand.expires_at.isnot(None),
            ControlCommand.expires_at <= now,
        )
        .all()
    )
    for c in stale:
        c.status = "EXPIRED"
        c.message = "Command expired before the ESP32 executed it."
        logger.info(
            "[CONTROL] Expiring command | command_id=%s action=%s channel=%s created_at=%s expires_at=%s now=%s",
            c.command_id, c.action, c.channel, c.created_at, c.expires_at, now,
        )
    if stale:
        db.commit()

    cmd = control.pending_command(device_id)
    if not cmd:
        db.commit()
        logger.info("[CONTROL] Pending commands found: 0")
        return PendingCommandResponse(command=None)

    control.dispatch_or_expire(cmd)
    db.commit()

    if cmd.status == "EXPIRED":
        # Defensive: an expired command must never be delivered as work.
        logger.info("[CONTROL] Returning command: none (expired)")
        return PendingCommandResponse(command=None)

    logger.info(
        "[CONTROL] Returning command | command_id=%s device=%s channel=%s action=%s status=%s",
        cmd.command_id, cmd.device_id, cmd.channel, cmd.action, cmd.status,
    )
    # Compact wire contract: the ESP32 parses this into a fixed
    # StaticJsonDocument<512>, so no id/appliance_id/timestamps here.
    return PendingCommandResponse(
        has_command=True,
        command={
            "command_id": cmd.command_id,
            "device_id": cmd.device_id,
            "channel": cmd.channel,
            "action": cmd.action,
        },
    )


@router.post("/devices/{device_id}/control/{command_id}/ack", response_model=CommandAckResponse)
def ack_control(device_id: str, command_id: str, ack: CommandAckRequest, db: Session = Depends(get_db)):
    control = ControlService(db)
    device = control.resolve_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    # Enforce ownership BEFORE mutating: a different ESP32 must never be able to
    # acknowledge (and thereby confirm) another device's command.
    cmd = (
        db.query(ControlCommand)
        .filter((ControlCommand.command_id == command_id) | (ControlCommand.id == command_id))
        .first()
    )
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    if cmd.device_id and cmd.device_id != device_id:
        raise HTTPException(status_code=403, detail="Command belongs to a different device")

    acknowledged = control.acknowledge(
        command_id,
        success=ack.success,
        relay_state=ack.relay_state,
        message=ack.message,
    )
    if not acknowledged:
        raise HTTPException(status_code=404, detail="Command not found")

    db.commit()
    return CommandAckResponse(
        status=acknowledged.status,
        command_id=acknowledged.command_id,
        acknowledged=True,
    )


@router.get("/devices/{device_id}/control/status")
def device_control_status(device_id: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    app = (
        db.query(Appliance)
        .filter(Appliance.device_id == device_id, Appliance.control_capable == True)
        .order_by(Appliance.created_at.asc())
        .first()
    )
    return {
        "device_id": device_id,
        "hardware_control_available": True,
        "device_online": device.last_seen is not None,
        "last_seen": device.last_seen.isoformat() + "Z" if device.last_seen else None,
        "appliances": [
            {
                "id": a.id,
                "name": a.name,
                "channel": a.channel,
                "confirmed_state": a.last_confirmed_state or "UNKNOWN",
                "last_control_at": a.last_control_at.isoformat() + "Z" if a.last_control_at else None,
            }
            for a in db.query(Appliance)
            .filter(Appliance.device_id == device_id, Appliance.control_capable == True)
            .order_by(Appliance.created_at.asc())
            .all()
        ],
    }


@router.get("/control-commands", response_model=list[ControlCommandResponse])
def list_control_commands(limit: int = 50, db: Session = Depends(get_db)):
    commands = (
        db.query(ControlCommand)
        .order_by(ControlCommand.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ControlCommandResponse(
            id=c.id,
            command_id=c.command_id,
            device_id=c.device_id,
            appliance_id=c.appliance_id,
            channel=c.channel,
            action=c.action,
            source=c.source,
            status=c.status,
            message=c.message,
            hardware_control_available=True,
            confirmed_relay_state=c.confirmed_relay_state or "UNKNOWN",
            created_at=c.created_at,
            expires_at=c.expires_at,
            acknowledged_at=c.acknowledged_at,
            executed_at=c.executed_at,
        )
        for c in commands
    ]


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
@router.get("/schedules", response_model=list[ScheduleResponse])
def list_schedules(db: Session = Depends(get_db)):
    scheduler = SchedulerService(db)
    schedules = db.query(Schedule).order_by(Schedule.created_at.asc()).all()
    result = []
    for s in schedules:
        scheduler.refresh_next_execution(s)
        result.append(_to_schedule_response(s, scheduler))
    db.commit()
    return result


@router.post("/schedules", response_model=ScheduleResponse, status_code=201)
def create_schedule(schedule_in: ScheduleCreate, db: Session = Depends(get_db)):
    _validate_schedule(
        schedule_in.appliance_id,
        schedule_in.action,
        schedule_in.start_time,
        schedule_in.end_time,
        schedule_in.schedule_type,
        schedule_in.days_of_week,
        db,
    )
    schedule = Schedule(
        appliance_id=schedule_in.appliance_id,
        action=schedule_in.action,
        schedule_type=schedule_in.schedule_type,
        start_time=schedule_in.start_time,
        end_time=schedule_in.end_time,
        days_of_week=json.dumps(schedule_in.days_of_week),
        enabled=schedule_in.enabled,
        timezone=schedule_in.timezone,
    )
    db.add(schedule)
    db.flush()
    scheduler = SchedulerService(db)
    scheduler.refresh_next_execution(schedule)
    db.commit()
    db.refresh(schedule)
    return _to_schedule_response(schedule, SchedulerService(db))


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler = SchedulerService(db)
    scheduler.refresh_next_execution(schedule)
    db.commit()
    return _to_schedule_response(schedule, SchedulerService(db))


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(schedule_id: str, schedule_in: ScheduleUpdate, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    data = schedule_in.model_dump(exclude_unset=True)

    if "days_of_week" in data and data["days_of_week"] is not None:
        days = data.pop("days_of_week")
        schedule.days_of_week = json.dumps(days)

    # on_time/off_time are API aliases for start_time/end_time; drop the aliases
    # so they aren't set as unmapped attributes on the model.
    data.pop("on_time", None)
    data.pop("off_time", None)

    if "appliance_id" in data and data["appliance_id"]:
        if not db.query(Appliance).filter(Appliance.id == data["appliance_id"]).first():
            raise HTTPException(status_code=404, detail="Appliance not found")

    for key, value in data.items():
        if value is not None:
            setattr(schedule, key, value)

    # Revalidate final state
    _validate_schedule(
        schedule.appliance_id,
        schedule.action,
        schedule.start_time,
        schedule.end_time,
        schedule.schedule_type,
        json.loads(schedule.days_of_week or "[]"),
        db,
    )

    scheduler = SchedulerService(db)
    scheduler.refresh_next_execution(schedule)
    db.commit()
    db.refresh(schedule)
    return _to_schedule_response(schedule, SchedulerService(db))


@router.post("/schedules/{schedule_id}/enable", response_model=ScheduleResponse)
def enable_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.enabled = True
    scheduler = SchedulerService(db)
    scheduler.refresh_next_execution(schedule)
    db.commit()
    db.refresh(schedule)
    return _to_schedule_response(schedule, SchedulerService(db))


@router.post("/schedules/{schedule_id}/disable", response_model=ScheduleResponse)
def disable_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.enabled = False
    schedule.next_execution_at = None
    db.commit()
    db.refresh(schedule)
    return _to_schedule_response(schedule, SchedulerService(db))


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
    return {"status": "DELETED", "id": schedule_id}


def _validate_schedule(appliance_id, action, start_time, end_time, schedule_type="DAILY", days_of_week=None, db=None):
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    if action not in ("ON", "OFF"):
        raise HTTPException(status_code=422, detail="Invalid action: must be ON or OFF")
    if not start_time:
        raise HTTPException(status_code=422, detail="start_time is required")
    # Same-day equality check: an ON and OFF at the exact same instant is rejected.
    # Overnight pairs (OFF earlier than ON, e.g. ON 23:00 / OFF 06:00) are allowed.
    if end_time and end_time == start_time:
        raise HTTPException(status_code=422, detail="ON time and OFF time cannot be the same.")
    if schedule_type == "WEEKLY" and not days_of_week:
        raise HTTPException(
            status_code=422,
            detail="Weekly schedules require at least one day of the week.",
        )
    if schedule_type == "ONCE" and False:
        # ONCE schedules currently anchor to the current day; no date field is
        # persisted, so a date-specific check is not applicable.
        pass
    if not appliance.control_capable:
        raise HTTPException(status_code=400, detail="Appliance is not control capable")


def _to_schedule_response(schedule, scheduler):
    """Build a ScheduleResponse including ON/OFF times and next ON/OFF datetimes."""
    now = utcnow()
    next_on = scheduler.next_on_at(schedule, now)
    next_off = scheduler.next_off_at(schedule, now)
    return ScheduleResponse(
        id=schedule.id,
        appliance_id=schedule.appliance_id,
        action=schedule.action,
        schedule_type=schedule.schedule_type,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        days_of_week=json.loads(schedule.days_of_week or "[]")
        if isinstance(schedule.days_of_week, str)
        else (schedule.days_of_week or []),
        enabled=schedule.enabled,
        timezone=schedule.timezone,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        last_executed_at=schedule.last_executed_at,
        next_execution_at=schedule.next_execution_at,
        on_time=schedule.start_time,
        off_time=schedule.end_time,
        next_on_at=next_on,
        next_off_at=next_off,
    )


# ---------------------------------------------------------------------------
# Scheduler run (manual trigger; safe, no GPIO)
# ---------------------------------------------------------------------------
class SchedulerRunResponse(BaseModel):
    status: str
    control_commands_executed: int
    commands: list[dict]


@router.post("/scheduler/run", response_model=SchedulerRunResponse)
def run_scheduler(db: Session = Depends(get_db)):
    scheduler = SchedulerService(db)
    commands = scheduler.run_due()
    return SchedulerRunResponse(
        status="OK",
        control_commands_executed=len(commands),
        commands=[
            {
                "appliance_id": c.appliance_id,
                "action": c.action,
                "source": c.source,
                "status": c.status,
                "message": c.message,
            }
            for c in commands
        ],
    )
