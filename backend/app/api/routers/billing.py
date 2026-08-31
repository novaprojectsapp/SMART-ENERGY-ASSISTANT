from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
from ...database import get_db
from ...models import EnergyReading
from ...billing.engine import load_tariff, calculate_billing
import json
import logging

logger = logging.getLogger("smart_energy.api.billing")
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _get_period_kwh(db: Session, start: datetime, end: datetime, device_id: str | None = None) -> float:
    query = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= end,
    )
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)

    readings = query.order_by(EnergyReading.timestamp.asc()).all()
    if len(readings) < 2:
        return 0.0

    first_energy = readings[0].energy
    last_energy = readings[-1].energy
    return max(0.0, last_energy - first_energy)


@router.get("/today")
def get_today_billing(device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    kwh = _get_period_kwh(db, start_of_day, now, device_id)
    tariff = load_tariff()
    result = calculate_billing(kwh, tariff, period_type="monthly_equivalent")

    daily_rate = result.total_charge
    monthly_rate = daily_rate * 30
    billing_period_rate = daily_rate * tariff.billing_period_months

    return {
        "period": "today",
        "period_start": start_of_day.isoformat(),
        "period_end": now.isoformat(),
        "measured_kwh": round(kwh, 4),
        "energy_charge_today": round(daily_rate, 2),
        "monthly_equivalent_estimate": round(monthly_rate, 2),
        "billing_period_estimate": round(billing_period_rate, 2),
        "billing_period_months": tariff.billing_period_months,
        "currency": tariff.currency,
        "tariff_version": tariff.version,
        "slab_breakdown": [
            {
                "slab": s.slab_number,
                "units": s.units_in_slab,
                "rate": s.rate_per_unit,
                "charge": s.charge,
                "description": s.description,
            }
            for s in result.slab_breakdown
        ],
        "data_source": "MEASURED",
    }


@router.get("/predict")
def predict_bill(
    days: int = 30,
    device_id: str | None = None,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    kwh = _get_period_kwh(db, now - timedelta(days=7), now, device_id)

    if kwh <= 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No consumption data available for prediction",
        }

    avg_daily = kwh / 7.0
    tariff = load_tariff()

    projected_monthly = avg_daily * 30
    projected_billing = avg_daily * (tariff.billing_period_months * 30)

    monthly_result = calculate_billing(projectly_monthly, tariff, period_type="monthly_equivalent")
    billing_result = calculate_billing(projected_billing, tariff, period_type="billing_period")

    return {
        "status": "OK",
        "prediction_basis": "LAST_7_DAYS",
        "input_window_days": 7,
        "avg_daily_kwh": round(avg_daily, 4),
        "monthly_equivalent": {
            "projected_kwh": round(projected_monthly, 4),
            "energy_charge": round(monthly_result.total_charge, 2),
            "currency": tariff.currency,
        },
        "billing_period": {
            "months": tariff.billing_period_months,
            "projected_kwh": round(projected_billing, 4),
            "energy_charge": round(billing_result.total_charge, 2),
            "currency": tariff.currency,
        },
        "tariff_version": tariff.version,
        "timestamp": now.isoformat(),
        "data_source": "PREDICTED",
    }


@router.get("/tariff")
def get_tariff_info():
    tariff = load_tariff()
    return {
        "tariff_name": tariff.tariff_name,
        "region": tariff.region,
        "version": tariff.version,
        "currency": tariff.currency,
        "billing_period_months": tariff.billing_period_months,
        "effective_date": tariff.effective_date,
        "slabs": [
            {
                "slab_number": s.slab_number,
                "min_units": s.min_units,
                "max_units": s.max_units,
                "rate_per_unit": s.rate_per_unit,
                "description": s.description,
            }
            for s in tariff.slabs
        ],
    }
