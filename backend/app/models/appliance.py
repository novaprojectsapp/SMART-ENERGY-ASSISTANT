from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from ..database import Base
from ..utils.time import utcnow
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class Appliance(Base):
    __tablename__ = "appliances"

    id = Column(String(64), primary_key=True, default=new_id)
    device_id = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    type = Column(String(32), default="OTHER")
    channel = Column(Integer, default=1)
    enabled = Column(Boolean, default=True)
    control_capable = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
