from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ...database import get_db
from ...ai.intent_engine import classify_intent
from ...ai.llm_fallback import call_llm_fallback
from ...ai.data_access import get_latest_reading, get_today_readings, calc_daily_energy, get_energy_kwh
from ...billing.engine import load_tariff, calculate_billing
from ...models import Device, ApplianceActivity, AIModel
from ...utils.time import utcnow
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


def _format_power(watts: float) -> str:
    if watts >= 1000:
        return f"{watts/1000:.2f} kilowatts"
    return f"{watts:.2f} watts"


def _format_energy(kwh: float) -> str:
    return f"{kwh:.4f} kilowatt-hours"


def _format_currency(amount: float, currency: str = "INR") -> str:
    if currency == "INR":
        return f"rupees {amount:.2f}"
    return f"{currency} {amount:.2f}"


def _handle_intent(intent_data, device_id: str | None, db: Session) -> str:
    intent = intent_data.intent
    period = intent_data.period

    if intent == "HELP":
        return (
            "I can help you with: current power, voltage, current, energy, frequency, "
            "power factor, today's usage, today's cost, monthly bill, bill prediction, "
            "energy insights, anomalies, peak usage, appliance activity, "
            "daily, weekly, monthly usage, saving tips, and what-if scenarios."
        )

    if intent == "UNKNOWN":
        return "I'm not sure what you're asking. Try asking about your power usage, bill, or energy consumption."

    if intent == "NEEDS_CLARIFICATION":
        return "Do you mean your current power in watts or the energy you've consumed in kilowatt-hours?"

    latest = get_latest_reading(db, device_id)
    today_readings = get_today_readings(db, device_id)
    today_kwh = calc_daily_energy(today_readings)

    if intent == "CURRENT_POWER":
        if not latest:
            return "No device data available yet. Please ensure your device is connected and sending readings."
        return f"Your current measured power is {_format_power(latest.power)}."

    if intent == "CURRENT_VOLTAGE":
        if not latest:
            return "No device data available yet."
        return f"Your current voltage is {latest.voltage:.2f} volts."

    if intent == "CURRENT_CURRENT":
        if not latest:
            return "No device data available yet."
        return f"Your current is {latest.current:.2f} amperes."

    if intent == "CURRENT_ENERGY":
        return f"You have used {_format_energy(today_kwh)} today. This is a measured value."

    if intent == "CURRENT_FREQUENCY":
        if not latest:
            return "No device data available yet."
        return f"Your current frequency is {latest.frequency:.2f} hertz."

    if intent == "CURRENT_POWER_FACTOR":
        if not latest:
            return "No device data available yet."
        return f"Your power factor is {latest.power_factor:.3f}."

    if intent == "TODAY_ENERGY":
        return f"You have used {_format_energy(today_kwh)} today. This is based on measured data."

    if intent == "TODAY_COST":
        tariff = load_tariff()
        billing = calculate_billing(today_kwh, tariff, "daily")
        return f"Today's measured energy charge is {_format_currency(billing.total_charge, tariff.currency)} for {today_kwh:.4f} kilowatt-hours."

    if intent == "MONTHLY_BILL":
        tariff = load_tariff()
        recent_kwh = get_energy_kwh(db, utcnow() - timedelta(days=7), utcnow(), device_id)
        if recent_kwh <= 0:
            return "Not enough data to estimate your monthly bill."
        avg_daily = recent_kwh / 7.0
        projected = avg_daily * 30
        billing = calculate_billing(projected, tariff, "monthly_equivalent")
        return f"Based on your recent usage, your estimated monthly energy charge is {_format_currency(billing.total_charge, tariff.currency)} for {projected:.2f} kilowatt-hours."

    if intent == "BILL_PREDICTION":
        tariff = load_tariff()
        recent_kwh = get_energy_kwh(db, utcnow() - timedelta(days=7), utcnow(), device_id)
        if recent_kwh <= 0:
            return "Not enough data to predict your bill."
        avg_daily = recent_kwh / 7.0
        billing_period_kwh = avg_daily * (tariff.billing_period_months * 30)
        billing = calculate_billing(billing_period_kwh, tariff, "billing_period")
        return f"Based on your recent usage of {avg_daily:.2f} kilowatt-hours per day, your estimated {tariff.billing_period_months}-month billing period energy charge is {_format_currency(billing.total_charge, tariff.currency)} for {billing_period_kwh:.2f} kilowatt-hours. This is an estimate."

    if intent == "BILL_EXPLANATION":
        tariff = load_tariff()
        return f"Your bill uses {tariff.tariff_name}. Slabs: First 100 units free, 101-200 at 2.35 rupees, 201-500 at 4.45 rupees, above 500 at 6.45 rupees. Billing period is {tariff.billing_period_months} months."

    if intent == "ENERGY_INSIGHT":
        if not today_readings:
            return "No data available for insights yet."
        peak = max((r.power for r in today_readings), default=0)
        avg = sum(r.power for r in today_readings) / len(today_readings) if today_readings else 0
        return f"Today's energy insight: Average power {_format_power(avg)}, peak {_format_power(peak)}, total usage {_format_energy(today_kwh)}."

    if intent == "PEAK_USAGE":
        if not today_readings:
            return "No data available to determine peak usage."
        peak = max(today_readings, key=lambda r: r.power)
        return f"Peak power today was {_format_power(peak.power)} at {peak.timestamp.strftime('%I:%M %p')}."

    if intent == "ANOMALY_STATUS":
        return "To check for anomalies, please visit the analytics page. Anomaly detection requires sufficient historical data."

    if intent == "APPLIANCE_ACTIVITY":
        model = db.query(AIModel).filter(
            AIModel.hardware_validated == True,
            AIModel.status == "PUBLISHED",
        ).order_by(AIModel.created_at.desc()).first()

        if not model:
            return "Appliance recognition model is not available yet. Real hardware validation is required."

        return "Appliance recognition requires a validated model from real hardware data."

    if intent in ("DAILY_USAGE", "WEEKLY_USAGE", "MONTHLY_USAGE"):
        return f"Today's energy usage is {_format_energy(today_kwh)}. Visit the analytics page for detailed daily, weekly, and monthly charts."

    if intent == "SAVING_RECOMMENDATION":
        if not today_readings:
            return "I need usage data to provide saving recommendations."
        avg = sum(r.power for r in today_readings) / len(today_readings) if today_readings else 0
        if avg > 500:
            return f"Your average power is {_format_power(avg)}, which is relatively high. Consider identifying always-on devices and turning off unused appliances."
        return f"Your average power is {_format_power(avg)}, which is moderate. Monitor your usage patterns to find further savings."

    if intent == "ENERGY_COACH":
        return "I'm your energy coach! Visit the Coach page for personalized recommendations based on your actual usage patterns."

    if intent == "WHAT_IF":
        return "Visit the What-If Simulator page to model scenarios like reducing consumption by a certain percentage."

    if intent == "DEVICE_STATUS":
        device = db.query(Device).first() if not device_id else db.query(Device).filter(Device.id == device_id).first()
        if not device:
            return "No device registered yet."
        if device.last_seen:
            age = (utcnow() - device.last_seen).total_seconds()
            if age < 300:
                return f"Device {device.name} is online. Last seen {int(age)} seconds ago."
            return f"Device {device.name} appears offline. Last seen {int(age)} seconds ago."
        return f"Device {device.name} has never sent a reading."

    if intent == "LAST_UPDATE":
        if not latest:
            return "No readings have been received yet."
        age = (utcnow() - latest.timestamp).total_seconds()
        if age < 60:
            return f"Last reading was {int(age)} seconds ago."
        if age < 3600:
            return f"Last reading was {int(age/60)} minutes ago."
        return f"Last reading was {int(age/3600)} hours ago."

    return "I can help you with energy monitoring, billing, and usage insights. What would you like to know?"


@router.post("/query", response_model=VoiceQueryResponse)
async def process_voice_query(req: VoiceQueryRequest, db: Session = Depends(get_db)):
    start_time = time.time()

    intent_result = classify_intent(req.text)
    source = "LOCAL"

    if intent_result.intent == "UNKNOWN" and intent_result.confidence < 0.5:
        llm_result = await call_llm_fallback(req.text)
        if llm_result and llm_result.get("intent") != "UNKNOWN":
            intent_result = type("Intent", (), llm_result)()
            source = "LLM"

    response_text = _handle_intent(intent_result, req.device_id, db)

    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    logger.info(
        "Voice query: '%s' -> intent=%s source=%s time=%sms",
        req.text[:80], getattr(intent_result, 'intent', 'UNKNOWN'), source, elapsed_ms,
    )

    return VoiceQueryResponse(
        query=req.text,
        intent=getattr(intent_result, 'intent', 'UNKNOWN'),
        confidence=getattr(intent_result, 'confidence', 0.0),
        response=response_text,
        source=source,
        processing_time_ms=elapsed_ms,
    )
