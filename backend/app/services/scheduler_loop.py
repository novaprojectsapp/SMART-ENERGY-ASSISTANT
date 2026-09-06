"""
Background scheduler loop.

Starts automatically with the FastAPI lifespan so schedules execute while the
backend/EXE is running - no manual /scheduler/run needed. The loop is:

- a single daemon thread (started at most once; duplicate-start guarded)
- non-blocking for FastAPI (runs in its own thread)
- creates its own DB session per iteration and closes it
- survives a failed iteration (errors are logged, loop continues)
- stops gracefully on shutdown via a threading.Event

Disabled when APP_TESTING=1 so the test suite stays deterministic.
"""
import logging
import os
import threading
import time

from ..database import SessionLocal
from ..models import ControlCommand
from .scheduler import SchedulerService

logger = logging.getLogger("smart_energy.scheduler_loop")

DEFAULT_INTERVAL_SECONDS = 1.0


class SchedulerLoop:
    def __init__(self, interval_seconds: float = DEFAULT_INTERVAL_SECONDS):
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> bool:
        if self._started:
            logger.info("Scheduler loop already started; ignoring duplicate start.")
            return False
        if os.environ.get("APP_TESTING") == "1":
            logger.info("Scheduler loop disabled (APP_TESTING=1).")
            return False
        self._started = True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="sea-scheduler-loop",
            daemon=True,
        )
        self._thread.start()
        logger.info("Background scheduler loop started (interval %.1fs).", self.interval)
        return True

    def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._started = False
        self._thread = None
        logger.info("Background scheduler loop stopped.")

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._iteration()
            except Exception:  # noqa: BLE001 - survive a failed iteration
                logger.exception("Scheduler iteration failed; continuing loop.")
            elapsed = time.monotonic() - started
            sleep_for = max(0.0, self.interval - elapsed)
            if sleep_for > 0:
                self._stop.wait(timeout=sleep_for)

    def _iteration(self) -> None:
        db = SessionLocal()
        try:
            svc = SchedulerService(db)
            commands = svc.run_due()
            for c in commands:
                logger.info("Background scheduler created command %s (%s %s)", c.id, c.action, c.source)
        finally:
            db.close()


_scheduler_loop = SchedulerLoop()


def start_scheduler_loop() -> bool:
    """Start the global scheduler loop once. Returns True if started."""
    return _scheduler_loop.start()


def stop_scheduler_loop(timeout: float = 5.0) -> None:
    _scheduler_loop.stop(timeout=timeout)


def scheduler_loop_running() -> bool:
    return _scheduler_loop._started and bool(_scheduler_loop._thread and _scheduler_loop._thread.is_alive())