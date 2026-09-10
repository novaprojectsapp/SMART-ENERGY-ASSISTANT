"""
Build a structured, data-safe context dict for AI response composition.

All values come from the database and trusted business logic.
No external API or LLM is consulted during context construction.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..billing.engine import load_tariff, calculate_billing, TariffConfig
from ..models import Device
from ..utils.device_selection import select_device_id
from .data_access import (
    get_latest_reading,
    get_today_readings,
    get_recent_readings,
    calc_daily_energy,
    get_energy_kwh,
)


def _safe_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    if seconds < 3600:
        return f"{int(seconds / 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds / 3600)} hours ago"
    return f"{int(seconds / 86400)} days ago"


class ContextBuilder:
    """Assembles a trusted data context for a voice query."""

    def __init__(self, db: Session, device_id: str | None = None):
        self.db = db
        self.device_id = select_device_id(db, device_id)
        self.now = datetime.now(timezone.utc)

    def build(self) -> dict:
        ctx: dict = {"query": "", "device": {}, "live": {}, "today": {}, "recent": {}, "billing": {}, "tariff": {}, "safety": {}}

        self._build_device(ctx)
        self._build_live(ctx)
        self._build_today(ctx)
        self._build_recent(ctx)
        self._build_billing(ctx)
        self._build_safety(ctx)

        return ctx

    def _build_device(self, ctx: dict):
        if not self.device_id:
            ctx["device"] = {"available": False}
            return
        device = self.db.query(Device).filter(Device.id == self.device_id).first()
        if not device:
            ctx["device"] = {"available": False}
            return
        online = False
        age_seconds = None
        if device.last_seen:
            age_seconds = (self.now - device.last_seen.replace(tzinfo=timezone.utc)).total_seconds()
            online = age_seconds < 300
        ctx["device"] = {
            "id": device.id,
            "name": device.name,
            "online": online,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "last_seen_age": _format_age(age_seconds) if age_seconds is not None else "never",
        }

    def _build_live(self, ctx: dict):
        latest = get_latest_reading(self.db, self.device_id)
        if not latest:
            ctx["live"] = {"available": False}
            return
        age_seconds = (self.now - latest.timestamp.replace(tzinfo=timezone.utc)).total_seconds()
        ctx["live"] = {
            "available": True,
            "voltage": _safe_float(latest.voltage),
            "current": _safe_float(latest.current),
            "power_w": _safe_float(latest.power),
            "energy_kwh": _safe_float(latest.energy),
            "frequency": _safe_float(latest.frequency),
            "power_factor": _safe_float(latest.power_factor),
            "timestamp": latest.timestamp.isoformat(),
            "age": _format_age(age_seconds),
        }

    def _build_today(self, ctx: dict):
        today_readings = get_today_readings(self.db, self.device_id)
        today_kwh = calc_daily_energy(today_readings)

        tariff = None
        try:
            tariff = load_tariff()
        except Exception:
            pass

        cost_inr = None
        if tariff and today_kwh > 0:
            try:
                billing = calculate_billing(today_kwh, tariff, "daily")
                cost_inr = billing.total_charge
            except Exception:
                pass

        avg_power = None
        peak_power = None
        if today_readings:
            powers = [r.power for r in today_readings]
            avg_power = sum(powers) / len(powers) if powers else None
            peak_power = max(powers) if powers else None

        ctx["today"] = {
            "energy_kwh": round(today_kwh, 4) if today_kwh else 0.0,
            "cost_inr": round(cost_inr, 2) if cost_inr is not None else None,
            "reading_count": len(today_readings),
            "avg_power_w": round(avg_power, 1) if avg_power is not None else None,
            "peak_power_w": round(peak_power, 1) if peak_power is not None else None,
        }

    def _build_recent(self, ctx: dict):
        recent_7d = get_recent_readings(self.db, days=7, device_id=self.device_id)
        if not recent_7d:
            ctx["recent"] = {"available": False}
            return

        powers = [r.power for r in recent_7d]
        avg_power = sum(powers) / len(powers) if powers else 0
        peak_power = max(powers) if powers else 0

        recent_kwh = get_energy_kwh(
            self.db,
            self.now - timedelta(days=7),
            self.now,
            self.device_id,
        )
        avg_daily = recent_kwh / 7.0 if recent_kwh > 0 else 0

        ctx["recent"] = {
            "available": True,
            "days": 7,
            "average_power_w": round(avg_power, 1),
            "peak_power_w": round(peak_power, 1),
            "energy_kwh": round(recent_kwh, 4),
            "avg_daily_kwh": round(avg_daily, 4),
        }

    def _build_billing(self, ctx: dict):
        tariff = None
        try:
            tariff = load_tariff()
        except Exception:
            pass

        if not tariff:
            ctx["billing"] = {"available": False}
            ctx["tariff"] = {"available": False}
            return

        recent_kwh = get_energy_kwh(
            self.db,
            self.now - timedelta(days=7),
            self.now,
            self.device_id,
        )

        if recent_kwh <= 0:
            ctx["billing"] = {"available": False, "reason": "insufficient_data"}
            ctx["tariff"] = {
                "available": True,
                "currency": tariff.currency,
                "name": tariff.tariff_name,
                "billing_period_months": tariff.billing_period_months,
            }
            return

        avg_daily = recent_kwh / 7.0
        monthly_kwh = avg_daily * 30
        billing_period_kwh = avg_daily * (tariff.billing_period_months * 30)

        monthly_billing = calculate_billing(monthly_kwh, tariff, "monthly_equivalent")
        period_billing = calculate_billing(billing_period_kwh, tariff, "billing_period")

        ctx["billing"] = {
            "available": True,
            "monthly_projection_inr": monthly_billing.total_charge,
            "billing_period_projection_inr": period_billing.total_charge,
            "billing_period_months": tariff.billing_period_months,
            "monthly_projected_kwh": round(monthly_kwh, 2),
            "billing_period_projected_kwh": round(billing_period_kwh, 2),
        }
        ctx["tariff"] = {
            "available": True,
            "currency": tariff.currency,
            "name": tariff.tariff_name,
            "billing_period_months": tariff.billing_period_months,
        }

    def _build_safety(self, ctx: dict):
        ctx["safety"] = {
            "over_voltage_active": False,
            "voltage_cutoff_v": 250.0,
            "recovery_voltage_v": 240.0,
        }
        live = ctx.get("live", {})
        if live.get("available") and live.get("voltage") is not None:
            if live["voltage"] > 250.0:
                ctx["safety"]["over_voltage_active"] = True
