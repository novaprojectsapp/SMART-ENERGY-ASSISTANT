"""Centralized device selection.

Backend equivalent of the frontend getPrimaryDevice() helper.  When a client
does not specify a device_id, API endpoints must prefer the real ESP32 hardware
device in this order:

1. Explicitly supplied device_id
2. settings.PRIMARY_DEVICE_ID (ESP32-S3-01) when registered and active
3. An active device that has HARDWARE readings
4. Any other active registered device (fallback)
5. None
"""

from sqlalchemy.orm import Session
from ..config import settings
from ..models import Device, EnergyReading


def select_device_id(db: Session, device_id: str | None = None) -> str | None:
    if device_id:
        return device_id

    primary_id = settings.PRIMARY_DEVICE_ID
    if primary_id:
        primary = db.query(Device).filter(
            Device.id == primary_id,
            Device.is_active == True,  # noqa: E712
        ).first()
        if primary:
            return primary_id

    hw_device_ids = [
        row[0]
        for row in db.query(EnergyReading.device_id)
        .filter(EnergyReading.data_source == "HARDWARE")
        .distinct()
        .all()
    ]
    for registered in db.query(Device).filter(Device.is_active == True).all():  # noqa: E712
        if registered.id in hw_device_ids:
            return registered.id

    fallback = db.query(Device).filter(Device.is_active == True).first()  # noqa: E712
    if fallback:
        return fallback.id

    return None