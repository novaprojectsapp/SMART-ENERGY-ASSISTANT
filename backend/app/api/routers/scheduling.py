from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json
from ...database import get_db
from ...models import Appliance, Schedule, ControlCommand, Device
from ...schemas.schemas import (
    ApplianceCreate,
    ApplianceUpdate,
    ApplianceResponse,
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    ControlCommandCreate,
    ControlCommandResponse,
)
from ...services.scheduler import SchedulerService
from ...services.esp32_control import ESP32ControlService, HARDWARE_CONTROL_NOT_AVAILABLE
from ...utils.time import utcnow

router = APIRouter(prefix="/api/v1", tags=["scheduling"])


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
@router.post("/appliances/{appliance_id}/control", response_model=ControlCommandResponse, status_code=201)
def control_appliance(appliance_id: str, cmd_in: ControlCommandCreate, db: Session = Depends(get_db)):
    if cmd_in.appliance_id != appliance_id:
        raise HTTPException(status_code=400, detail="appliance_id mismatch")
    appliance = db.query(Appliance).filter(Appliance.id == appliance_id).first()
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    if not appliance.control_capable:
        raise HTTPException(status_code=400, detail="Appliance is not control capable")

    hardware = ESP32ControlService()
    hw = hardware.turn_on(appliance) if cmd_in.action == "ON" else hardware.turn_off(appliance)

    if hw.get("status") == HARDWARE_CONTROL_NOT_AVAILABLE:
        status = "SIMULATED"
        message = "SIMULATED: %s would turn %s. Hardware control is not connected yet." % (
            appliance.name, cmd_in.action,
        )
    else:
        status = "PENDING"
        message = "Control command created. Sending to hardware hardware control."

    command = ControlCommand(
        appliance_id=appliance.id,
        action=cmd_in.action,
        source=cmd_in.source,
        status=status,
        message=message,
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return ControlCommandResponse(
        id=command.id,
        appliance_id=command.appliance_id,
        action=command.action,
        source=command.source,
        status=command.status,
        message=command.message,
        hardware_control_available=False,
        created_at=command.created_at,
    )


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
            appliance_id=c.appliance_id,
            action=c.action,
            source=c.source,
            status=c.status,
            message=c.message,
            hardware_control_available=False,
            created_at=c.created_at,
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
