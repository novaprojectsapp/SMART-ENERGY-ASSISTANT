from sqlalchemy import Column, String, DateTime, Float, Boolean, Text, Integer
from ..database import Base
from ..utils.time import utcnow


class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(String(64), primary_key=True)
    model_version = Column(String(32), nullable=False)
    model_type = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    training_source = Column(String(32), nullable=False)
    dataset_version = Column(String(32), nullable=True)
    features = Column(Text, nullable=False)
    classes = Column(Text, nullable=False)
    training_sessions = Column(Integer, default=0)
    validation_sessions = Column(Integer, default=0)
    accuracy = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    hardware_validated = Column(Boolean, default=False)
    status = Column(String(16), default="DRAFT")
    file_path = Column(Text, nullable=True)
    notes = Column(Text, default="")
