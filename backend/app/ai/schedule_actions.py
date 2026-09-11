"""
High-level scheduling actions used by the voice/AI handler.

Encapsulates appliance resolution (fuzzy matching), schedule CRUD, manual
control, listing, and a lightweight in-process multi-turn draft store so the
assistant can ask clarifying questions and complete a schedule across turns.

Management operations (create / update / enable / disable / delete) return a
(result_message, pending_state) tuple. pending_state is a dict describing the
in-progress operation (e.g. {"op": "disable", "ref": "bulb"}) so the voice
handler can keep a multi-turn conversation alive; None means the operation
terminated (success or fatal error).
"""
import re
import time
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Appliance, Schedule, ControlCommand
from ..schemas.schemas import ScheduleCreate, ControlCommandCreate
from ..services.scheduler import SchedulerService
from ..services.control_service import ControlService
from ..utils.time import utcnow
from .data_access import get_latest_reading

logger = logging.getLogger("smart_energy.ai.schedule")

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DRAFT_TTL_SECONDS = 900

# In-process multi-turn draft store. Key = session (device_id or 'default').
_pending_drafts: dict[str, dict] = {}


class ScheduleActions:
    def __init__(self, db: Session, device_id: str | None = None):
        self.db = db
        self.device_id = device_id

    # ------------------------------------------------------------------ utils
    def _norm(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().strip())

    def resolve_appliance(self, ref: str | None) -> tuple[Appliance | None, str | None]:
        """Resolve an appliance reference to a single match.

        Returns (appliance, error_message). If ambiguous, error_message describes it.
        """
        if not ref:
            return None, "Which appliance do you mean? Please name it (e.g. 'bulb 1')."

        query = self.db.query(Appliance)
        if self.device_id:
            query = query.filter(Appliance.device_id == self.device_id)
        appliances = query.all()
        if not appliances:
            return None, "You have not registered any appliances yet. Add one from the Smart Scheduler page first."

        refn = self._norm(ref)
        direct = [a for a in appliances if self._norm(a.name) == refn]
        if len(direct) == 1:
            return direct[0], None
        if len(direct) > 1:
            names = ", ".join(a.name for a in direct)
            return None, f"Which appliance do you mean: {names}?"

        # fuzzy: ref contains type word (bulb/light/fan...) and optionally a number
        type_word = None
        num = None
        m = re.search(r"\b(bulb|light|fan|ac|air\s*conditioner|tv|pump|socket|appliance|device)\b", refn)
        if m:
            type_word = m.group(1)
        mn = re.search(r"\b([1-3])\b", refn)
        if mn:
            num = int(mn.group(1))

        def base_type(a):
            return "air conditioner" if a.type == "AC" else a.type.lower()

        matches = []
        for a in appliances:
            an = self._norm(a.name)
            a_type = self._norm(base_type(a))
            if type_word and (type_word in an or type_word in a_type):
                channel_ok = (num is None) or (a.channel == num) or (re.search(rf"\b{num}\b", an) is not None)
                if channel_ok:
                    matches.append(a)
            elif num is not None and re.search(rf"\b{num}\b", an):
                matches.append(a)

        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            names = ", ".join(a.name for a in matches)
            return None, f"Which appliance do you mean: {names}?"

        if matches:
            return matches[0], None

        return None, f"I could not find an appliance matching '{ref}'. Registered appliances: {', '.join(a.name for a in appliances) or 'none'}."

    def _fmt_days(self, days: list[int]) -> str:
        if not days:
            return "every day"
        if len(days) == 7 or set(days) == set(range(7)):
            return "every day"
        if set(days) == {0, 1, 2, 3, 4}:
            return "on weekdays"
        return "on " + ", ".join(WEEKDAY_NAMES[d] for d in sorted(days))

    def _fmt_time_12h(self, value: str) -> str:
        try:
            hh, mm = value.split(":")
            hour, minute = int(hh), int(mm)
        except Exception:
            return value
        period = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute:02d} {period}"

    def _repeat_label(self, schedule: Schedule) -> str:
        if schedule.schedule_type == "ONCE":
            return "once"
        if schedule.schedule_type == "WEEKLY":
            return self._fmt_days(json_load(schedule.days_of_week))
        return "daily"

    def _schedule_label(self, app: Appliance, schedule: Schedule) -> str:
        state = "enabled" if schedule.enabled else "disabled"
        return (
            f"{app.name} — {schedule.action} at {self._fmt_time_12h(schedule.start_time)} "
            f"{self._repeat_label(schedule)} ({state})"
        )

    def _schedules_for_appliance(self, app: Appliance, time_ref: str | None = None) -> list[Schedule]:
        query = self.db.query(Schedule).filter(Schedule.appliance_id == app.id)
        if time_ref:
            query = query.filter(Schedule.start_time == time_ref)
        return query.order_by(Schedule.created_at.asc()).all()

    def _pick_schedule(
        self,
        app: Appliance,
        schedules: list[Schedule],
        selector: int | None,
        schedule_id: str | None,
        verb: str,
    ) -> tuple[Schedule | None, str | None]:
        """Select one schedule. Returns (schedule, listing_message_or_None)."""
        if not schedules:
            return None, f"No schedule found for {app.name}."
        if len(schedules) == 1:
            return schedules[0], None
        if schedule_id is not None:
            for s in schedules:
                if s.id == schedule_id:
                    return s, None
            return None, "That schedule no longer exists."
        if selector is not None and 0 <= selector < len(schedules):
            return schedules[selector], None
        listing = " ".join(
            f"{i + 1}. {self._schedule_label(app, s)}" for i, s in enumerate(schedules)
        )
        return None, (
            f"{app.name} has {len(schedules)} schedules: {listing}. Which one should I {verb}?"
        )

    # ------------------------------------------------------------------- create
    def create_schedule(self, draft: dict) -> tuple[dict, str | None]:
        """Create a schedule from a draft dict. Returns (result_dict, error)."""
        app, err = self.resolve_appliance(draft.get("appliance_ref"))
        if err:
            return None, err
        action = draft.get("action")
        start_time = draft.get("start_time")
        off_time = draft.get("off_time") or draft.get("end_time")
        schedule_type = draft.get("schedule_type") or "DAILY"
        days = draft.get("days_of_week")

        if action not in ("ON", "OFF"):
            return None, "Should the appliance be turned ON or OFF?"
        if not start_time:
            return None, "What time should I turn it on or off? For example '6 PM' or '18:00'."
        if schedule_type == "WEEKLY" and not days:
            return None, "Which days of the week should this repeat? For example 'weekdays' or 'Monday and Friday'."

        if not app.control_capable:
            return None, f"{app.name} is not control-capable, so it cannot be scheduled."

        # A schedule with an off_time is an ON/OFF pair and always leads with ON.
        if off_time:
            sched = ScheduleCreate(
                appliance_id=app.id,
                action="ON",
                schedule_type=schedule_type,
                start_time=start_time,
                end_time=off_time,
                days_of_week=days or [],
            )
        else:
            sched = ScheduleCreate(
                appliance_id=app.id,
                action=action,
                schedule_type=schedule_type,
                start_time=start_time,
                days_of_week=days or [],
            )
        from ..api.routers.scheduling import create_schedule as _cs
        created = _cs(sched, self.db)
        repeat = schedule_type
        if repeat == "WEEKLY":
            repeat += f" {self._fmt_days(days or [])}"
        if created.off_time:
            message = (
                f"Scheduled {app.name} to turn ON at {start_time} and OFF at {created.off_time} "
                f"({repeat}). The scheduler will send the command to the ESP32 at the set times."
            )
        else:
            message = (
                f"Scheduled {app.name} to turn {action} at {start_time} ({repeat}). "
                f"The scheduler will send the command to the ESP32 at the set time."
            )
        return {
            "created": True,
            "schedule": created,
            "message": message,
        }, None

    def maybe_clarify(self, draft: dict) -> str | None:
        """Return a clarification question if required fields are missing.

        Progressive order: appliance name, then ON/OFF, then the time (asking
        AM/PM when a bare hour was given). A single event (ON or OFF at one
        time) no longer forces a pair of ON/OFF times.
        """
        app, err = self.resolve_appliance(draft.get("appliance_ref"))
        if err:
            return err
        action = draft.get("action")
        start_time = draft.get("start_time")
        off_time = draft.get("off_time") or draft.get("end_time")
        if not action:
            return f"Should {app.name} turn ON or OFF?"
        if start_time is None and off_time is None:
            ambiguous = draft.get("time_ambiguous")
            if ambiguous:
                return f"Do you mean {ambiguous} AM or {ambiguous} PM?"
            return f"What time should I schedule {app.name} to turn {action}? For example '6 PM'."
        return None

    # ------------------------------------------------------------------- draft
    def save_draft(self, key: str, draft: dict):
        draft["_ts"] = time.time()
        _pending_drafts[key] = draft

    def load_draft(self, key: str) -> dict | None:
        draft = _pending_drafts.get(key)
        if not draft:
            return None
        ts = draft.get("_ts")
        if ts and (time.time() - ts) > DRAFT_TTL_SECONDS:
            _pending_drafts.pop(key, None)
            return None
        return draft

    def clear_draft(self, key: str):
        _pending_drafts.pop(key, None)

    # ------------------------------------------------------------------- manage
    def list_schedules(self) -> str:
        query = self.db.query(Schedule)
        if self.device_id:
            query = query.join(Appliance, Appliance.id == Schedule.appliance_id).filter(
                Appliance.device_id == self.device_id
            )
        schedules = query.order_by(Schedule.created_at.asc()).all()
        if not schedules:
            return "You don't have any schedules yet. Say something like 'turn on bulb 1 at 6 PM every day' to create one."
        id2app = {a.id: a.name for a in self.db.query(Appliance).all()}
        lines = [
            f"{id2app.get(s.appliance_id, s.appliance_id)} — {s.action} at "
            f"{self._fmt_time_12h(s.start_time)} {self._repeat_label(s)} "
            f"({'enabled' if s.enabled else 'disabled'})"
            for s in schedules
        ]
        self.db.commit()
        noun = "schedule" if len(schedules) == 1 else "schedules"
        return f"You have {len(schedules)} {noun}: " + "; ".join(lines)

    def list_appliances(self) -> str:
        query = self.db.query(Appliance)
        if self.device_id:
            query = query.filter(Appliance.device_id == self.device_id)
        appliances = query.all()
        if not appliances:
            return "You have no registered appliances. Add one from the Smart Scheduler page."
        return "Registered appliances: " + ", ".join(
            f"{a.name} ({a.type}, control={'yes' if a.control_capable else 'no'})"
            for a in appliances
        )

    def enable_disable(
        self,
        action: str,
        ref: str | None,
        time_ref: str | None = None,
        selector: int | None = None,
        schedule_id: str | None = None,
    ) -> tuple[str, dict | None]:
        op = "enable" if action == "enable" else "disable"
        app, err = self.resolve_appliance(ref)
        if err:
            return err, None
        schedules = self._schedules_for_appliance(app, time_ref)
        if not schedules:
            if time_ref:
                return f"No schedule found for {app.name} at '{time_ref}'.", None
            return f"No schedule found for {app.name}.", None
        sched, msg = self._pick_schedule(app, schedules, selector, schedule_id, op)
        if msg:
            return msg, {"op": op, "ref": ref, "time_ref": time_ref}
        sched.enabled = (op == "enable")
        if sched.enabled:
            SchedulerService(self.db).refresh_next_execution(sched)
        else:
            sched.next_execution_at = None
        self.db.commit()
        done = "Enabled" if sched.enabled else "Disabled"
        return f"Done. {done} the schedule: {self._schedule_label(app, sched)}.", None

    def delete_schedule(
        self,
        ref: str | None,
        time_ref: str | None = None,
        selector: int | None = None,
        schedule_id: str | None = None,
    ) -> tuple[str, dict | None]:
        app, err = self.resolve_appliance(ref)
        if err:
            return err, None
        schedules = self._schedules_for_appliance(app, time_ref)
        if not schedules:
            if time_ref:
                return f"No schedule found for {app.name} at '{time_ref}'.", None
            return f"No schedule found for {app.name}.", None
        sched, msg = self._pick_schedule(app, schedules, selector, schedule_id, "delete")
        if msg:
            return msg, {"op": "delete", "ref": ref, "time_ref": time_ref}
        label = self._schedule_label(app, sched)
        self.db.delete(sched)
        self.db.commit()
        return f"Done. Removed the schedule: {label}.", None

    def update_schedule(
        self,
        ref: str | None,
        new_time: str | None = None,
        selector: int | None = None,
        schedule_id: str | None = None,
    ) -> tuple[str, dict | None]:
        app, err = self.resolve_appliance(ref)
        if err:
            return err, None
        schedules = self._schedules_for_appliance(app, None)
        if not schedules:
            return f"No schedule found for {app.name}.", None

        if new_time is None and schedule_id is None:
            if len(schedules) == 1 and selector is None:
                return "What time should I change it to? For example '8 PM'.", {
                    "op": "update",
                    "ref": ref,
                }
            sched, msg = self._pick_schedule(app, schedules, selector, schedule_id, "change")
            if msg:
                return msg, {"op": "update", "ref": ref}
            return "What time should I change it to? For example '8 PM'.", {
                "op": "update",
                "ref": ref,
            }

        if schedule_id is not None:
            sched = next((s for s in schedules if s.id == schedule_id), None)
            if not sched:
                return "That schedule no longer exists.", None
        else:
            sched, msg = self._pick_schedule(app, schedules, selector, schedule_id, "change")
            if msg:
                return msg, {"op": "update", "ref": ref, "new_time": new_time}

        if new_time is None:
            return "What time should I change it to? For example '8 PM'.", {
                "op": "update",
                "ref": ref,
                "schedule_id": sched.id,
            }

        sched.start_time = new_time
        SchedulerService(self.db).refresh_next_execution(sched)
        self.db.commit()
        return (
            f"Done. I've rescheduled {app.name} to {sched.action} at "
            f"{self._fmt_time_12h(new_time)} ({self._repeat_label(sched)}).",
            None,
        )

    # ------------------------------------------------------------------- manual
    def manual_control(self, ref: str | None, action: str) -> str:
        app, err = self.resolve_appliance(ref)
        if err:
            return err
        if not app.control_capable:
            return f"{app.name} is not control-capable, so it cannot be switched."
        control = ControlService(self.db)
        try:
            cmd = control.create_command(
                appliance_id=app.id,
                action=action,
                source="VOICE",
            )
        except ValueError as exc:
            return str(exc)
        self.db.commit()
        message = (
            f"Command sent to the ESP32 to turn {app.name} {action}. "
            f"Waiting for confirmation."
        )
        if action == "ON":
            latest = get_latest_reading(self.db, self.device_id)
            if latest is not None and latest.voltage > 250.0:
                message += (
                    f" Note: voltage is currently {latest.voltage:.1f}V, above the "
                    "250V safety limit; the ESP32 may refuse to switch the relay on."
                )
        return message

    # ------------------------------------------------------------------- state
    def current_state(self, ref: str | None) -> str:
        app, err = self.resolve_appliance(ref)
        if err:
            return err
        state = app.last_confirmed_state or "UNKNOWN"
        if state == "UNKNOWN":
            return f"{app.name} has no confirmed state yet. Send an ON or OFF command to the ESP32 to sync it."
        return f"{app.name} is currently {state} (confirmed by the ESP32)."


def json_load(value):
    import json
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []