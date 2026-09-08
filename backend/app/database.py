from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings, _resolve_database_url

DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    _safe_migrate()
    _fix_appliance_device_mappings()


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}
    ).fetchone()
    return row is not None


def _columns(conn, table: str) -> set[str]:
    try:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


# Optional new columns added to existing tables without destroying user data.
# Only columns present in this map are added; each is appended only if missing.
_MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "control_commands": {
        "command_id": "VARCHAR(64) DEFAULT ''",
        "device_id": "VARCHAR(64) DEFAULT ''",
        "channel": "INTEGER DEFAULT 1",
        "confirmed_relay_state": "VARCHAR(16) DEFAULT 'UNKNOWN'",
        "expires_at": "DATETIME",
        "dispatched_at": "DATETIME",
        "acknowledged_at": "DATETIME",
        "executed_at": "DATETIME",
        "attempt_count": "INTEGER DEFAULT 0",
    },
    "appliances": {
        "last_confirmed_state": "VARCHAR(16) DEFAULT 'UNKNOWN'",
        "last_control_at": "DATETIME",
    },
    "devices": {
        "capabilities": "TEXT DEFAULT ''",
    },
}


def _safe_migrate():
    """Add any new columns to existing tables (SQLite) without data loss."""
    if "sqlite" not in DATABASE_URL:
        return
    with engine.begin() as conn:
        for table, columns in _MIGRATION_COLUMNS.items():
            if not _table_exists(conn, table):
                continue
            existing = _columns(conn, table)
            for name, ddl in columns.items():
                if name in existing:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                except Exception:
                    # Column may already exist (race) or be non-addable; ignore safely.
                    continue


def _fix_appliance_device_mappings():
    """Repair appliance hardware mappings, never override a valid one.

    A command for an appliance with an empty/self-referencing device_id can
    never be polled by the ESP32 (control_service rejects it at creation time).
    This startup fixup binds only those broken appliances to the primary
    hardware device (ESP32-S3-01) so existing records remain controllable.
    Correct mappings to OTHER registered devices are left untouched."""
    if "sqlite" not in DATABASE_URL:
        return
    with engine.begin() as conn:
        if not _table_exists(conn, "appliances"):
            return
        try:
            conn.execute(
                text(
                    "UPDATE appliances SET device_id = :pid "
                    "WHERE device_id IS NULL OR device_id = '' OR device_id = id"
                ),
                {"pid": settings.PRIMARY_DEVICE_ID},
            )
        except Exception:
            # Non-critical: never block startup on a best-effort data repair.
            pass
