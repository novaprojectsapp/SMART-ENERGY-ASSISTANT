from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer
from ..database import Base
from ..utils.time import utcnow
from .appliance import new_id


class ControlCommand(Base):
    __tablename__ = "control_commands"

    id = Column(String(64), primary_key=True, default=new_id)

    # Unique public command identifier sent to the ESP32 (uuid).
    command_id = Column(String(64), nullable=False, default=new_id)

    device_id = Column(String(64), nullable=False, default="")
    appliance_id = Column(String(64), nullable=False)
    channel = Column(Integer, default=1)
    action = Column(String(8), nullable=False)
    source = Column(String(16), default="USER")

    # Lifecycle state: PENDING -> (DISPATCHED) -> EXECUTED | FAILED | EXPIRED
    status = Column(String(16), default="PENDING")
    message = Column(Text, default="")

    # Confirmed relay state after ESP32 acknowledgement ("ON"/"OFF"/"UNKNOWN").
    confirmed_relay_state = Column(String(16), default="UNKNOWN")

    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0)
