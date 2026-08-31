from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from ...database import get_db
from ...config import settings
from ...schemas.schemas import HealthResponse
import time

router = APIRouter(prefix="/api/v1/health", tags=["health"])

_start_time = time.time()


@router.get("", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        version="1.0.0",
        database=db_status,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
