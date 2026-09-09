from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from ...database import get_db
from ...models import Device, EnergyReading
from ...schemas.schemas import DeviceCreate, DeviceResponse
from ...utils.time import utcnow, to_iso
from ...utils.freshness import freshness_status
from ...utils.capabilities import normalize_capabilities, encode_capabilities
import logging

logger = logging.getLogger("smart_energy.api.devices")
router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


def _device_status(device: Device, db: Session) -> str:
    return freshness_status(device.last_seen)


@router.post("", response_model=DeviceResponse, status_code=201)
def register_device(device_in: DeviceCreate, response: Response, db: Session = Depends(get_db)):
    caps_json = encode_capabilities(device_in.capabilities)
    existing = db.query(Device).filter(Device.id == device_in.id).first()
    if existing:
        # Idempotent re-registration: the same device registering again (e.g. the
        # ESP32 re-registers after every power cycle / backend reconfiguration)
        # refreshes the self-declared capabilities and name and returns 200.
        # The 409 (conflict) contract was removed so clients never special-case a
        # "device already known" response -- 201 = created, 200 = already known.
        existing.capabilities = caps_json
        if device_in.name:
            existing.name = device_in.name
        db.commit()
        db.refresh(existing)
        resp = DeviceResponse.model_validate(existing)
        resp.status = _device_status(existing, db)
        response.status_code = status.HTTP_200_OK
        logger.info("Device re-registered (idempotent 200): %s", existing.id)
        return resp

    device = Device(
        id=device_in.id,
        name=device_in.name,
        device_type=device_in.device_type,
        location=device_in.location,
        notes=device_in.notes,
        capabilities=caps_json,
        created_at=utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    logger.info(
        "Device registered: %s (%s) capabilities=%s",
        device.id, device.name, normalize_capabilities(caps_json),
    )

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
        "last_seen": to_iso(device.last_seen) if device.last_seen else None,
        "latest_reading": {
            "timestamp": to_iso(latest.timestamp),
            "power": latest.power,
            "voltage": latest.voltage,
            "current": latest.current,
        } if latest else None,
    }
