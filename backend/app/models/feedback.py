from sqlalchemy import Column, String, DateTime, Text, Integer
from ..database import Base
from ..utils.time import utcnow


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String(64), primary_key=True)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
