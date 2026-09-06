import http.client
import json
import socket
import time
import urllib.parse

HEALTH_PATH = "/api/v1/health"


def port_in_use(host: str, port: int) -> bool:
    """Return True if another process is already bound to host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def readiness_url(port: int, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{port}{HEALTH_PATH}"


def fetch_health(host: str, port: int, timeout: float = 2.0):
    """Return (status_code, payload_dict) or None if the probe fails."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", HEALTH_PATH)
            resp = conn.getresponse()
            body = resp.read()
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError:
                payload = {}
            return resp.status, payload
        finally:
            conn.close()
    except OSError:
        return None


def looks_like_sea_health(payload) -> bool:
    """True if the probe responded with a Smart Energy Assistant health body."""
    if not isinstance(payload, dict):
        return False
    return payload.get("status") == "ok" and "database" in payload


def wait_until_ready(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    poll_interval: float = 0.5,
):
    """Poll the health endpoint until the backend is ready.

    Returns (ready: bool, elapsed: float, last_probe)."""
    start = time.monotonic()
    deadline = start + timeout
    last_probe = None
    while time.monotonic() < deadline:
        last_probe = fetch_health(host, port)
        if last_probe is not None and last_probe[0] == 200:
            return True, time.monotonic() - start, last_probe
        time.sleep(poll_interval)
    return False, timeout, last_probe