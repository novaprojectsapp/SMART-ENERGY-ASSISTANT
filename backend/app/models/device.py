from sqlalchemy import Column, String, DateTime, Boolean, Text, Float, Integer
from sqlalchemy.orm import relationship
from ..database import Base
from ..utils.time import utcnow


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    device_type = Column(String(32), default="PZEM-004T")
    location = Column(String(128), default="")
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    notes = Column(Text, default="")

    readings = relationship("EnergyReading", back_populates="device", cascade="all, delete-orphan")
    events = relationship("EnergyEvent", back_populates="device", cascade="all, delete-orphan")
