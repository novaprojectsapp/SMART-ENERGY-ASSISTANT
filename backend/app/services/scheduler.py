"""
Scheduler engine.

Finds due schedules, creates control commands, records execution, and
computes next execution times. Timezone-aware (default Asia/Kolkata).

The scheduler NEVER touches GPIO directly. It produces a ControlCommand
that a hardware adapter (ESP32 Control) would later deliver to a relay.
Until that adapter has hardware, commands remain PENDING/SIMULATED.
"""
import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import Appliance, Schedule, ControlCommand
from .esp32_control import ESP32ControlService, HARDWARE_CONTROL_NOT_AVAILABLE
from ..utils.time import utcnow

logger = logging.getLogger("smart_energy.scheduler")

DEFAULT_TZ = "Asia/Kolkata"
WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# SQLite round-trips datetimes as naive; keep everything in naive-UTC internally
# so aware vs naive comparisons never crash.
def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class SchedulerService:
    def __init__(self, db: Session):
        self.db = db

    def get_zone(self, schedule: Schedule):
        try:
            return ZoneInfo(schedule.timezone or DEFAULT_TZ)
        except Exception:
            return ZoneInfo(DEFAULT_TZ)

    def compute_next_execution(self, schedule: Schedule, now: datetime) -> datetime | None:
        """Return the next execution datetime (UTC) for a schedule given a now DateTime (aware)."""
        if not schedule.enabled:
            return None
        try:
            zone = self.get_zone(schedule)
            now = _naive_utc(now)
            local_now = now.replace(tzinfo=timezone.utc).astimezone(zone)
            t = time.fromisoformat(schedule.start_time)
        except Exception:
            return None

        if schedule.schedule_type == "ONCE":
            candidate = local_now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if candidate <= local_now:
                return None  # one-time occurrence passed
            return _naive_utc(candidate.astimezone(timezone.utc))

        if schedule.schedule_type == "DAILY":
            candidate = local_now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if candidate <= local_now:
                candidate = candidate + timedelta(days=1)
            return _naive_utc(candidate.astimezone(timezone.utc))

        if schedule.schedule_type == "WEEKLY":
            days = self._parse_days(schedule)
            if not days:
                days = list(range(7))
            for offset in range(1, 8):
                day = (local_now.weekday() + offset) % 7
                if day in days:
                    candidate = (local_now + timedelta(days=offset)).replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                    if candidate > local_now:
                        return _naive_utc(candidate.astimezone(timezone.utc))
            return None

        if schedule.schedule_type == "AFTER_DURATION":
            # Requires end_time; treat as daily occurrence at end_time if present,
            # otherwise schedule_type is not fully supported -> None.
            if not schedule.end_time:
                return None
            try:
                te = time.fromisoformat(schedule.end_time)
            except Exception:
                return None
            candidate = local_now.replace(hour=te.hour, minute=te.minute, second=0, microsecond=0)
            if candidate <= local_now:
                candidate = candidate + timedelta(days=1)
            return _naive_utc(candidate.astimezone(timezone.utc))

        return None

    def _parse_days(self, schedule: Schedule) -> list[int]:
        try:
            days = json.loads(schedule.days_of_week or "[]")
            if isinstance(days, list):
                return [d for d in days if isinstance(d, int) and 0 <= d <= 6]
        except Exception:
            pass
        return []

    def refresh_next_execution(self, schedule: Schedule, now: datetime | None = None):
        now = _naive_utc(now) or _naive_utc(utcnow())
        schedule.next_execution_at = self.compute_next_execution(schedule, now)
        return schedule

    def find_due_schedules(self, now: datetime | None = None) -> list[Schedule]:
        """Return enabled schedules whose next_execution_at is <= now and not yet executed."""
        now = _naive_utc(now) or _naive_utc(utcnow())
        return (
            self.db.query(Schedule)
            .filter(
                Schedule.enabled == True,
                Schedule.next_execution_at.isnot(None),
                Schedule.next_execution_at <= now,
            )
            .all()
        )

    def due_for(self, schedule: Schedule, now: datetime) -> bool:
        now = _naive_utc(now)
        return (
            schedule.enabled
            and schedule.next_execution_at is not None
            and schedule.next_execution_at <= now
            and not self._already_executed(schedule, now)
        )

    def _already_executed(self, schedule: Schedule, now: datetime) -> bool:
        now = _naive_utc(now)
        if schedule.last_executed_at is None:
            return False
        # A schedule should not fire twice within the same minute window for the same occurrence.
        window_start = now - timedelta(minutes=1)
        return schedule.last_executed_at >= window_start

    def run_due(self, now: datetime | None = None) -> list[ControlCommand]:
        """Execute all due schedules, creating control commands. Returns created commands."""
        now = _naive_utc(now) or _naive_utc(utcnow())
        commands = []
        due = self.find_due_schedules(now)
        for schedule in due:
            if not self.due_for(schedule, now):
                # Not actually due (dup guard) or disabled; recompute next and continue.
                self.refresh_next_execution(schedule, now)
                continue
            cmd = self.execute_schedule(schedule, now)
            if cmd:
                commands.append(cmd)
        self.db.commit()
        return commands

    def execute_schedule(self, schedule: Schedule, now: datetime) -> ControlCommand | None:
        appliance = self.db.query(Appliance).filter(Appliance.id == schedule.appliance_id).first()
        if not appliance:
            # Orphaned schedule -> disable and skip.
            schedule.enabled = False
            schedule.next_execution_at = None
            logger.warning("Schedule %s references missing appliance; disabled", schedule.id)
            return None

        hardware = ESP32ControlService()
        hw = hardware.turn_on(appliance) if schedule.action == "ON" else hardware.turn_off(appliance)

        if hw.get("status") == HARDWARE_CONTROL_NOT_AVAILABLE:
            status = "PENDING"
            message = "SIMULATED: %s would turn %s. Hardware control is not connected yet." % (
                appliance.name,
                schedule.action,
            )
        else:
            status = "SENT"
            message = "%s command sent to hardware for %s." % (schedule.action, appliance.name)

        cmd = ControlCommand(
            appliance_id=appliance.id,
            action=schedule.action,
            source="SCHEDULE",
            status=status,
            message=message,
        )
        self.db.add(cmd)

        schedule.last_executed_at = now
        self.refresh_next_execution(schedule, now)
        logger.info("Schedule %s executed: %s %s", schedule.id, appliance.name, schedule.action)
        return cmd
