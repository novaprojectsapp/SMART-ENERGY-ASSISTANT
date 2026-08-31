from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from ..database import Base
from ..utils.time import utcnow


class EnergyEvent(Base):
    __tablename__ = "energy_events"

    id = Column(String(64), primary_key=True)
    device_id = Column(String(64), ForeignKey("devices.id"), nullable=False)
    event_type = Column(String(32), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    value = Column(Float, nullable=True)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="events")
