from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ...database import get_db
from ...ai.intent_engine import classify_intent
from ...ai.llm_fallback import call_llm_fallback
from ...ai.context_builder import ContextBuilder
from ...ai.response_composer import compose_response
from ...ai.data_access import get_latest_reading, get_today_readings, calc_daily_energy, get_energy_kwh, get_recent_readings
from ...ai.schedule_parser import extract_appliance_ref, extract_draft, parse_time, parse_schedule_selector
from ...ai.schedule_actions import ScheduleActions
from ...billing.engine import load_tariff, calculate_billing
from ...models import Device
from ...utils.time import utcnow, naive_utc
from ...utils.device_selection import select_device_id
from datetime import datetime, timedelta, timezone
import json
import logging
import time

logger = logging.getLogger("smart_energy.api.voice")
router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


class VoiceQueryRequest(BaseModel):
    text: str
    device_id: str | None = None


class VoiceQueryResponse(BaseModel):
    query: str
    intent: str
    confidence: float
    response: str
    source: str
    processing_time_ms: float


# ---------------------------------------------------------------------------
# Lightweight per-session conversation history (bounded, in-memory)
# ---------------------------------------------------------------------------
_conversation_history: dict[str, list[dict]] = {}
MAX_HISTORY_TURNS = 10


def _get_history(session_key: str) -> list[dict]:
    return _conversation_history.get(session_key, [])


def _add_history(session_key: str, role: str, text: str, intent: str = ""):
    if session_key not in _conversation_history:
        _conversation_history[session_key] = []
    _conversation_history[session_key].append({"role": role, "text": text, "intent": intent})
    if len(_conversation_history[session_key]) > MAX_HISTORY_TURNS:
        _conversation_history[session_key] = _conversation_history[session_key][-MAX_HISTORY_TURNS:]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _format_power(watts: float) -> str:
    if watts >= 1000:
        return f"{watts / 1000:.2f} kilowatts"
    return f"{watts:.0f} watts"


def _format_energy(kwh: float) -> str:
    return f"{kwh:.2f} kilowatt-hours"


def _format_currency(amount: float, currency: str = "INR") -> str:
    if currency == "INR":
        return f"rupees {amount:.0f}"
    return f"{currency} {amount:.0f}"


def _format_currency_short(amount: float) -> str:
    return f"\u20b9{amount:,.0f}"


# ---------------------------------------------------------------------------
# Deterministic local response generator (offline, fast, no hallucination)
# ---------------------------------------------------------------------------
def _local_response(intent_data, device_id: str | None, db: Session, raw_text: str = "") -> str:
    intent = intent_data.intent

    if intent == "HELP":
        return (
            "I can help you with: current power, voltage, current, energy, frequency, "
            "power factor, today's usage, today's cost, monthly bill, bill prediction, "
            "energy insights, anomalies, peak usage, "
            "daily, weekly, monthly usage, saving tips, what-if scenarios, and "
            "appliance scheduling. For example: 'turn on bulb 1 at 6 PM every day'."
        )

    if intent == "UNKNOWN":
        return "I'm not sure what you're asking. Try asking about your power usage, bill, energy consumption, or scheduling."

    if intent == "NEEDS_CLARIFICATION":
        return "Do you mean your current power in watts or the energy you've consumed in kilowatt-hours?"

    latest = get_latest_reading(db, device_id)
    today_readings = get_today_readings(db, device_id)
    today_kwh = calc_daily_energy(today_readings)

    if intent == "CURRENT_POWER":
        if not latest:
            return "No device data available yet. Please ensure your device is connected and sending readings."
        pw = latest.power
        if pw >= 1000:
            return f"Right now your system is drawing {pw / 1000:.2f} kilowatts."
        return f"Right now your system is drawing {pw:.0f} watts."

    if intent == "CURRENT_VOLTAGE":
        if not latest:
            return "No device data available yet."
        v = latest.voltage
        if v > 250:
            return f"Your voltage is {v:.1f} volts. That is above the safe limit, and protection is active."
        if v < 200:
            return f"Your voltage is {v:.1f} volts. That seems unusually low."
        return f"Your voltage is {v:.1f} volts."

    if intent == "CURRENT_CURRENT":
        if not latest:
            return "No device data available yet."
        return f"Your current draw is {latest.current:.2f} amps."

    if intent == "CURRENT_ENERGY":
        return f"You have used {_format_energy(today_kwh)} today."

    if intent == "CURRENT_FREQUENCY":
        if not latest:
            return "No device data available yet."
        return f"Your frequency is {latest.frequency:.1f} hertz."

    if intent == "CURRENT_POWER_FACTOR":
        if not latest:
            return "No device data available yet."
        pf = latest.power_factor
        if pf >= 0.95:
            return f"Your power factor is {pf:.2f}, which is good."
        if pf >= 0.85:
            return f"Your power factor is {pf:.2f}, which is fair."
        return f"Your power factor is {pf:.2f}, which is low."

    if intent == "TODAY_ENERGY":
        return f"You have used {_format_energy(today_kwh)} today."

    if intent == "TODAY_COST":
        tariff = load_tariff()
        billing = calculate_billing(today_kwh, tariff, "daily")
        return f"Today's electricity charge is {_format_currency_short(billing.total_charge)} for {today_kwh:.2f} units."

    if intent == "MONTHLY_BILL":
        tariff = load_tariff()
        recent_kwh = get_energy_kwh(db, utcnow() - timedelta(days=7), utcnow(), device_id)
        if recent_kwh <= 0:
            return "Not enough data to estimate your monthly bill."
        avg_daily = recent_kwh / 7.0
        projected = avg_daily * 30
        billing = calculate_billing(projected, tariff, "monthly_equivalent")
        return f"Based on your recent usage, your estimated monthly bill is {_format_currency_short(billing.total_charge)} for about {projected:.0f} units."

    if intent == "BILL_PREDICTION":
        tariff = load_tariff()
        recent_kwh = get_energy_kwh(db, utcnow() - timedelta(days=7), utcnow(), device_id)
        if recent_kwh <= 0:
            return "Not enough data to predict your bill."
        avg_daily = recent_kwh / 7.0
        billing_period_kwh = avg_daily * (tariff.billing_period_months * 30)
        billing = calculate_billing(billing_period_kwh, tariff, "billing_period")
        months = tariff.billing_period_months
        return f"Based on your recent usage, your estimated {months}-month bill is {_format_currency_short(billing.total_charge)} for about {billing_period_kwh:.0f} units. This is an estimate."

    if intent == "BILL_EXPLANATION":
        tariff = load_tariff()
        slabs = []
        for s in tariff.slabs:
            if s.max_units:
                slabs.append(f"First {s.max_units} units: {s.rate_per_unit} rupees per unit")
            else:
                slabs.append(f"Above {s.min_units - 1} units: {s.rate_per_unit} rupees per unit")
        slab_text = "; ".join(slabs)
        return f"Your bill uses the {tariff.tariff_name} tariff with {tariff.billing_period_months}-month billing periods. Slabs: {slab_text}."

    if intent == "ENERGY_INSIGHT":
        if not today_readings:
            return "No data available for insights yet."
        peak = max((r.power for r in today_readings), default=0)
        avg = sum(r.power for r in today_readings) / len(today_readings) if today_readings else 0
        return f"Today's average power is {_format_power(avg)}, peak was {_format_power(peak)}, and you used {_format_energy(today_kwh)}."

    if intent == "PEAK_USAGE":
        if not today_readings:
            return "No data available to determine peak usage."
        peak = max(today_readings, key=lambda r: r.power)
        return f"Peak power today was {_format_power(peak.power)} at {peak.timestamp.strftime('%I:%M %p')}."

    if intent == "ANOMALY_STATUS":
        return "To check for anomalies, please visit the analytics page. Anomaly detection requires sufficient historical data."

    if intent == "APPLIANCE_ACTIVITY":
        if not latest:
            return "No appliance activity data yet."
        return (
            f"Your current draw is {_format_power(latest.power)} at "
            f"{latest.voltage:.1f} volts. Individual appliance detection is available "
            "through the Smart Scheduler page."
        )

    if intent in ("DAILY_USAGE", "WEEKLY_USAGE", "MONTHLY_USAGE"):
        return f"Today's energy usage is {_format_energy(today_kwh)}."

    if intent == "SAVING_RECOMMENDATION":
        if not today_readings:
            return "I need usage data to provide saving recommendations."
        avg = sum(r.power for r in today_readings) / len(today_readings) if today_readings else 0
        if avg > 500:
            return f"Your average power today is {_format_power(avg)}, which is relatively high. Consider identifying always-on devices and turning off unused appliances to reduce your bill."
        return f"Your average power today is {_format_power(avg)}, which is moderate. Monitor your usage patterns to find further savings."

    if intent == "ENERGY_COACH":
        return "I'm your energy coach! Visit the Coach page for personalised recommendations based on your actual usage patterns."

    if intent == "WHAT_IF":
        return "Visit the What-If Simulator page to model scenarios like reducing consumption by a certain percentage."

    if intent == "DEVICE_STATUS":
        effective_id = select_device_id(db, device_id)
        device = db.query(Device).filter(Device.id == effective_id).first() if effective_id else None
        if not device:
            return "No device registered yet."
        if device.last_seen:
            age = (naive_utc(utcnow()) - naive_utc(device.last_seen)).total_seconds()
            if age < 300:
                return f"Your device is online and connected. Last seen {int(age)} seconds ago."
            if age < 3600:
                return f"Your device appears offline. Last seen {int(age / 60)} minutes ago."
            return f"Your device appears offline. Last seen {int(age / 3600)} hours ago."
        return f"Device {device.name} has never sent a reading."

    if intent == "LAST_UPDATE":
        if not latest:
            return "No readings have been received yet."
        age = (naive_utc(utcnow()) - naive_utc(latest.timestamp)).total_seconds()
        if age < 60:
            return f"The last reading was {int(age)} seconds ago."
        if age < 3600:
            return f"The last reading was {int(age / 60)} minutes ago."
        return f"The last reading was {int(age / 3600)} hours ago."

    if intent in ("NORMAL_USAGE", "ENERGY_COMPARISON"):
        recent = get_recent_readings(db, days=7, device_id=device_id)
        if not recent:
            return "I don't have enough historical data yet to compare your usage with your normal pattern."
        powers = [r.power for r in recent]
        avg_power = sum(powers) / len(powers) if powers else 0
        recent_kwh = get_energy_kwh(db, utcnow() - timedelta(days=7), utcnow(), device_id)
        avg_daily = recent_kwh / 7.0 if recent_kwh > 0 else 0
        return f"Your average power over the last 7 days is {_format_power(avg_power)}, averaging {avg_daily:.2f} units per day."

    return "I can help you with energy monitoring, billing, and usage insights. What would you like to know?"


# ---------------------------------------------------------------------------
# Scheduling / appliance-management conversation flow (multi-turn capable)
# ---------------------------------------------------------------------------
_SCHEDULE_INTENTS = {
    "CREATE_SCHEDULE", "UPDATE_SCHEDULE", "DELETE_SCHEDULE",
    "ENABLE_SCHEDULE", "DISABLE_SCHEDULE", "LIST_SCHEDULES",
    "MANUAL_APPLIANCE_ON", "MANUAL_APPLIANCE_OFF", "LIST_APPLIANCES",
}

_OP_FAMILIES_BY_INTENT = {
    "ENABLE_SCHEDULE": "enable",
    "DISABLE_SCHEDULE": "disable",
    "DELETE_SCHEDULE": "delete",
    "UPDATE_SCHEDULE": "update",
}


def _store_state(actions, key, state):
    if state:
        actions.save_draft(key, state)
    else:
        actions.clear_draft(key)


def _is_create_draft(pending):
    if not pending or pending.get("op"):
        return False
    return any(pending.get(f) for f in ("appliance_ref", "action", "start_time", "off_time", "time_ambiguous"))


def _continue_management(actions, key, raw_text, pending):
    """Advance an in-progress enable/disable/delete/update operation.

    A follow-up turn may supply the appliance, a specific time, or an ordinal
    ("the second one"). Anything already known is carried in `pending`.
    """
    op = pending.get("op")
    ref = extract_appliance_ref(raw_text) or pending.get("ref")
    time_ref = parse_time(raw_text) or pending.get("time_ref")
    new_time = parse_time(raw_text) or pending.get("new_time")
    selector = parse_schedule_selector(raw_text)
    schedule_id = pending.get("schedule_id")

    if not ref:
        verb = {"enable": "enable", "disable": "disable", "delete": "delete", "update": "change"}.get(op, "change")
        actions.save_draft(key, pending)
        return f"Which appliance schedule should I {verb}? Please name it."

    if op == "enable":
        msg, state = actions.enable_disable("enable", ref, time_ref=time_ref, selector=selector, schedule_id=schedule_id)
    elif op == "disable":
        msg, state = actions.enable_disable("disable", ref, time_ref=time_ref, selector=selector, schedule_id=schedule_id)
    elif op == "delete":
        msg, state = actions.delete_schedule(ref, time_ref=time_ref, selector=selector, schedule_id=schedule_id)
    else:
        msg, state = actions.update_schedule(ref, new_time=new_time, selector=selector, schedule_id=schedule_id)
    _store_state(actions, key, state)
    return msg


def _create_or_continue(actions, key, raw_text, pending):
    """Create a schedule, or fill missing fields from a follow-up answer."""
    extracted = extract_draft(raw_text)
    base = {}
    if pending and not pending.get("op"):
        base = pending
    merged = dict(base)
    for field in ("appliance_ref", "action", "start_time", "off_time", "schedule_type", "days_of_week", "time_ambiguous"):
        value = extracted.get(field)
        if value:
            merged[field] = value
    if not merged.get("schedule_type"):
        merged["schedule_type"] = "DAILY"

    question = actions.maybe_clarify(merged)
    if question:
        actions.save_draft(key, merged)
        return question

    result, err = actions.create_schedule(merged)
    if err:
        actions.save_draft(key, merged)
        return err
    actions.clear_draft(key)
    return result["message"]


def _handle_schedule(intent_str, raw_text, device_id, db, intent_data):
    actions = ScheduleActions(db, device_id=device_id)
    key = device_id or "default"
    pending = actions.load_draft(key) or {}
    op = pending.get("op")

    # Manual control: an explicit command wins, but "Turn it on." while a
    # create draft is being completed is a clarification answer, not a command.
    if intent_str in ("MANUAL_APPLIANCE_ON", "MANUAL_APPLIANCE_OFF"):
        if _is_create_draft(pending):
            return _create_or_continue(actions, key, raw_text, pending)
        actions.clear_draft(key)
        action = "ON" if intent_str == "MANUAL_APPLIANCE_ON" else "OFF"
        ref = (intent_data.extra or {}).get("appliance_ref") or extract_appliance_ref(raw_text)
        return actions.manual_control(ref, action)

    if intent_str == "LIST_APPLIANCES":
        actions.clear_draft(key)
        return actions.list_appliances()

    if intent_str == "LIST_SCHEDULES":
        actions.clear_draft(key)
        return actions.list_schedules()

    # Continue an in-progress management op (the user answered a follow-up that
    # was classified as UNKNOWN or as a repeated phrasing of the same op).
    if op and (intent_str == "UNKNOWN" or _OP_FAMILIES_BY_INTENT.get(intent_str) == op):
        return _continue_management(actions, key, raw_text, pending)

    # Fresh management operation (supersedes any older pending op/draft).
    if intent_str in _OP_FAMILIES_BY_INTENT:
        family = _OP_FAMILIES_BY_INTENT[intent_str]
        actions.clear_draft(key)
        return _continue_management(actions, key, raw_text, {"op": family, "ref": extract_appliance_ref(raw_text)})

    return _create_or_continue(actions, key, raw_text, pending)


# ---------------------------------------------------------------------------
# Voice query endpoint — full AI pipeline
# ---------------------------------------------------------------------------
@router.post("/query", response_model=VoiceQueryResponse)
async def process_voice_query(req: VoiceQueryRequest, db: Session = Depends(get_db)):
    start_time = time.time()

    device_id = select_device_id(db, req.device_id)
    session_key = device_id or "default"

    # Step 1: Normalise and classify intent locally
    intent_result = classify_intent(req.text)
    source = "LOCAL"

    # Step 2: If local intent is UNKNOWN and low confidence, try Gemini as intent fallback
    if intent_result.intent == "UNKNOWN" and intent_result.confidence < 0.5:
        llm_result = await call_llm_fallback(req.text)
        if llm_result and llm_result.get("intent") != "UNKNOWN":
            intent_result = type("Intent", (), llm_result)()
            source = "LLM"

    # Step 3: For scheduling/management intents, and for follow-up answers to an
    # in-progress scheduling conversation, use the multi-turn local flow.
    intent_str = getattr(intent_result, "intent", "UNKNOWN")
    confidence = getattr(intent_result, "confidence", 0.0)

    draft_check = ScheduleActions(db, device_id=device_id)
    pending_draft = draft_check.load_draft(session_key)
    continue_pending = intent_str == "UNKNOWN" and bool(pending_draft)

    if intent_str in _SCHEDULE_INTENTS or continue_pending:
        response_text = _handle_schedule(intent_str, req.text, device_id, db, intent_result)
        _add_history(session_key, "user", req.text, intent_str)
        _add_history(session_key, "assistant", response_text, intent_str)
    elif intent_str in ("HELP", "UNKNOWN", "NEEDS_CLARIFICATION"):
        response_text = _local_response(intent_result, device_id, db, req.text)
        _add_history(session_key, "user", req.text, intent_str)
        _add_history(session_key, "assistant", response_text, intent_str)
    else:
        # Step 4: Build structured context for AI-assisted responses
        ctx_builder = ContextBuilder(db, device_id)
        context = ctx_builder.build()
        context["query"] = req.text
        context["intent"] = intent_str
        context["confidence"] = confidence

        # Step 5: Confidence-aware routing
        # >= 0.85 → local deterministic response (fast, no API cost)
        # 0.60-0.84 → AI-assisted response with structured context
        # < 0.60 → full AI interpretation
        use_ai = confidence < 0.85

        if use_ai and confidence >= 0.60:
            # Mid-confidence: try AI composition, fall back to local
            history = _get_history(session_key)
            ai_response = await compose_response(req.text, context, history)
            if ai_response:
                response_text = ai_response
                source = "AI"
            else:
                response_text = _local_response(intent_result, device_id, db, req.text)
        elif use_ai and confidence < 0.60:
            # Low confidence: rely more on AI interpretation
            history = _get_history(session_key)
            ai_response = await compose_response(req.text, context, history)
            if ai_response:
                response_text = ai_response
                source = "AI"
            else:
                response_text = _local_response(intent_result, device_id, db, req.text)
        else:
            # High confidence: fast local response
            response_text = _local_response(intent_result, device_id, db, req.text)

        _add_history(session_key, "user", req.text, intent_str)
        _add_history(session_key, "assistant", response_text, intent_str)

    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    logger.info(
        "Voice query: '%s' -> intent=%s confidence=%.2f source=%s time=%sms",
        req.text[:80], intent_str, confidence, source, elapsed_ms,
    )

    return VoiceQueryResponse(
        query=req.text,
        intent=intent_str,
        confidence=confidence,
        response=response_text,
        source=source,
        processing_time_ms=elapsed_ms,
    )
