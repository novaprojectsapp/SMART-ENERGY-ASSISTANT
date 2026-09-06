from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import Device, EnergyReading
from ...schemas.schemas import ReadingCreate, ReadingResponse
from ...utils.time import utcnow
from ...utils.freshness import freshness_status
from ...utils.validation import validate_reading
from ...config import settings
import uuid
import logging

logger = logging.getLogger("smart_energy.api.readings")
router = APIRouter(prefix="/api/v1", tags=["readings"])


@router.post("/devices/{device_id}/readings", response_model=ReadingResponse, status_code=201)
def ingest_reading(device_id: str, reading_in: ReadingCreate, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    errors = validate_reading(reading_in)
    if errors:
        raise HTTPException(status_code=422, detail=f"Invalid reading: {'; '.join(errors)}")

    # ESP32 devices in AP mode have no reliable clock; use backend wall-clock time
    # when the device does not supply a timestamp.
    if reading_in.timestamp is None:
        reading_in.timestamp = utcnow()

    existing = (
        db.query(EnergyReading)
        .filter(EnergyReading.device_id == device_id, EnergyReading.timestamp == reading_in.timestamp)
        .first()
    )
    if existing:
        logger.debug("Duplicate reading skipped: device=%s ts=%s", device_id, reading_in.timestamp)
        return ReadingResponse.model_validate(existing)

    reading = EnergyReading(
        id=str(uuid.uuid4()),
        device_id=device_id,
        timestamp=reading_in.timestamp,
        voltage=reading_in.voltage,
        current=reading_in.current,
        power=reading_in.power,
        energy=reading_in.energy,
        frequency=reading_in.frequency,
        power_factor=reading_in.power_factor,
        data_source=reading_in.data_source,
        created_at=utcnow(),
    )
    db.add(reading)

    device.last_seen = utcnow()
    db.commit()
    db.refresh(reading)

    logger.info("Reading ingested: device=%s power=%.2fW", device_id, reading.power)
    return ReadingResponse.model_validate(reading)


@router.get("/devices/{device_id}/readings", response_model=list[ReadingResponse])
def get_readings(
    device_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    readings = (
        db.query(EnergyReading)
        .filter(EnergyReading.device_id == device_id)
        .order_by(EnergyReading.timestamp.desc())
        .limit(limit)
        .all()
    )
    return readings


@router.get("/readings/latest", response_model=list[ReadingResponse])
def get_latest_readings(db: Session = Depends(get_db)):
    from sqlalchemy import text
    from datetime import timezone as _tz
    result = db.execute(
        text("""
            SELECT er.* FROM energy_readings er
            INNER JOIN (
                SELECT device_id, MAX(timestamp) as max_ts
                FROM energy_readings GROUP BY device_id
            ) latest ON er.device_id = latest.device_id AND er.timestamp = latest.max_ts
        """)
    ).fetchall()

    now = utcnow()
    readings = []
    for row in result:
        reading = ReadingResponse.model_validate(dict(row._mapping))
        ts = reading.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        reading.age_seconds = (now - ts).total_seconds()
        reading.status = freshness_status(ts, now)
        readings.append(reading)

    primary_id = settings.PRIMARY_DEVICE_ID

    def _priority(r: ReadingResponse) -> int:
        if r.data_source == "HARDWARE" and r.device_id == primary_id:
            return 0
        if r.data_source == "HARDWARE":
            return 1
        return 2

    readings.sort(key=lambda r: (_priority(r), -_ts_sort_key(r.timestamp)))
    return readings


def _ts_sort_key(dt) -> float:
    from datetime import timezone as _tz
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.timestamp()
