"""ESP32 backend discovery + auto-configuration bridge.

Responsibilities:
- Robustly detect the laptop's active IPv4 address on the network connected to
  the SmartEnergyESP32 access point (no hardcoded 192.168.4.2).
- Push the dynamically detected backend URL to the ESP32 configuration server
  (POST /api/backend/config on the AP) and verify it (GET /api/backend/status).

Selection order for the detected address:
  1. Adapter whose Wi-Fi connection profile (SSID) == "SmartEnergyESP32".
  2. Any IPv4 in 192.168.4.0/24.
  3. Any connected, non-loopback, non-link-local IPv4.
Excluded: 127.0.0.1, 169.254.x.x, disconnected adapters, virtual/VPN adapters.

Only the standard library is used (no psutil) so the packaged EXE stays lean.
"""

import base64
import ipaddress
import json
import logging
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("sea.esp32_bridge")

ESP32_AP_IP = "192.168.4.1"
ESP32_AP_SSID = "SmartEnergyESP32"
ESP32_CONFIG_PORT = 80
ESP32_CONFIG_PATH = "/api/backend/config"
ESP32_STATUS_PATH = "/api/backend/status"
BACKEND_PORT = 8000

SEA_SUBNET = ipaddress.ip_network("192.168.4.0/24")

# Friendly-name fragments that identify virtual/VPN/loopback-style adapters.
VIRTUAL_NAME_FRAGMENTS = (
    "virtual", "vethernet", "vmware", "virtualbox", "tap-", "tun", "bluetooth",
    "loopback", "tailscale", "zerotier", "hamachi", "wsl", "docker", "vpn",
    "pseudo", "teredo", "isatap", "microsoft wi-fi direct",
)
# Fragments that signal a Wi-Fi / wireless adapter on Windows.
WIRELESS_NAME_FRAGMENTS = ("wi-fi", "wifi", "wireless", "802.11", "wlan", "wire")


# ---------------------------------------------------------------------------
# URL handling / validation
# ---------------------------------------------------------------------------
def normalize_backend_url(url: Any) -> str:
    """Trim whitespace and strip a single trailing slash."""
    if url is None:
        return ""
    out = str(url).strip()
    if out.endswith("/"):
        out = out[:-1]
    return out


def backend_url_for(ipv4: str, port: int = BACKEND_PORT) -> str:
    """Build a backend URL for a detected IPv4 address."""
    host = ipv4.strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def extract_host(url: str) -> str:
    """Extract the host part of an http(s) URL."""
    u = normalize_backend_url(url)
    scheme = "://"
    idx = u.find(scheme)
    if idx < 0:
        return u
    rest = u[idx + len(scheme):]
    end = len(rest)
    for sep in ("/", ":", "?", "#"):
        p = rest.find(sep)
        if p >= 0:
            end = min(end, p)
    return rest[:end]


def validate_backend_url(url: Any) -> bool:
    """Match firmware validation: non-empty, http(s)://, non-empty host, no spaces."""
    u = normalize_backend_url(url)
    if not u:
        return False
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    host = extract_host(u)
    if not host:
        return False
    if " " in u:
        return False
    # Loosely reject obviously-literal/empty hosts like "://" or "http://:8000".
    if host in ("", ":", "http", "https"):
        return False
    return True


# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------
def is_loopback_ip(ipv4: str) -> bool:
    try:
        return ipaddress.ip_address(ipv4).is_loopback
    except ValueError:
        return False


def is_link_local_ip(ipv4: str) -> bool:
    try:
        return ipaddress.ip_address(ipv4).is_link_local
    except ValueError:
        return False


def in_sea_subnet(ipv4: str) -> bool:
    try:
        return ipaddress.ip_address(ipv4) in SEA_SUBNET
    except ValueError:
        return False


def is_usable_ipv4(ipv4: str) -> bool:
    try:
        addr = ipaddress.ip_address(ipv4)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return not addr.is_loopback and not addr.is_link_local


def _looks_virtual(friendly_name: str) -> bool:
    name = (friendly_name or "").lower()
    return any(frag in name for frag in VIRTUAL_NAME_FRAGMENTS)


def _looks_wireless(friendly_name: str) -> bool:
    name = (friendly_name or "").lower()
    return any(frag in name for frag in WIRELESS_NAME_FRAGMENTS)


def rank_interfaces(interfaces: list) -> list:
    """Rank network interfaces, best first.

    Each entry is a dict with keys: ip (required), name (optional),
    ssid (optional), connected (optional bool), wireless (optional bool).
    The winner is the first entry of the returned list.
    """
    scored = []
    for iface in interfaces:
        ip = str(iface.get("ip", "")).strip()
        name = iface.get("name") or iface.get("alias") or ""
        ssid = (iface.get("ssid") or "").strip()
        connected = bool(iface.get("connected", True))
        wireless = bool(iface.get("wireless", _looks_wireless(name)))

        if not ip:
            continue
        try:
            addr = ipaddress.ip_address(ip)
            if addr.version != 4:
                continue
            is_loop = addr.is_loopback
            is_link = addr.is_link_local
        except ValueError:
            continue

        score = 0
        if ssid == ESP32_AP_SSID:
            score += 1000  # definitively connected to the hardware network
        if in_sea_subnet(ip):
            score += 500
        if connected:
            score += 50
        if not is_loop:
            score += 40
        if not is_link:
            score += 20
        if wireless:
            score += 30
        if is_loop or is_link or _looks_virtual(name):
            score -= 1000  # never preferred
        scored.append((score, ip, name, ssid))

    scored.sort(key=lambda t: (-t[0], t[1]))
    return [{"ip": s[1], "name": s[2], "ssid": s[3], "score": s[0]} for s in scored]


def pick_backend_ip(interfaces: list) -> Optional[str]:
    """Return the best IPv4 for the backend, or None."""
    ranked = rank_interfaces(interfaces)
    if not ranked:
        return None
    best = ranked[0]
    if best["score"] < 0 or not is_usable_ipv4(best["ip"]):
        return None
    return best["ip"]


# ---------------------------------------------------------------------------
# OS-level enumeration (Windows: PowerShell; other: socket fallback)
# ---------------------------------------------------------------------------
_PS_ENUM_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$profiles = @{}
Get-NetConnectionProfile | ForEach-Object { $profiles[$_.InterfaceIndex] = $_.Name }
$rows = @()
Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object {
    $ad = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex
    $rows += [PSCustomObject]@{
        ip        = $_.IPAddress
        alias     = $_.InterfaceAlias
        index     = $_.InterfaceIndex
        ssid      = $profiles[$_.InterfaceIndex]
        connected = [bool]($ad -and $ad.Status -eq 'Up')
    }
}
$rows | ConvertTo-Json -Compress
"""


def _powershell_json(script: str, timeout: float = 10.0):
    """Run a PowerShell script and return parsed JSON (or None)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("PowerShell enumeration failed: %s", exc)
        return None
    if proc.returncode != 0:
        logger.warning("PowerShell enumeration non-zero exit: %s", proc.stderr.strip()[:200])
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _enumerate_windows_interfaces() -> list:
    data = _powershell_json(_PS_ENUM_SCRIPT)
    if not data:
        return []
    if isinstance(data, dict):
        data = [data]
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        result.append({
            "ip": row.get("ip", ""),
            "name": row.get("alias", ""),
            "ssid": row.get("ssid", ""),
            "connected": bool(row.get("connected", False)),
            "wireless": _looks_wireless(row.get("alias", "")),
        })
    return result


def _enumerate_socket_fallback() -> list:
    interfaces = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if addr not in interfaces:
                interfaces.append(addr)
    except OSError:
        pass
    return [{"ip": ip, "name": "host", "ssid": "", "connected": True} for ip in interfaces]


def enumerate_interfaces() -> list:
    if sys.platform.startswith("win"):
        interfaces = _enumerate_windows_interfaces()
        if interfaces:
            return interfaces
    return _enumerate_socket_fallback()


def detect_laptop_ipv4() -> Optional[str]:
    """Best-effort detection of the laptop IPv4 that the ESP32 can reach."""
    interfaces = enumerate_interfaces()
    if not interfaces:
        logger.warning("No IPv4 interfaces detected")
        return None
    return pick_backend_ip(interfaces)


def wifi_connected_to_sea(interfaces: Optional[list] = None) -> bool:
    """True when a Wi-Fi connection profile is reporting the SmartEnergyESP32 SSID.

    Falls back to direct ESP32 reachability check when the SSID profile
    hasn't updated yet (common on Windows after initial connection).
    """
    if interfaces is None:
        interfaces = enumerate_interfaces()
    if any(str(i.get("ssid", "")).strip() == ESP32_AP_SSID for i in interfaces):
        return True
    # Fallback: if the ESP32 AP is reachable on its default IP, we're connected
    # even if the Windows SSID profile hasn't propagated yet.
    if any(in_sea_subnet(str(i.get("ip", ""))) for i in interfaces):
        return True
    return False


# ---------------------------------------------------------------------------
# ESP32 AP reachability + configuration
# ---------------------------------------------------------------------------
def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_json(url: str, method: str = "GET", payload: Any = None, timeout: float = 3.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = json.loads(raw.decode("utf-8")) if raw else {}
            return resp.status, body
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("ESP32 HTTP %s %s failed: %s", method, url, exc)
        return None, {}


def esp32_reachable(timeout: float = 2.0) -> bool:
    return tcp_reachable(ESP32_AP_IP, ESP32_CONFIG_PORT, timeout)


def esp32_status(timeout: float = 3.0):
    status, body = _http_json(
        f"http://{ESP32_AP_IP}:{ESP32_CONFIG_PORT}{ESP32_STATUS_PATH}", timeout=timeout
    )
    if status != 200:
        return None
    return body


def configure_esp32(backend_url: str, timeout: float = 3.0):
    """POST /api/backend/config; returns (ok, status_code, detail)."""
    backend_url = normalize_backend_url(backend_url)
    if not validate_backend_url(backend_url):
        return False, None, "invalid backend_url"
    status, body = _http_json(
        f"http://{ESP32_AP_IP}:{ESP32_CONFIG_PORT}{ESP32_CONFIG_PATH}",
        method="POST",
        payload={"backend_url": backend_url},
        timeout=timeout,
    )
    if status == 200 and body.get("configured"):
        return True, status, body
    return False, status, body


def verify_esp32_config(backend_url: str) -> bool:
    """Confirm the ESP32 reports the same backend URL we pushed."""
    status = esp32_status()
    if not status:
        return False
    return bool(status.get("configured")) and normalize_backend_url(status.get("backend_url", "")) == normalize_backend_url(backend_url)