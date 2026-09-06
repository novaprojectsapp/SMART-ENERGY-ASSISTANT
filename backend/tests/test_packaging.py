import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.app.paths import (  # noqa: E402
    APP_NAME,
    database_path,
    database_url,
    data_dir,
    frontend_dir,
    resource_dir,
    tariff_dir,
)
from backend.app.utils.startup import (  # noqa: E402
    HEALTH_PATH,
    looks_like_sea_health,
    port_in_use,
    readiness_url,
)


def test_resource_dir_contains_repo_layout():
    assert (resource_dir() / "frontend").is_dir()
    assert (frontend_dir() / "index.html").exists()


def test_tariff_dir_contains_tariff_json():
    assert (tariff_dir() / "tamil_nadu_domestic.json").exists()


def test_data_dir_env_override(tmp_path, monkeypatch):
    target = tmp_path / "sea-data"
    monkeypatch.setenv("SEA_DATA_DIR", str(target))
    assert data_dir() == target
    assert target.is_dir()


def test_data_dir_defaults_to_repo_root_in_dev(monkeypatch):
    monkeypatch.delenv("SEA_DATA_DIR", raising=False)
    assert data_dir() == resource_dir()


def test_database_path_and_url_follow_data_dir(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "sea-data"
    monkeypatch.setenv("SEA_DATA_DIR", str(target))
    assert database_path() == target / "smart_energy.db"
    assert database_url() == "sqlite:///" + (target / "smart_energy.db").as_posix()


def test_database_url_is_absolute():
    url = database_url()
    assert url.startswith("sqlite:///")
    path = url[len("sqlite:///") :]
    assert "://" not in path


def test_log_dir_under_application_name(tmp_path, monkeypatch):
    monkeypatch.setenv("SEA_DATA_DIR", str(tmp_path))
    from backend.app.paths import log_dir

    assert log_dir() == tmp_path / "logs"


def test_readiness_url_and_health_path():
    assert HEALTH_PATH == "/api/v1/health"
    assert readiness_url(8000) == "http://127.0.0.1:8000/api/v1/health"


def test_looks_like_sea_health():
    assert looks_like_sea_health({"status": "ok", "database": "connected"})
    assert not looks_like_sea_health({"status": "error"})
    assert not looks_like_sea_health(None)
    assert not looks_like_sea_health({"status": "ok"})


def test_port_in_use_detects_bound_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        assert port_in_use("127.0.0.1", port) is True


def test_port_in_use_false_when_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port_in_use("127.0.0.1", port) is False