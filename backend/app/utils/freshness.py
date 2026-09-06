from datetime import datetime, timezone, timedelta


CONNECTED_THRESHOLD_SECONDS = 10
STALE_THRESHOLD_SECONDS = 60

CONNECTED = "CONNECTED"
STALE = "STALE"
OFFLINE = "OFFLINE"
NO_DATA = "NO_DATA"


def ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_seconds(dt: datetime, now: datetime = None) -> float:
    dt = ensure_utc(dt)
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = ensure_utc(now)
    if dt is None:
        return None
    return (now - dt).total_seconds()


def freshness_status(dt: datetime, now: datetime = None) -> str:
    if dt is None:
        return NO_DATA
    age = age_seconds(dt, now)
    if age < CONNECTED_THRESHOLD_SECONDS:
        return CONNECTED
    if age < STALE_THRESHOLD_SECONDS:
        return STALE
    return OFFLINE


def is_connected(dt: datetime, now: datetime = None) -> bool:
    return freshness_status(dt, now) == CONNECTED