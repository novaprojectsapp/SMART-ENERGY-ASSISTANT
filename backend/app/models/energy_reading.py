from sqlalchemy import Column, String, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from ..database import Base
from ..utils.time import utcnow


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id = Column(String(64), primary_key=True)
    device_id = Column(String(64), ForeignKey("devices.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    voltage = Column(Float, nullable=False)
    current = Column(Float, nullable=False)
    power = Column(Float, nullable=False)
    energy = Column(Float, nullable=False)
    frequency = Column(Float, nullable=False)
    power_factor = Column(Float, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    data_source = Column(String(32), default="HARDWARE")

    device = relationship("Device", back_populates="readings")

    __table_args__ = (
        UniqueConstraint("device_id", "timestamp", name="uq_device_timestamp"),
    )
