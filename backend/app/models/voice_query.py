from sqlalchemy import Column, String, DateTime, Text, Float
from ..database import Base
from ..utils.time import utcnow


class VoiceQuery(Base):
    __tablename__ = "voice_queries"

    id = Column(String(64), primary_key=True)
    query_text = Column(Text, nullable=False)
    intent = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    response_text = Column(Text, nullable=True)
    source = Column(String(32), default="LOCAL")
    processing_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)
