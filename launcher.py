"""Smart Energy Assistant - one-click Windows launcher.

Runs the FastAPI backend in-process (Linux/Windows), verifies readiness,
opens the dashboard in the default browser, and keeps a small window open
that shuts the backend down gracefully when closed.

Behavior:
- single instance guarded by a Windows mutex, with a health-signature fallback
- port 8000 busy by an unrelated app -> friendly error dialog, never killed
- SQLite database lives in the writable app-data directory and is seeded
  from the repository database only on first launch (development mode)
"""

import ctypes
import logging
import os
from logging.handlers import RotatingFileHandler
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

APP_NAME = "SmartEnergyAssistant"
HOST = "0.0.0.0"
PORT = 8000
DASHBOARD_URL = f"http://127.0.0.1:{PORT}/"
MUTEX_NAME = f"Local\\{APP_NAME}.SingleInstance"
HEALTH_TIMEOUT_SECONDS = 30.0
FIREWALL_RULE_NAME = "SmartEnergyBackend8000"

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if getattr(sys, "frozen", False):
    # Windowed PyInstaller apps have no console; the logging machinery and
    # third-party libs assume sys.stdout/stderr exist. Redirect to devnull.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    sys.path.insert(0, str(bundle_root))
    sys.path.insert(0, str(bundle_root / "backend"))

from backend.app.paths import data_dir, log_dir, resource_dir  # noqa: E402
from backend.app.utils.startup import (  # noqa: E402
    looks_like_sea_health,
    fetch_health,
    port_in_use,
    wait_until_ready,
)
from backend.app.utils.esp32_bridge import ESP32_AP_IP, ESP32_CONFIG_PORT, backend_url_for  # noqa: E402
from backend.app.utils.esp32_sync import ESP32Sync  # noqa: E402

logger = logging.getLogger("sea_launcher")

_server = None
_mutex_handle = None
_esp32_sync = None
_sync_status = None


def setup_logging(log_path: Path) -> None:
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())


def acquire_single_instance() -> bool:
    """Claim the single-instance mutex. False means another launcher is running."""
    global _mutex_handle
    try:
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        already_exists = ctypes.windll.kernel32.GetLastError() == 183
        return not already_exists
    except (AttributeError, OSError):
        return True  # non-Windows or API unavailable: rely on port probe


def has_existing_instance() -> bool:
    probe = fetch_health("127.0.0.1", PORT)
    return probe is not None and probe[0] == 200 and looks_like_sea_health(probe[1])


def show_error(title: str, message: str) -> None:
    logger.error("%s - %s", title, message)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            print(f"[{title}] {message}", file=sys.stderr)


def seed_database_if_needed() -> None:
    """Copy the development database into the app-data dir on first launch."""
    data_db = data_dir() / "smart_energy.db"
    source_db = resource_dir() / "smart_energy.db"
    if data_db.exists():
        return
    if resource_dir() == data_dir():
        return
    if not source_db.exists():
        logger.info("No seed database found; a fresh one will be created.")
        return
    logger.info("Seeding app database from %s", source_db)
    try:
        src = sqlite3.connect(str(source_db))
        dst = sqlite3.connect(str(data_db))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
    except sqlite3.Error as exc:
        logger.warning("Could not seed database (source likely in use): %s", exc)
        data_db.unlink(missing_ok=True)


def run_backend() -> None:
    import uvicorn

    from backend.app.main import app

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        access_log=False,
        workers=1,
    )
    global _server
    _server = uvicorn.Server(config)
    _server.run()


def request_shutdown() -> None:
    if _server is not None:
        _server.should_exit = True


def ensure_firewall_rule() -> bool:
    """Best-effort: allow inbound TCP 8000 on Private + Public profiles.

    Uses the existing rule name SmartEnergyBackend8000. Requires admin rights;
    when unavailable this fails silently and logs a warning (the backend still
    works, but ESP32 uploads need the rule present on clean client machines).
    """
    netsh = ["netsh", "advfirewall", "firewall"]
    try:
        probe = subprocess.run(
            netsh + ["show", "rule", f"name={FIREWALL_RULE_NAME}"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        exists = FIREWALL_RULE_NAME.lower() in probe.stdout.lower()
        if exists:
            logger.info("Firewall rule '%s' already exists.", FIREWALL_RULE_NAME)
            return True
        add = subprocess.run(
            netsh + [
                "add", "rule",
                f"name={FIREWALL_RULE_NAME}",
                "dir=in", "action=allow",
                "protocol=TCP", f"localport={PORT}",
                "profile=private,public",
                "enable=yes",
            ],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if add.returncode == 0:
            logger.info("Firewall rule '%s' added (TCP %s).", FIREWALL_RULE_NAME, PORT)
            return True
        logger.warning(
            "Could not add firewall rule (rc=%s): %s",
            add.returncode, add.stderr.strip()[:300],
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Firewall rule setup skipped: %s", exc)
    return False


def start_esp32_sync() -> None:
    """Start the background ESP32 backend auto-configuration service."""
    global _esp32_sync
    if _esp32_sync is not None and _esp32_sync.is_alive():
        return
    _esp32_sync = ESP32Sync(port=PORT, interval=2.0, on_status=on_sync_status)
    _esp32_sync.start()
    logger.info("ESP32 auto-config service started (AP %s:%s).", ESP32_AP_IP, ESP32_CONFIG_PORT)


def on_sync_status(status) -> None:
    """Store the latest ESP32 sync state for the status window."""
    global _sync_status
    _sync_status = status


def main() -> int:
    try:
        app_data = data_dir()
        logs = log_dir()
        app_data.mkdir(parents=True, exist_ok=True)
        os.environ["SEA_DATA_DIR"] = str(app_data)
        os.environ["SEA_LOG_DIR"] = str(logs)

        log_path = logs / "launcher.log"
        setup_logging(log_path)

        logger.info("=== Smart Energy Assistant launcher starting ===")
        logger.info("App data dir: %s", app_data)
        logger.info("Resource dir: %s", resource_dir())

        if not acquire_single_instance():
            logger.info("Another instance is already running; focus its dashboard.")
            webbrowser.open(DASHBOARD_URL)
            return 0

        if port_in_use(HOST, PORT):
            if has_existing_instance():
                logger.info("Port %s hosts a running Smart Energy Assistant.", PORT)
                webbrowser.open(DASHBOARD_URL)
                return 0
            show_error(
                "Smart Energy Assistant could not start",
                "Port 8000 is already being used.\n\n"
                "Please close the application that is using port 8000 and try again.",
            )
            return 1

        seed_database_if_needed()
        ensure_firewall_rule()

        server_thread = threading.Thread(target=run_backend, name="sea-backend", daemon=True)
        server_thread.start()

        ready, elapsed, last_probe = wait_until_ready(PORT, timeout=HEALTH_TIMEOUT_SECONDS)
        if not ready:
            show_error(
                "Smart Energy Assistant could not start",
                "The backend did not become ready within 30 seconds.\n\n"
                "See the launcher log for details:\n"
                f"{logs / 'launcher.log'}",
            )
            return 1
        logger.info("Backend ready after %.1fs; opening dashboard.", elapsed)

        start_esp32_sync()
        webbrowser.open(DASHBOARD_URL)

        try:
            import tkinter as tk

            root = tk.Tk()
            root.title(APP_NAME)
            root.resizable(False, False)

            tk.Label(
                root,
                text="Smart Energy Assistant is running.",
                font=("Segoe UI", 11, "bold"),
                padx=24, pady=(16, 4),
            ).pack()
            tk.Label(
                root,
                text=f"Dashboard: {DASHBOARD_URL}",
                font=("Segoe UI", 9), justify="left", padx=24, pady=4,
            ).pack()

            sync_label = tk.Label(
                root,
                text="Detecting laptop network address...",
                font=("Segoe UI", 9), justify="left", wraplength=440,
                padx=24, pady=(4, 8),
            )
            sync_label.pack()

            buttons = tk.Frame(root, padx=24, pady=(8, 16))
            buttons.pack()
            tk.Button(buttons, text="Open Dashboard", width=18, command=lambda: webbrowser.open(DASHBOARD_URL)).pack(side="left", padx=6)
            tk.Button(buttons, text="Exit", width=12, command=root.destroy).pack(side="left", padx=6)

            def refresh_sync():
                s = _sync_status
                if s is None:
                    sync_label.configure(text="Detecting laptop network address...")
                else:
                    url = s.get("backend_url") or "not detected"
                    msg = s.get("message") or ""
                    online = s.get("online")
                    state_line = ("ESP32 configured: YES - Device Online" if online
                                  else "ESP32 configured: NO")
                    sync_label.configure(
                        text=f"Laptop backend URL: {url}\n{msg}\n{state_line}"
                    )
                root.after(1000, refresh_sync)

            root.after(200, refresh_sync)
            root.protocol("WM_DELETE_WINDOW", root.destroy)
            root.mainloop()
        except Exception:
            logger.info("Tk unavailable; running headless until process is closed.")
            threading.Event().wait()

        logger.info("Launcher shutting down.")
        if _esp32_sync is not None:
            _esp32_sync.stop()
        request_shutdown()
        if server_thread.is_alive():
            server_thread.join(timeout=10)
        logger.info("Backend stopped. Goodbye.")
        return 0

    except Exception as exc:  # noqa: BLE001 - top-level guard
        logger.exception("Fatal launcher error")
        show_error(
            "Smart Energy Assistant could not start",
            f"An unexpected error occurred.\n\n{exc}\n\nSee the launcher log for details.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())