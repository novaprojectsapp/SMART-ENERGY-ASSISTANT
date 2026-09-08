from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from .config import settings
from .database import init_db
from .utils.logging import setup_logging
from .paths import frontend_dir
from .services.scheduler_loop import start_scheduler_loop, stop_scheduler_loop
from .api.routers import (
    health,
    devices,
    readings,
    billing,
    analytics,
    voice,
    recommendations,
    whatif,
    settings,
    reports,
    ai_insights,
    scheduling,
)

logger = setup_logging()
FRONTEND_DIR = frontend_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Smart Energy Assistant starting...")
    init_db()
    logger.info("Database initialized")
    start_scheduler_loop()
    yield
    logger.info("Smart Energy Assistant shutting down")
    stop_scheduler_loop()
    logger.info("Background scheduler stopped")


app = FastAPI(
    title="Smart Energy Assistant",
    description="Local-First AI Energy Monitoring + Voice Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
app.include_router(settings.router)
app.include_router(reports.router)
app.include_router(ai_insights.router)
app.include_router(scheduling.router)


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
