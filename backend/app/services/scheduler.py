"""
Scheduler engine.

Finds due schedules, creates control commands, records execution, and
computes next execution times. Timezone-aware (default Asia/Kolkata).

A schedule can represent either:
  - a single event (action ON or OFF) at start_time, or
  - an ON/OFF pair: ON at start_time and OFF at end_time.

Pair schedules produce TWO independently-tracked events (ON event, OFF event)
for each cycle. Overnight pairs (OFF earlier than ON, e.g. ON 23:00 / OFF 06:00)
interpret the OFF as occurring the following day. Duplicate execution is
prevented: each event fires at most once per cycle.

OVERLAPPING SCHEDULES
---------------------
An automatic OFF event never fires for an appliance while ANOTHER enabled
schedule window still requires the appliance to be ON. Each schedule's event is
still recorded (so its own cycle advances), but the OFF command is suppressed.
This prevents one schedule ending (e.g. 22:00) from switching the relay off
while a second schedule (e.g. until 23:00) still requires power.

The scheduler NEVER touches GPIO directly. It produces a PENDING ControlCommand
that the ESP32 polls and acknowledges. Commands are only marked EXECUTED after
a real ESP32 acknowledgement.
"""
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import Appliance, Schedule, ControlCommand
from .control_service import ControlService
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

    def _on_time(self, schedule: Schedule) -> time:
        return time.fromisoformat(schedule.start_time)

    def _off_time(self, schedule: Schedule) -> time | None:
        if not schedule.end_time:
            return None
        return time.fromisoformat(schedule.end_time)

    def _has_off(self, schedule: Schedule) -> bool:
        return bool(schedule.end_time)

    def _parse_days(self, schedule: Schedule) -> list[int]:
        try:
            days = json.loads(schedule.days_of_week or "[]")
            if isinstance(days, list):
                return [d for d in days if isinstance(d, int) and 0 <= d <= 6]
        except Exception:
            pass
        return []

    def _day_allowed(self, schedule: Schedule, d: date) -> bool:
        if schedule.schedule_type == "WEEKLY":
            return d.weekday() in self._parse_days(schedule)
        if schedule.schedule_type == "ONCE":
            return True
        return True  # DAILY / AFTER_DURATION

    # ------------------------------------------------------------------
    # Cycle / event computation (times are naive-UTC datetimes)
    # ------------------------------------------------------------------
    def _cycle_local(self, schedule: Schedule, day: date) -> tuple[datetime, datetime | None]:
        """Return (on_datetime_local, off_datetime_local) for the cycle anchored
        at local date `day`."""
        zone = self.get_zone(schedule)
        on_t = self._on_time(schedule)
        on_local = datetime.combine(day, on_t)
        on_utc = _naive_utc(on_local.astimezone(zone).astimezone(timezone.utc))

        off_t = self._off_time(schedule)
        if off_t is None:
            return on_utc, None
        # Overnight: OFF time earlier than (or equal) to ON time -> next day.
        off_day = day + timedelta(days=1) if off_t <= on_t else day
        off_local = datetime.combine(off_day, off_t)
        off_utc = _naive_utc(off_local.astimezone(zone).astimezone(timezone.utc))
        return on_utc, off_utc

    def _next_anchor_day(self, schedule: Schedule, local_today: date) -> date | None:
        """First allowed day on-or-after local_today, or None for a spent ONCE."""
        if schedule.schedule_type == "ONCE":
            # ONCE anchors to today (its single scheduled date). If today's cycle
            # is fully in the past the caller advances; there is no 'next day'.
            return local_today
        for offset in range(0, 8):
            d = local_today + timedelta(days=offset)
            if self._day_allowed(schedule, d):
                return d
        return None

    def next_cycle(self, schedule: Schedule, now: datetime) -> tuple[datetime, datetime | None] | None:
        """Return the next pending cycle (on_utc, off_utc) after `now`, or None.

        For ONCE schedules that have fully passed, returns None. For DAILY/WEEKLY
        the cycle is advanced to the first cycle with a pending event."""
        if not schedule.enabled:
            return None
        zone = self.get_zone(schedule)
        local_now = _naive_utc(now).replace(tzinfo=timezone.utc).astimezone(zone)
        today = local_now.date()

        for offset in range(0, 31):
            anchor = self._next_anchor_day(schedule, today + timedelta(days=offset))
            if anchor is None:
                return None
            on_utc, off_utc = self._cycle_local(schedule, anchor)
            # Determine if this cycle has a pending event after now.
            pending_on = on_utc is not None and on_utc > _naive_utc(now) if on_utc else False
            pending_off = off_utc is not None and off_utc > _naive_utc(now) if off_utc else False
            if pending_on or pending_off:
                return on_utc, off_utc
            # This cycle is fully in the past (or OFF is the only pending and it's past).
            if schedule.schedule_type == "ONCE":
                # One-time schedule fully executed -> no more cycles.
                return None
        return None

    def next_event(self, schedule: Schedule, now: datetime) -> tuple[datetime, str] | None:
        """Return (next_event_utc, action) where action is 'ON' or 'OFF'."""
        cycle = self.next_cycle(schedule, now)
        if not cycle:
            return None
        on_utc, off_utc = cycle
        now_u = _naive_utc(now)
        if on_utc and on_utc > now_u:
            return on_utc, "ON"
        if off_utc and off_utc > now_u:
            return off_utc, "OFF"
        return None

    def each_cycle(self, schedule: Schedule, now: datetime):
        """Yield successive (anchor_day, on_utc, off_utc) cycles after `now`."""
        now_u = _naive_utc(now)
        zone = self.get_zone(schedule)
        if not schedule.enabled:
            return
        local_now = now_u.replace(tzinfo=timezone.utc).astimezone(zone)
        today = local_now.date()
        for offset in range(0, 61):
            anchor = self._next_anchor_day(schedule, today + timedelta(days=offset))
            if anchor is None:
                break
            yield anchor, *self._cycle_local(schedule, anchor)

    def next_on_at(self, schedule: Schedule, now: datetime) -> datetime | None:
        """Next future ON event (naive UTC), or None."""
        now_u = _naive_utc(now)
        for _anchor, on_utc, _off in self.each_cycle(schedule, now):
            if on_utc and on_utc > now_u:
                return on_utc
        return None

    def next_off_at(self, schedule: Schedule, now: datetime) -> datetime | None:
        """Next future OFF event (naive UTC), or None."""
        if not self._has_off(schedule):
            return None
        now_u = _naive_utc(now)
        for _anchor, _on, off_utc in self.each_cycle(schedule, now):
            if off_utc and off_utc > now_u:
                return off_utc
        return None

    # ------------------------------------------------------------------
    # Desired-state evaluation (overlapping-schedule protection)
    # ------------------------------------------------------------------
    def _window_covers(self, schedule: Schedule, now: datetime) -> bool:
        """True if `now` (naive UTC) is inside an ON/OFF window of this schedule.

        Only ON/OFF pair schedules define a continuous window. Single-event
        schedules do not contribute to the overlap check. Overnight windows
        (OFF < ON) span midnight and are handled by checking the previous
        day's anchor too."""
        if not self._has_off(schedule):
            return False
        now_u = _naive_utc(now)
        if now_u is None:
            return False
        zone = self.get_zone(schedule)
        local_now = now_u.replace(tzinfo=timezone.utc).astimezone(zone)
        candidates = {local_now.date(), local_now.date() - timedelta(days=1)}
        for day in candidates:
            on_utc, off_utc = self._cycle_local(schedule, day)
            if on_utc is None or off_utc is None:
                continue
            on_u = _naive_utc(on_utc)
            off_u = _naive_utc(off_utc)
            # A single cycle always ends the same day it starts, or next for
            # overnight, so on < off for a valid pair within one anchor day.
            if on_u <= now_u < off_u:
                return True
        return False

    def appliance_requires_on(self, appliance_id: str, now: datetime) -> bool:
        """True if ANY enabled schedule currently requires this appliance ON.

        Used to suppress an automatic OFF event when another schedule window
        still overlaps today's schedule."""
        now_u = _naive_utc(now) or _naive_utc(utcnow())
        for schedule in self.db.query(Schedule).filter(Schedule.appliance_id == appliance_id).all():
            if not schedule.enabled:
                continue
            if schedule.schedule_type == "WEEKLY":
                local = _naive_utc(now_u).replace(tzinfo=timezone.utc).astimezone(self.get_zone(schedule))
                if local.weekday() not in self._parse_days(schedule):
                    continue
            if schedule.schedule_type == "ONCE":
                # A ONCE schedule only requires ON on its own cycle day; once
                # both events are processed (next_execution_at cleared) it no
                # longer contributes to the desired state.
                if schedule.next_execution_at is None:
                    continue
            if self._window_covers(schedule, now_u):
                return True
        return False

    def desired_state_for(self, appliance: Appliance, now: datetime) -> str:
        """Desired ON/OFF state for an appliance at `now` according to all
        enabled schedules."""
        return "ON" if self.appliance_requires_on(appliance.id, now) else "OFF"

    def refresh_next_execution(self, schedule: Schedule, now: datetime | None = None):
        """Set next_execution_at to the next pending event (ON or OFF), or None."""
        now = _naive_utc(now) or _naive_utc(utcnow())
        event = self.next_event(schedule, now)
        schedule.next_execution_at = event[0] if event else None
        return schedule

    # ------------------------------------------------------------------
    # Due detection (uses the existing next_execution_at machinery)
    # ------------------------------------------------------------------
    def find_due_schedules(self, now: datetime | None = None) -> list[Schedule]:
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
        # A schedule should not fire twice within the same minute window for the same event.
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

        now = _naive_utc(now)
        # Determine which event is firing now: the stored next_execution_at tells us.
        action = self._event_action_at(schedule, now)

        if action not in ("ON", "OFF"):
            action = schedule.action

        # Overlap protection: never emit an automatic OFF while another enabled
        # schedule window still requires this appliance to be ON. The event is
        # still recorded (cycle advances) but no OFF command is created.
        if action == "OFF" and self.appliance_requires_on(appliance.id, now):
            schedule.last_executed_at = now
            self.refresh_next_execution(schedule, now)
            logger.info(
                "Schedule %s OFF suppressed for %s: another schedule window still requires ON",
                schedule.id,
                appliance.name,
            )
            return None

        control = ControlService(self.db)
        try:
            cmd = control.create_command(
                appliance_id=appliance.id,
                action=action,
                source="SCHEDULE",
            )
        except ValueError as exc:
            logger.warning("Schedule %s: %s", schedule.id, exc)
            schedule.last_executed_at = now
            self.refresh_next_execution(schedule, now)
            return None

        self.db.add(cmd)

        schedule.last_executed_at = now
        self.refresh_next_execution(schedule, now)
        logger.info("Schedule %s executed: %s %s", schedule.id, appliance.name, action)
        return cmd

    def _event_action_at(self, schedule: Schedule, now: datetime) -> str:
        """Return the schedule event ('ON' or 'OFF') that was pending at `now`.

        Determines which event fired by matching next_execution_at against the
        cycle's ON/OFF times. Anchors are checked across neighbouring days so
        overnight pairs (OFF on the day after ON) resolve correctly.
        """
        pending = schedule.next_execution_at
        if pending is None:
            return schedule.action
        pending_u = _naive_utc(pending)
        zone = self.get_zone(schedule)
        local_day = pending_u.replace(tzinfo=timezone.utc).astimezone(zone).date()
        for offset in range(-1, 2):
            day = local_day + timedelta(days=offset)
            on_utc, off_utc = self._cycle_local(schedule, day)
            if on_utc and _naive_utc(on_utc) == pending_u:
                return "ON"
            if off_utc and _naive_utc(off_utc) == pending_u:
                return "OFF"
        if not self._has_off(schedule):
            return schedule.action
        return "ON"
