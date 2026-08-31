from sqlalchemy import Column, String, DateTime, Float, Boolean, Text, Integer
from ..database import Base
from ..utils.time import utcnow


class ApplianceActivity(Base):
    __tablename__ = "appliance_activity"

    id = Column(String(64), primary_key=True)
    device_id = Column(String(64), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    appliance_states = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    model_version = Column(String(32), nullable=True)
    is_hardware_validated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
