from sqlalchemy.orm import Session
from ..models import EnergyReading, Device
from datetime import datetime, timedelta, timezone


def get_latest_reading(db: Session, device_id: str | None = None) -> EnergyReading | None:
    query = db.query(EnergyReading)
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)
    return query.order_by(EnergyReading.timestamp.desc()).first()


def get_today_readings(db: Session, device_id: str | None = None) -> list[EnergyReading]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    query = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= now,
    )
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)
    return query.order_by(EnergyReading.timestamp.asc()).all()


def get_recent_readings(db: Session, days: int = 7, device_id: str | None = None) -> list[EnergyReading]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    query = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= now,
    )
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)
    return query.order_by(EnergyReading.timestamp.asc()).all()


def calc_daily_energy(readings: list[EnergyReading]) -> float:
    if len(readings) < 2:
        return 0.0
    return max(0.0, readings[-1].energy - readings[0].energy)


def get_energy_kwh(db: Session, start: datetime, end: datetime, device_id: str | None = None) -> float:
    query = db.query(EnergyReading).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.timestamp <= end,
    )
    if device_id:
        query = query.filter(EnergyReading.device_id == device_id)
    readings = query.order_by(EnergyReading.timestamp.asc()).all()
    return calc_daily_energy(readings)
