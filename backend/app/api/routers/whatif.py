from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from ...database import get_db
from ...billing.engine import load_tariff, calculate_billing
from ...ai.data_access import get_energy_kwh
from ...utils.time import utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1", tags=["what-if"])


class WhatIfRequest(BaseModel):
    reduction_percent: float = Field(..., ge=0, le=100)
    device_id: str | None = None


@router.post("/what-if")
def simulate_what_if(req: WhatIfRequest, db: Session = Depends(get_db)):
    now = utcnow()
    week_start = now - timedelta(days=7)

    recent_kwh = get_energy_kwh(db, week_start, now, req.device_id)
    if recent_kwh <= 0:
        return {"status": "INSUFFICIENT_DATA", "message": "No consumption data available for simulation."}

    avg_daily = recent_kwh / 7.0
    tariff = load_tariff()

    baseline_monthly = avg_daily * 30
    scenario_monthly = baseline_monthly * (1 - req.reduction_percent / 100)
    baseline_billing = calculate_billing(baseline_monthly, tariff, "monthly_equivalent")
    scenario_billing = calculate_billing(scenario_monthly, tariff, "monthly_equivalent")

    baseline_2month = avg_daily * 60
    scenario_2month = baseline_2month * (1 - req.reduction_percent / 100)
    baseline_2month_billing = calculate_billing(baseline_2month, tariff, "billing_period")
    scenario_2month_billing = calculate_billing(scenario_2month, tariff, "billing_period")

    return {
        "status": "OK",
        "scenario": f"Reduce consumption by {req.reduction_percent}%",
        "reduction_percent": req.reduction_percent,
        "monthly_equivalent": {
            "baseline_kwh": round(baseline_monthly, 2),
            "scenario_kwh": round(scenario_monthly, 2),
            "baseline_charge": round(baseline_billing.total_charge, 2),
            "scenario_charge": round(scenario_billing.total_charge, 2),
            "estimated_savings": round(baseline_billing.total_charge - scenario_billing.total_charge, 2),
            "currency": tariff.currency,
        },
        "billing_period": {
            "months": tariff.billing_period_months,
            "baseline_kwh": round(baseline_2month, 2),
            "scenario_kwh": round(scenario_2month, 2),
            "baseline_charge": round(baseline_2month_billing.total_charge, 2),
            "scenario_charge": round(scenario_2month_billing.total_charge, 2),
            "estimated_savings": round(baseline_2month_billing.total_charge - scenario_2month_billing.total_charge, 2),
            "currency": tariff.currency,
        },
        "data_source": "PREDICTED",
    }
