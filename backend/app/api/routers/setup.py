from fastapi import APIRouter

from ...utils.esp32_sync import get_sync_status

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/connection")
def connection_status():
    """Current ESP32 <-> laptop auto-configuration status.

    When the desktop EXE is managing the link this reports the live state from
    the background sync service (NO_WIFI / WAITING_ESP32 / CONFIGURING / ONLINE /
    DISCONNECTED). Running the backend standalone returns managed=false.
    """
    status = get_sync_status()
    status.setdefault("managed", False)
    return status