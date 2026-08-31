from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import Device, EnergyReading
from ...billing.engine import load_tariff, calculate_billing
from ...ai.data_access import get_energy_kwh
from ...utils.time import utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


@router.get("")
def get_recommendations(device_id: str | None = None, db: Session = Depends(get_db)):
    now = utcnow()
    week_start = now - timedelta(days=7)

    recent_kwh = get_energy_kwh(db, week_start, now, device_id)
    avg_daily = recent_kwh / 7.0 if recent_kwh > 0 else 0

    latest = (
        db.query(EnergyReading)
        .order_by(EnergyReading.timestamp.desc())
        .first()
    )

    recommendations = []

    if not latest:
        return {
            "recommendations": [],
            "status": "NO_DATA",
            "message": "Connect your device to receive personalized recommendations.",
        }

    peak_readings = (
        db.query(EnergyReading)
        .filter(EnergyReading.timestamp >= now - timedelta(days=7))
        .order_by(EnergyReading.power.desc())
        .limit(5)
        .all()
    )

    if peak_readings:
        peak_avg = sum(r.power for r in peak_readings) / len(peak_readings)
        if peak_avg > 500:
            recommendations.append({
                "type": "PEAK_REDUCTION",
                "priority": "HIGH",
                "message": f"Your peak power usage averages {peak_avg:.0f}W. Consider spreading high-power appliance usage across different times.",
                "data_source": "MEASURED",
            })

    if avg_daily > 5:
        recommendations.append({
            "type": "HIGH_CONSUMPTION",
            "priority": "MEDIUM",
            "message": f"Your average daily consumption is {avg_daily:.2f} kWh. Check for always-on devices that could be switched off when not needed.",
            "data_source": "MEASURED",
        })

    if avg_daily > 0 and avg_daily < 2:
        recommendations.append({
            "type": "EFFICIENT_USAGE",
            "priority": "INFO",
            "message": f"Your average daily consumption of {avg_daily:.2f} kWh is efficient. Keep maintaining good habits!",
            "data_source": "MEASURED",
        })

    tariff = load_tariff()
    projected_monthly = avg_daily * 30
    if projected_monthly > 100:
        savings_pct = 0.15
        saved_kwh = projected_monthly * savings_pct
        saved_billing = calculate_billing(saved_kwh, tariff, "monthly_equivalent")
        recommendations.append({
            "type": "BILL_REDUCTION",
            "priority": "HIGH",
            "message": f"A 15% reduction could save approximately {saved_kwh:.1f} kWh per month and {_format_currency(saved_billing.total_charge, tariff.currency)}.",
            "data_source": "PREDICTED",
        })

    return {
        "recommendations": recommendations,
        "summary": {
            "avg_daily_kwh": round(avg_daily, 4),
            "weekly_kwh": round(recent_kwh, 4),
        },
        "data_source": "MEASURED",
    }


def _format_currency(amount: float, currency: str) -> str:
    if currency == "INR":
        return f"Rs.{amount:.2f}"
    return f"{currency} {amount:.2f}"
