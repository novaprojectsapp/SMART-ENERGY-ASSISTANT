from sqlalchemy import Column, String, DateTime, Text, Float, Boolean
from ..database import Base
from ..utils.time import utcnow


class TariffSetting(Base):
    __tablename__ = "tariff_settings"

    id = Column(String(64), primary_key=True)
    tariff_name = Column(String(128), nullable=False)
    region = Column(String(64), nullable=False)
    version = Column(String(32), nullable=False)
    effective_date = Column(DateTime, nullable=True)
    currency = Column(String(8), default="INR")
    tariff_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
