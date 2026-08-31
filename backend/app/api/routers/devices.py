from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
from ...database import get_db
from ...models import Device, EnergyReading
from ...schemas.schemas import DeviceCreate, DeviceResponse
from ...utils.time import utcnow
import logging

logger = logging.getLogger("smart_energy.api.devices")
router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


def _device_status(device: Device, db: Session) -> str:
    if device.last_seen is None:
        return "NO_DATA"
    now = utcnow()
    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    threshold = now - timedelta(minutes=5)
    if last_seen >= threshold:
        return "ONLINE"
    return "OFFLINE"


@router.post("", response_model=DeviceResponse, status_code=201)
def register_device(device_in: DeviceCreate, db: Session = Depends(get_db)):
    existing = db.query(Device).filter(Device.id == device_in.id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Device '{device_in.id}' already registered")

    device = Device(
        id=device_in.id,
        name=device_in.name,
        device_type=device_in.device_type,
        location=device_in.location,
        notes=device_in.notes,
        created_at=utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    logger.info("Device registered: %s (%s)", device.id, device.name)

    resp = DeviceResponse.model_validate(device)
    resp.status = _device_status(device, db)
    return resp


@router.get("", response_model=list[DeviceResponse])
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.is_active == True).all()
    result = []
    for d in devices:
        resp = DeviceResponse.model_validate(d)
        resp.status = _device_status(d, db)
        result.append(resp)
    return result


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(device_id: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    resp = DeviceResponse.model_validate(device)
    resp.status = _device_status(device, db)
    return resp


@router.get("/{device_id}/status")
def get_device_status(device_id: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    latest = (
        db.query(EnergyReading)
        .filter(EnergyReading.device_id == device_id)
        .order_by(EnergyReading.timestamp.desc())
        .first()
    )

    return {
        "device_id": device_id,
        "status": _device_status(device, db),
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "latest_reading": {
            "timestamp": latest.timestamp.isoformat(),
            "power": latest.power,
            "voltage": latest.voltage,
            "current": latest.current,
        } if latest else None,
    }
