import os
import sys

# Keep app imports pinned to the isolated test DB so importing `app.main`
# below (for the setup router) can never touch the production database.
os.environ["APP_TESTING"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.esp32_bridge import (  # noqa: E402
    ESP32_AP_IP,
    ESP32_AP_SSID,
    backend_url_for,
    detect_laptop_ipv4,
    enumerate_interfaces,
    extract_host,
    in_sea_subnet,
    is_link_local_ip,
    is_loopback_ip,
    is_usable_ipv4,
    normalize_backend_url,
    pick_backend_ip,
    rank_interfaces,
    validate_backend_url,
)


def test_esp32_constants():
    assert ESP32_AP_IP == "192.168.4.1"
    assert ESP32_AP_SSID == "SmartEnergyESP32"


# ---- backend URL building/validation ----
def test_backend_url_for_builds_url():
    assert backend_url_for("192.168.4.5") == "http://192.168.4.5:8000"
    assert backend_url_for("192.168.4.2") == "http://192.168.4.2:8000"
    assert backend_url_for("10.0.0.8", 8080) == "http://10.0.0.8:8080"


def test_normalize_backend_url():
    assert normalize_backend_url(" http://192.168.4.3:8000/ ") == "http://192.168.4.3:8000"
    assert normalize_backend_url("http://192.168.4.3:8000") == "http://192.168.4.3:8000"


def test_extract_host():
    assert extract_host("http://192.168.4.5:8000") == "192.168.4.5"
    assert extract_host("http://192.168.4.5") == "192.168.4.5"
    assert extract_host("https://sea.local/api") == "sea.local"


def test_validate_backend_url_accepts_valid():
    assert validate_backend_url("http://192.168.4.5:8000")
    assert validate_backend_url("http://192.168.4.2:8000/")
    assert validate_backend_url("https://sea.local:8000")
    assert validate_backend_url(" http://192.168.4.2:8000 ")


def test_validate_backend_url_rejects_invalid():
    assert not validate_backend_url("")
    assert not validate_backend_url(None)
    assert not validate_backend_url("   ")
    assert not validate_backend_url("192.168.4.5:8000")          # no scheme
    assert not validate_backend_url("ftp://192.168.4.5:8000")    # wrong scheme
    assert not validate_backend_url("http://:8000")              # no host
    assert not validate_backend_url("http:///path")              # no host
    assert not validate_backend_url("http://192.168 .4.5:8000")  # whitespace


# ---- IP classification ----
def test_ip_classification():
    assert is_loopback_ip("127.0.0.1")
    assert not is_loopback_ip("192.168.4.5")
    assert is_link_local_ip("169.254.10.10")
    assert not is_link_local_ip("192.168.4.5")
    assert in_sea_subnet("192.168.4.2")
    assert in_sea_subnet("192.168.4.254")
    assert not in_sea_subnet("192.168.5.2")
    assert not in_sea_subnet("10.0.0.1")
    assert is_usable_ipv4("192.168.4.5")
    assert not is_usable_ipv4("127.0.0.1")
    assert not is_usable_ipv4("169.254.5.5")
    assert not is_usable_ipv4("not-an-ip")


# ---- detection preference ordering ----
def test_rank_prefers_sea_subnet():
    interfaces = [
        {"ip": "192.168.4.5", "name": "Wi-Fi", "connected": True},
        {"ip": "192.168.1.10", "name": "Wi-Fi", "connected": True},
    ]
    ranked = rank_interfaces(interfaces)
    assert ranked[0]["ip"] == "192.168.4.5"


def test_rank_prefers_ssid_match_even_outside_subnet():
    """An adapter connected to the SmartEnergyESP32 SSID must win even if the
    DHCP pool ever uses a different subnet."""
    interfaces = [
        {"ip": "10.0.0.5", "name": "Wi-Fi", "ssid": ESP32_AP_SSID, "connected": True},
        {"ip": "192.168.4.9", "name": "Ethernet", "connected": True},
    ]
    ranked = rank_interfaces(interfaces)
    assert ranked[0]["ssid"] == ESP32_AP_SSID


def test_rank_excludes_loopback_linklocal_virtual():
    interfaces = [
        {"ip": "127.0.0.1", "name": "Loopback", "connected": True},
        {"ip": "169.254.2.2", "name": "Wi-Fi", "connected": True},
        {"ip": "192.168.1.20", "name": "vEthernet (WSL)", "connected": True},
        {"ip": "192.168.4.8", "name": "Wi-Fi", "connected": True},
    ]
    ranked = rank_interfaces(interfaces)
    assert ranked[0]["ip"] == "192.168.4.8"
    assert pick_backend_ip(interfaces) == "192.168.4.8"


def test_rank_connected_over_disconnected():
    interfaces = [
        {"ip": "192.168.1.5", "name": "Wi-Fi", "connected": False},
        {"ip": "192.168.1.6", "name": "Wi-Fi", "connected": True},
    ]
    ranked = rank_interfaces(interfaces)
    assert ranked[0]["ip"] == "192.168.1.6"


def test_pick_backend_ip_prefers_sea_subnet_over_ssid_absent():
    assert (
        pick_backend_ip(
            [
                {"ip": "192.168.4.25", "name": "Wi-Fi", "connected": True},
                {"ip": "172.16.0.3", "name": "Ethernet", "connected": True},
                {"ip": "127.0.0.1", "name": "Loopback", "connected": True},
            ]
        )
        == "192.168.4.25"
    )


def test_pick_backend_ip_none_when_only_excluded():
    assert (
        pick_backend_ip(
            [
                {"ip": "127.0.0.1", "name": "Loopback", "connected": True},
                {"ip": "169.254.4.4", "name": "Wi-Fi", "connected": True},
            ]
        )
        is None
    )


def test_pick_backend_ip_none_when_empty():
    assert pick_backend_ip([]) is None


def test_detect_laptop_ipv4_returns_usable_or_none():
    """Live enumeration should never return a loopback/link-local address."""
    ip = detect_laptop_ipv4()
    if ip is not None:
        assert is_usable_ipv4(ip)


def test_enumerate_interfaces_returns_list():
    assert isinstance(enumerate_interfaces(), list)


# ---- shared /setup/connection status endpoint ----
def test_setup_connection_endpoint_registered():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/setup/connection" in paths


def test_setup_connection_payload_shape():
    from app.utils.esp32_sync import get_sync_status

    status = get_sync_status()
    assert "managed" in status
    assert "phase" in status
    assert "message" in status
    assert "backend_ip" in status
    assert "backend_url" in status
    assert "esp32_ip" in status
    assert "configured" in status
    assert "online" in status
    # Standalone (no launcher sync running) reports managed=False.
    assert status["managed"] is False