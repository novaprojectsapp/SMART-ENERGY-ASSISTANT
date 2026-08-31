"""
High-level scheduling actions used by the voice/AI handler.

Encapsulates appliance resolution (fuzzy matching), schedule CRUD, manual
control, listing, and a lightweight in-process multi-turn draft store so the
assistant can ask clarifying questions and complete a schedule across turns.
"""
import re
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Appliance, Schedule, ControlCommand
from ..schemas.schemas import ScheduleCreate, ControlCommandCreate
from ..services.scheduler import SchedulerService
from ..services.esp32_control import ESP32ControlService, HARDWARE_CONTROL_NOT_AVAILABLE
from ..utils.time import utcnow

logger = logging.getLogger("smart_energy.ai.schedule")

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# In-process multi-turn draft store. Key = session (device_id or 'default').
_pending_drafts: dict[str, dict] = {}


class ScheduleActions:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ utils
    def _norm(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().strip())

    def resolve_appliance(self, ref: str | None) -> tuple[Appliance | None, str | None]:
        """Resolve an appliance reference to a single match.

        Returns (appliance, error_message). If ambiguous, error_message describes it.
        """
        if not ref:
            return None, "Which appliance do you mean? Please name it (e.g. 'bulb 1')."

        appliances = self.db.query(Appliance).all()
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

    # ------------------------------------------------------------------- create
    def create_schedule(self, draft: dict) -> tuple[dict, str | None]:
        """Create a schedule from a draft dict. Returns (result_dict, error)."""
        app, err = self.resolve_appliance(draft.get("appliance_ref"))
        if err:
            return None, err
        action = draft.get("action")
        start_time = draft.get("start_time")
        schedule_type = draft.get("schedule_type") or "DAILY"
        days = draft.get("days_of_week")

        if not action:
            return None, "Should the appliance be turned ON or OFF?"
        if not start_time:
            return None, "What time should I schedule it? For example '6 PM' or '18:00'."

        if not app.control_capable:
            return None, f"{app.name} is not control-capable, so it cannot be scheduled."

        sched = ScheduleCreate(
            appliance_id=app.id,
            action=action,
            schedule_type=schedule_type,
            start_time=start_time,
            days_of_week=days or [],
        )
        from ..api.routers.scheduling import create_schedule as _cs
        created = _cs(sched, self.db)
        self.db.refresh(created)
        repeat = schedule_type
        if repeat == "WEEKLY":
            repeat += f" {self._fmt_days(days or [])}"
        return {
            "created": True,
            "schedule": created,
            "message": f"Scheduled {app.name} to turn {action} at {start_time} ({repeat}).",
        }, None

    def maybe_clarify(self, draft: dict) -> str | None:
        """Return a clarification question if required fields are missing."""
        app, err = self.resolve_appliance(draft.get("appliance_ref"))
        if err:
            return err
        if not draft.get("action"):
            return f"Sure. What time should I turn {app.name} on or off?"
        if not draft.get("start_time"):
            return f"Got it — turn {app.name} {draft.get('action')}. What time?"
        return None

    # ------------------------------------------------------------------- draft
    def save_draft(self, key: str, draft: dict):
        _pending_drafts[key] = draft

    def load_draft(self, key: str) -> dict | None:
        return _pending_drafts.get(key)

    def clear_draft(self, key: str):
        _pending_drafts.pop(key, None)

    # ------------------------------------------------------------------- manage
    def list_schedules(self) -> str:
        schedules = self.db.query(Schedule).order_by(Schedule.created_at.asc()).all()
        if not schedules:
            return "You have no schedules yet. Say something like 'turn on bulb 1 at 6 PM every day' to create one."
        scheduler = SchedulerService(self.db)
        lines = []
        id2app = {a.id: a.name for a in self.db.query(Appliance).all()}
        for s in schedules:
            name = id2app.get(s.appliance_id, s.appliance_id)
            days = self._fmt_days(json_load(s.days_of_week))
            state = "enabled" if s.enabled else "disabled"
            lines.append(f"{name}: {s.action} at {s.start_time} ({s.schedule_type} {days}, {state})")
        self.db.commit()
        return "Your schedules: " + "; ".join(lines)

    def list_appliances(self) -> str:
        appliances = self.db.query(Appliance).all()
        if not appliances:
            return "You have no registered appliances. Add one from the Smart Scheduler page."
        return "Registered appliances: " + ", ".join(
            f"{a.name} ({a.type}, control={'yes' if a.control_capable else 'no'})"
            for a in appliances
        )

    def enable_disable(self, action: str, ref: str | None, time_ref: str | None = None) -> str:
        app, err = self.resolve_appliance(ref)
        if err:
            return err
        schedules = self.db.query(Schedule).filter(Schedule.appliance_id == app.id).all()
        if not schedules:
            return f"No schedule found for {app.name}."
        if time_ref:
            schedules = [s for s in schedules if s.start_time == time_ref]
        if not schedules:
            return f"No matching schedule for {app.name} at '{time_ref or 'any time'}'."
        for s in schedules:
            s.enabled = (action == "enable")
            if not s.enabled:
                s.next_execution_at = None
            else:
                SchedulerService(self.db).refresh_next_execution(s)
        self.db.commit()
        return f"{action.capitalize()}d schedule(s) for {app.name}."

    def delete_schedule(self, ref: str | None, time_ref: str | None = None) -> str:
        app, err = self.resolve_appliance(ref)
        if err:
            return err
        schedules = self.db.query(Schedule).filter(Schedule.appliance_id == app.id).all()
        if not schedules:
            return f"No schedule found for {app.name}."
        if time_ref:
            schedules = [s for s in schedules if s.start_time == time_ref]
        if not schedules:
            return f"No matching schedule for {app.name} at '{time_ref or 'any time'}'."
        for s in schedules:
            self.db.delete(s)
        self.db.commit()
        return f"Removed the schedule(s) for {app.name}."

    # ------------------------------------------------------------------- manual
    def manual_control(self, ref: str | None, action: str) -> str:
        app, err = self.resolve_appliance(ref)
        if err:
            return err
        if not app.control_capable:
            return f"{app.name} is not control-capable, so it cannot be switched."
        hardware = ESP32ControlService()
        hw = hardware.turn_on(app) if action == "ON" else hardware.turn_off(app)
        if hw.get("status") == HARDWARE_CONTROL_NOT_AVAILABLE:
            status = "SIMULATED"
            message = f"SIMULATED: {app.name} would turn {action}. Hardware control is not connected yet."
        else:
            status = "PENDING"
            message = f"Control command created for {app.name} to turn {action}."
        command = ControlCommand(
            appliance_id=app.id,
            action=action,
            source="VOICE",
            status=status,
            message=message,
        )
        self.db.add(command)
        self.db.commit()
        return message


def json_load(value):
    import json
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []
