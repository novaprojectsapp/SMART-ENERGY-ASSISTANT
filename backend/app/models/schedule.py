from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from ..database import Base
from ..utils.time import utcnow
from .appliance import new_id


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String(64), primary_key=True, default=new_id)
    appliance_id = Column(String(64), nullable=False)
    action = Column(String(8), nullable=False)
    schedule_type = Column(String(16), default="DAILY")
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=True)
    days_of_week = Column(Text, default="[]")
    enabled = Column(Boolean, default=True)
    timezone = Column(String(40), default="Asia/Kolkata")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    last_executed_at = Column(DateTime, nullable=True)
    next_execution_at = Column(DateTime, nullable=True)
