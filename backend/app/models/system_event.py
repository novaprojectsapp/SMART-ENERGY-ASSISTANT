from sqlalchemy import Column, String, DateTime, Text
from ..database import Base
from ..utils.time import utcnow


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(String(64), primary_key=True)
    event_type = Column(String(32), nullable=False)
    severity = Column(String(16), default="INFO")
    message = Column(Text, nullable=False)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
