from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    database: str = "connected"
    uptime_seconds: float = 0.0


class DeviceCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    device_type: str = Field(default="PZEM-004T", max_length=32)
    location: str = Field(default="", max_length=128)
    notes: str = Field(default="", max_length=512)


class DeviceResponse(BaseModel):
    id: str
    name: str
    device_type: str
    location: str
    is_active: bool
    last_seen: Optional[datetime] = None
    created_at: datetime
    notes: str
    status: str = "NO_DATA"

    class Config:
        from_attributes = True


class ReadingCreate(BaseModel):
    timestamp: datetime
    voltage: float = Field(..., ge=0, le=500)
    current: float = Field(..., ge=0, le=100)
    power: float = Field(..., ge=0, le=50000)
    energy: float = Field(..., ge=0)
    frequency: float = Field(..., ge=0, le=100)
    power_factor: float = Field(..., ge=0, le=1.0)


class ReadingResponse(BaseModel):
    id: str
    device_id: str
    timestamp: datetime
    voltage: float
    current: float
    power: float
    energy: float
    frequency: float
    power_factor: float
    created_at: datetime
    data_source: str

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: str = "UNKNOWN_ERROR"
