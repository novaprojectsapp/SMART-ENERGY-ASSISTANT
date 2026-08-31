from sqlalchemy import Column, String, DateTime, Float, Text, Integer
from ..database import Base
from ..utils.time import utcnow


class AIPrediction(Base):
    __tablename__ = "ai_predictions"

    id = Column(String(64), primary_key=True)
    prediction_type = Column(String(32), nullable=False)
    device_id = Column(String(64), nullable=True)
    timestamp = Column(DateTime, nullable=False)
    period = Column(String(32), nullable=False)
    input_window_days = Column(Integer, nullable=True)
    avg_daily_kwh = Column(Float, nullable=True)
    projected_kwh = Column(Float, nullable=True)
    calculated_charge = Column(Float, nullable=True)
    tariff_version = Column(String(32), nullable=True)
    basis = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
