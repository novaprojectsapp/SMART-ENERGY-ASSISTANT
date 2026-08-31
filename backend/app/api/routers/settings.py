from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import SystemEvent
from ...config import settings
from ...utils.time import utcnow

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("")
def get_settings():
    return {
        "app_env": settings.APP_ENV,
        "gemini_enabled": settings.GEMINI_ENABLED,
        "gemini_model": settings.GEMINI_MODEL if settings.GEMINI_ENABLED else None,
        "has_gemini_key": bool(settings.GEMINI_API_KEY),
        "log_level": settings.LOG_LEVEL,
    }


@router.get("/system-events")
def get_system_events(limit: int = 50, db: Session = Depends(get_db)):
    events = (
        db.query(SystemEvent)
        .order_by(SystemEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "severity": e.severity,
            "message": e.message,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
