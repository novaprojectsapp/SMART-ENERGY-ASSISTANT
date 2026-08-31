from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from ...database import get_db
from ...models import EnergyReading
from ...billing.engine import load_tariff, calculate_billing
import logging

logger = logging.getLogger("smart_energy.api.analytics")
router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _get_readings_range(db: Session, start: datetime, end: datetime, device_id: str | None = None):
    query = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= end,
    )
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)
    return query.order_by(EnergyReading.timestamp.asc()).all()


def _calc_energy_delta(readings):
    if len(readings) < 2:
        return 0.0
    return max(0.0, readings[-1].energy - readings[0].energy)


@router.get("/summary")
def get_analytics_summary(device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    today_readings = _get_readings_range(db, today_start, now, device_id)
    week_readings = _get_readings_range(db, week_start, now, device_id)
    month_readings = _get_readings_range(db, month_start, now, device_id)

    tariff = load_tariff()

    today_kwh = _calc_energy_delta(today_readings)
    week_kwh = _calc_energy_delta(week_readings)
    month_kwh = _calc_energy_delta(month_readings)

    today_billing = calculate_billing(today_kwh, tariff, "daily")
    month_billing = calculate_billing(month_kwh, tariff, "monthly_equivalent")

    avg_daily = week_kwh / max(1, (now - week_start).days) if week_kwh > 0 else 0

    peak_power = max((r.power for r in today_readings), default=0)
    avg_power = sum(r.power for r in today_readings) / len(today_readings) if today_readings else 0
    avg_voltage = sum(r.voltage for r in today_readings) / len(today_readings) if today_readings else 0
    avg_pf = sum(r.power_factor for r in today_readings) / len(today_readings) if today_readings else 0

    return {
        "period": {
            "today_start": today_start.isoformat(),
            "week_start": week_start.isoformat(),
            "month_start": month_start.isoformat(),
            "now": now.isoformat(),
        },
        "energy": {
            "today_kwh": round(today_kwh, 4),
            "week_kwh": round(week_kwh, 4),
            "month_kwh": round(month_kwh, 4),
            "avg_daily_kwh": round(avg_daily, 4),
        },
        "power": {
            "current_avg_watts": round(avg_power, 2),
            "peak_watts_today": round(peak_power, 2),
        },
        "quality": {
            "avg_voltage": round(avg_voltage, 2),
            "avg_power_factor": round(avg_pf, 3),
        },
        "cost": {
            "today_energy_charge": today_billing.total_charge,
            "month_energy_charge": month_billing.total_charge,
            "currency": tariff.currency,
        },
        "readings_count": {
            "today": len(today_readings),
            "week": len(week_readings),
            "month": len(month_readings),
        },
        "data_source": "MEASURED" if today_readings else "NO_DATA",
    }


@router.get("/hourly")
def get_hourly_data(days: int = 1, device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=min(days, 30))
    readings = _get_readings_range(db, start, now, device_id)

    hourly = {}
    for r in readings:
        hour_key = r.timestamp.strftime("%Y-%m-%d:00")
        if hour_key not in hourly:
            hourly[hour_key] = {"power_sum": 0, "count": 0, "voltage_sum": 0}
        hourly[hour_key]["power_sum"] += r.power
        hourly[hour_key]["voltage_sum"] += r.voltage
        hourly[hour_key]["count"] += 1

    result = []
    for key in sorted(hourly.keys()):
        h = hourly[key]
        result.append({
            "hour": key,
            "avg_power": round(h["power_sum"] / h["count"], 2) if h["count"] > 0 else 0,
            "avg_voltage": round(h["voltage_sum"] / h["count"], 2) if h["count"] > 0 else 0,
            "readings": h["count"],
        })

    return {"hourly_data": result, "data_source": "MEASURED" if readings else "NO_DATA"}


@router.get("/daily")
def get_daily_data(days: int = 7, device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    daily = []

    for i in range(min(days, 30)):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        readings = _get_readings_range(db, day_start, day_end, device_id)

        kwh = _calc_energy_delta(readings)
        peak = max((r.power for r in readings), default=0)
        avg_p = sum(r.power for r in readings) / len(readings) if readings else 0

        daily.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "kwh": round(kwh, 4),
            "peak_power": round(peak, 2),
            "avg_power": round(avg_p, 2),
            "readings": len(readings),
        })

    return {"daily_data": list(reversed(daily))}


@router.get("/anomalies")
def get_anomalies(device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    readings = _get_readings_range(db, seven_days_ago, now, device_id)

    if len(readings) < 10:
        return {"anomalies": [], "status": "INSUFFICIENT_DATA", "message": "Need at least 10 readings for anomaly detection"}

    powers = [r.power for r in readings]
    mean_p = sum(powers) / len(powers)
    variance = sum((p - mean_p) ** 2 for p in powers) / len(powers)
    std_p = variance ** 0.5

    threshold_high = mean_p + 2 * std_p
    threshold_low = max(0, mean_p - 2 * std_p)

    anomalies = []
    for r in readings:
        if r.power > threshold_high or r.power < threshold_low:
            anomalies.append({
                "timestamp": r.timestamp.isoformat(),
                "power": r.power,
                "voltage": r.voltage,
                "current": r.current,
                "type": "HIGH" if r.power > threshold_high else "LOW",
                "deviation": round(abs(r.power - mean_p) / std_p, 2) if std_p > 0 else 0,
            })

    return {
        "anomalies": anomalies,
        "baseline": {
            "mean_power": round(mean_p, 2),
            "std_power": round(std_p, 2),
            "threshold_high": round(threshold_high, 2),
            "threshold_low": round(threshold_low, 2),
        },
        "data_source": "CALCULATED",
    }


@router.get("/patterns")
def get_patterns(device_id: str | None = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    readings = _get_readings_range(db, week_ago, now, device_id)

    if not readings:
        return {"patterns": [], "status": "INSUFFICIENT_DATA"}

    hour_bins = {}
    for r in readings:
        h = r.timestamp.hour
        if h not in hour_bins:
            hour_bins[h] = []
        hour_bins[h].append(r.power)

    hourly_avg = []
    for h in range(24):
        if h in hour_bins and hour_bins[h]:
            hourly_avg.append({
                "hour": h,
                "avg_power": round(sum(hour_bins[h]) / len(hour_bins[h]), 2),
                "readings": len(hour_bins[h]),
            })
        else:
            hourly_avg.append({"hour": h, "avg_power": 0, "readings": 0})

    peak_hours = sorted(hourly_avg, key=lambda x: x["avg_power"], reverse=True)[:3]
    off_peak_hours = sorted(
        [h for h in hourly_avg if h["avg_power"] > 0],
        key=lambda x: x["avg_power"],
    )[:3]

    return {
        "hourly_profile": hourly_avg,
        "peak_hours": peak_hours,
        "off_peak_hours": off_peak_hours,
        "data_source": "CALCULATED",
    }
