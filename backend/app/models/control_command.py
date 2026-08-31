from sqlalchemy import Column, String, Boolean, DateTime, Text
from ..database import Base
from ..utils.time import utcnow
from .appliance import new_id


class ControlCommand(Base):
    __tablename__ = "control_commands"

    id = Column(String(64), primary_key=True, default=new_id)
    appliance_id = Column(String(64), nullable=False)
    action = Column(String(8), nullable=False)
    source = Column(String(16), default="USER")
    status = Column(String(16), default="PENDING")
    message = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
