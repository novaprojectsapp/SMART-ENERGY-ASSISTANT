import os
import sys
from pathlib import Path

APP_NAME = "SmartEnergyAssistant"
ENV_DATA_DIR = "SEA_DATA_DIR"
ENV_LOG_DIR = "SEA_LOG_DIR"


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Root of read-only application resources (frontend, tariffs, code)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent


def data_dir() -> Path:
    """Writable client-data directory (SQLite DB, runtime files)."""
    env_dir = os.environ.get(ENV_DATA_DIR)
    if env_dir:
        root = Path(env_dir).expanduser()
    elif is_frozen():
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
    else:
        root = resource_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_dir() -> Path:
    """Writable log directory. Disabled (None) unless SEALOG_DIR set."""
    root = data_dir() / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def frontend_dir() -> Path:
    return resource_dir() / "frontend"


def tariff_dir() -> Path:
    return resource_dir() / "backend" / "config" / "tariffs"


def database_path() -> Path:
    return data_dir() / "smart_energy.db"


def database_url() -> str:
    return "sqlite:///" + database_path().as_posix()