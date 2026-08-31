from sqlalchemy import Column, String, DateTime, Float, Text
from ..database import Base
from ..utils.time import utcnow


class BillingRecord(Base):
    __tablename__ = "billing_records"

    id = Column(String(64), primary_key=True)
    device_id = Column(String(64), nullable=True)
    period_type = Column(String(32), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    total_kwh = Column(Float, nullable=False)
    energy_charge = Column(Float, nullable=False)
    tariff_version = Column(String(32), nullable=False)
    slab_breakdown = Column(Text, nullable=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
