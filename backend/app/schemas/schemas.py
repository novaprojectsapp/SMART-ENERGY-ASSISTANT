from pydantic import BaseModel, Field, field_validator, field_serializer, model_validator
import json
from typing import Optional
from datetime import datetime, timezone


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
    timestamp: Optional[datetime] = None
    voltage: float = Field(..., ge=0, le=500)
    current: float = Field(..., ge=0, le=100)
    power: float = Field(..., ge=0, le=50000)
    energy: float = Field(..., ge=0)
    frequency: float = Field(..., ge=0, le=100)
    power_factor: float = Field(..., ge=0, le=1.0)
    data_source: str = Field(default="HARDWARE", pattern="^(HARDWARE|SIMULATOR)$")


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


APPLIANCE_TYPES = {"BULB", "LIGHT", "FAN", "TV", "AC", "PUMP", "SOCKET", "OTHER"}
SCHEDULE_ACTIONS = {"ON", "OFF"}
SCHEDULE_TYPES = {"ONCE", "DAILY", "WEEKLY", "AFTER_DURATION"}
CONTROL_SOURCES = {"USER", "SCHEDULE", "VOICE"}
CONTROL_STATUSES = {"PENDING", "SENT", "ACKNOWLEDGED", "FAILED", "SIMULATED"}


class ApplianceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    type: str = Field(default="OTHER", max_length=32)
    channel: int = Field(default=1, ge=0, le=32)
    device_id: str = Field(default="", max_length=64)
    control_capable: bool = True

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v.upper() not in APPLIANCE_TYPES:
            raise ValueError(f"Invalid appliance type: {v}")
        return v.upper()


class ApplianceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    type: Optional[str] = Field(default=None, max_length=32)
    channel: Optional[int] = Field(default=None, ge=0, le=32)
    device_id: Optional[str] = Field(default=None, max_length=64)
    enabled: Optional[bool] = None
    control_capable: Optional[bool] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v is not None and v.upper() not in APPLIANCE_TYPES:
            raise ValueError(f"Invalid appliance type: {v}")
        return v.upper() if v else v


class ApplianceResponse(BaseModel):
    id: str
    device_id: str
    name: str
    type: str
    channel: int
    enabled: bool
    control_capable: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScheduleCreate(BaseModel):
    appliance_id: str = Field(..., min_length=1, max_length=64)
    action: str = Field(default="ON", pattern="^(ON|OFF)$")
    schedule_type: str = Field(default="DAILY", pattern="^(ONCE|DAILY|WEEKLY|AFTER_DURATION)$")
    start_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days_of_week: list[int] = Field(default_factory=list, min_length=0, max_length=7)
    enabled: bool = True
    timezone: str = Field(default="Asia/Kolkata", max_length=40)
    on_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    off_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def _apply_pair_times(self):
        # Support the ON/OFF pair concept: on_time -> start_time, off_time -> end_time.
        # Prefer explicit on_time/off_time, else fall back to start_time/end_time.
        if self.on_time is not None:
            self.start_time = self.on_time
        if self.off_time is not None:
            self.end_time = self.off_time
        # A schedule needs an ON time (start). Reject if none supplied.
        if not self.start_time:
            raise ValueError("start_time or on_time is required")
        # A schedule with an off_time (pair) always leads with ON.
        if self.end_time:
            self.action = "ON"
        return self

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v):
        for day in v:
            if day < 0 or day > 6:
                raise ValueError("days_of_week must be integers 0 (Mon) to 6 (Sun)")
        return v


class ScheduleUpdate(BaseModel):
    appliance_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    action: Optional[str] = Field(default=None, pattern="^(ON|OFF)$")
    schedule_type: Optional[str] = Field(default=None, pattern="^(ONCE|DAILY|WEEKLY|AFTER_DURATION)$")
    start_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days_of_week: Optional[list[int]] = Field(default=None, min_length=0, max_length=7)
    enabled: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, max_length=40)
    on_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    off_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def _apply_pair_times(self):
        if self.on_time is not None:
            self.start_time = self.on_time
        if self.off_time is not None:
            self.end_time = self.off_time
        if self.off_time is not None:
            self.action = "ON"
        return self

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v):
        if v is not None:
            for day in v:
                if day < 0 or day > 6:
                    raise ValueError("days_of_week must be integers 0 (Mon) to 6 (Sun)")
        return v


class ScheduleResponse(BaseModel):
    id: str
    appliance_id: str
    action: str
    schedule_type: str
    start_time: str
    end_time: Optional[str] = None
    days_of_week: list[int] = Field(default_factory=list)
    enabled: bool
    timezone: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_executed_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    on_time: Optional[str] = None
    off_time: Optional[str] = None
    next_on_at: Optional[datetime] = None
    next_off_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_validator("days_of_week", mode="before")
    @classmethod
    def _parse_days_before(cls, v):
        # DB stores days_of_week as a JSON string (Column(Text)).
        if isinstance(v, str):
            try:
                data = json.loads(v)
            except Exception:
                return []
            return data if isinstance(data, list) else []
        return v or []

    @field_serializer("days_of_week")
    def _serialize_days(self, v, _info):
        return v or []

    @model_validator(mode="before")
    @classmethod
    def _derive_pair_fields(cls, data):
        # Derive on_time/off_time from start_time/end_time when not provided.
        if isinstance(data, dict):
            if data.get("on_time") is None and data.get("start_time"):
                data["on_time"] = data["start_time"]
            if data.get("off_time") is None and data.get("end_time"):
                data["off_time"] = data["end_time"]
        return data


class ControlCommandCreate(BaseModel):
    appliance_id: str = Field(..., min_length=1, max_length=64)
    action: str = Field(..., pattern="^(ON|OFF)$")
    source: str = Field(default="USER", pattern="^(USER|SCHEDULE|VOICE)$")


class ControlCommandResponse(BaseModel):
    id: str
    appliance_id: str
    action: str
    source: str
    status: str
    message: str
    hardware_control_available: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ControlApiResponse(BaseModel):
    status: str
    command: Optional[dict] = None
    hardware_control_available: bool = False
    message: str
