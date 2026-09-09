from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from .config import settings
from .database import engine, init_db
from .utils.logging import setup_logging
from .paths import database_path, frontend_dir, is_frozen, resource_dir
from .services.scheduler_loop import start_scheduler_loop, stop_scheduler_loop
from .utils import udp_discovery
from .api.routers import (
    health,
    devices,
    readings,
    billing,
    analytics,
    voice,
    recommendations,
    whatif,
    reports,
    ai_insights,
    scheduling,
    setup,
)
from .api.routers import settings as settings_router  # noqa: E402 - avoids shadowing config settings

logger = setup_logging()
FRONTEND_DIR = frontend_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Smart Energy Assistant starting...")
    _log_startup_diagnostics()
    init_db()
    logger.info("Database initialized")
    start_scheduler_loop()
    udp_discovery.start_broadcaster()
    logger.info("UDP backend discovery broadcaster started on port %d", udp_discovery.DISCOVERY_PORT)
    yield
    logger.info("Smart Energy Assistant shutting down")
    udp_discovery.stop_broadcaster()
    stop_scheduler_loop()
    logger.info("Background scheduler stopped")


def _log_startup_diagnostics() -> None:
    """Log the single source of truth for the runtime database.

    The dashboard never exposes these internal paths; they are written to the
    application logs only (launcher.log in dev, %LOCALAPPDATA%\\SmartEnergyAssistant\\logs
    in the packaged EXE) so a support session can confirm which database file the
    live backend is actually using.
    """
    db_path = database_path()
    db_url = engine.url.render_as_string(hide_password=True)
    logger.info("DATABASE PATH: %s", db_path)
    logger.info("DATABASE EXISTS: %s", db_path.exists())
    logger.info("DATABASE MODE: %s", "FROZEN" if is_frozen() else "DEVELOPMENT")
    logger.info("DATABASE URL: %s", db_url)
    logger.info("PRIMARY DEVICE ID: %s", settings.PRIMARY_DEVICE_ID)
    logger.info("RESOURCE DIR: %s", resource_dir())
    logger.info("UDP DISCOVERY: %s:%s (broadcast %s, subnet 192.168.4.0/24)",
                udp_discovery.DISCOVERY_SERVICE, udp_discovery.DISCOVERY_PORT,
                udp_discovery.DISCOVERY_BROADCAST_IP)


app = FastAPI(
    title="Smart Energy Assistant",
    description="Local-First AI Energy Monitoring + Voice Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# Local-first same-origin app: the dashboard is served by this backend, so the
# browser never needs to send credentials cross-origin. Wildcard origins are
# intentional (allows file:// and dev-served frontends), but credentials are
# explicitly disabled -- a wildcard + credentials combination is rejected by
# browsers and is a broken/unsafe configuration.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(devices.router)
app.include_router(readings.router)
app.include_router(billing.router)
app.include_router(analytics.router)
app.include_router(voice.router)
app.include_router(recommendations.router)
app.include_router(whatif.router)
app.include_router(settings_router.router)
app.include_router(reports.router)
app.include_router(ai_insights.router)
app.include_router(scheduling.router)
app.include_router(setup.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    if getattr(settings, "APP_ENV", "development") == "development":
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc), "code": "INTERNAL_ERROR"},
        )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
    )


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
