from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import EnergyReading
from ...billing.engine import load_tariff, calculate_billing
from ...utils.time import utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1/ai", tags=["ai-insights"])


@router.get("/insights")
def get_ai_insights(device_id: str | None = None, db: Session = Depends(get_db)):
    now = utcnow()
    week_ago = now - timedelta(days=7)

    readings = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= week_ago,
        EnergyReading.timestamp <= now,
    )
    if device_id:
        readings = readings.filter(EnergyReading.device_id == device_id)
    readings = readings.order_by(EnergyReading.timestamp.asc()).all()

    if len(readings) < 5:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Need more readings for AI insights.",
            "insights": [],
        }

    powers = [r.power for r in readings]
    mean_p = sum(powers) / len(powers)
    std_p = (sum((p - mean_p) ** 2 for p in powers) / len(powers)) ** 0.5

    total_kwh = max(0, readings[-1].energy - readings[0].energy)
    avg_daily = total_kwh / 7.0

    hour_bins = {}
    for r in readings:
        h = r.timestamp.hour
        if h not in hour_bins:
            hour_bins[h] = []
        hour_bins[h].append(r.power)

    peak_hour = max(hour_bins.keys(), key=lambda h: max(hour_bins[h])) if hour_bins else None
    peak_power = max(powers)

    tariff = load_tariff()
    billing = calculate_billing(avg_daily * 30, tariff, "monthly_equivalent")

    insights = []

    if peak_power > mean_p + 2 * std_p:
        insights.append({
            "type": "ANOMALY",
            "severity": "HIGH",
            "message": f"Peak power of {peak_power:.1f}W detected, significantly above normal ({mean_p:.1f}W average).",
            "data_source": "CALCULATED",
        })

    insights.append({
        "type": "USAGE_PROFILE",
        "severity": "INFO",
        "message": f"Average power: {mean_p:.1f}W, typical range: {max(0, mean_p - std_p):.1f}W to {mean_p + std_p:.1f}W.",
        "data_source": "CALCULATED",
    })

    if peak_hour is not None:
        insights.append({
            "type": "PEAK_PERIOD",
            "severity": "INFO",
            "message": f"Peak usage occurs around {peak_hour}:00.",
            "data_source": "CALCULATED",
        })

    insights.append({
        "type": "PREDICTION",
        "severity": "INFO",
        "message": f"At current rate, estimated monthly energy charge: {tariff.currency} {billing.total_charge:.2f} for {avg_daily * 30:.1f} kWh.",
        "data_source": "PREDICTED",
    })

    if avg_daily > 5:
        insights.append({
            "type": "CONSUMPTION",
            "severity": "MEDIUM",
            "message": f"Daily consumption of {avg_daily:.2f} kWh is above average. Review high-power appliances.",
            "data_source": "CALCULATED",
        })

    return {
        "status": "OK",
        "insights": insights,
        "summary": {
            "avg_power": round(mean_p, 2),
            "std_power": round(std_p, 2),
            "avg_daily_kwh": round(avg_daily, 4),
            "peak_power": round(peak_power, 2),
        },
    }
