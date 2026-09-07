from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to naive-UTC.

    SQLite round-trips datetimes as naive strings, so comparing aware
    datetimes (e.g. utcnow()) against stored values must never crash or
    silently mismatch. Everything is kept in naive-UTC internally.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
