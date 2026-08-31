from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import EnergyReading, BillingRecord
from ...billing.engine import load_tariff, calculate_billing
from ...ai.data_access import get_energy_kwh
from ...utils.time import utcnow
from datetime import timedelta
import json

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/energy-summary")
def energy_summary(days: int = 30, device_id: str | None = None, db: Session = Depends(get_db)):
    now = utcnow()
    start = now - timedelta(days=min(days, 365))

    readings = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= now,
    )
    if device_id:
        readings = readings.filter(EnergyReading.device_id == device_id)

    readings = readings.order_by(EnergyReading.timestamp.asc()).all()

    if not readings:
        return {"status": "NO_DATA", "message": "No data available for report."}

    total_kwh = max(0, readings[-1].energy - readings[0].energy)
    tariff = load_tariff()
    billing = calculate_billing(total_kwh, tariff, "monthly_equivalent")

    powers = [r.power for r in readings]
    peak_power = max(powers)
    avg_power = sum(powers) / len(powers)

    first_date = readings[0].timestamp.isoformat()
    last_date = readings[-1].timestamp.isoformat()

    return {
        "report_type": "ENERGY_SUMMARY",
        "period": {
            "start": first_date,
            "end": last_date,
            "days": days,
        },
        "energy": {
            "total_kwh": round(total_kwh, 4),
            "avg_daily_kwh": round(total_kwh / max(1, days), 4),
        },
        "power": {
            "peak_watts": round(peak_power, 2),
            "avg_watts": round(avg_power, 2),
        },
        "cost": {
            "energy_charge": billing.total_charge,
            "currency": tariff.currency,
            "period_type": "monthly_equivalent",
        },
        "readings_count": len(readings),
        "data_source": "MEASURED",
    }
