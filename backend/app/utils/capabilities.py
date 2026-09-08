"""Device capability normalization.

Every registered device self-describes what it can do via its `capabilities`
map. The source of truth is the device declaration, stored by the backend and
never inferred from telemetry arrival.

Default capabilities (used when a device does not declare any, e.g. legacy
registrations or a firmware that predates this feature) describe the ESP32-S3
hardware this project ships: it reads PZEM telemetry AND actuates a relay on
channel 1 (GPIO 40). This default is accurate for the only device that can
register against this backend.

Keys:
    telemetry      bool   whether the device publishes PZEM readings
    relay_control  bool   whether the device can physically actuate relays
    channels       list   relay channels the device exposes (1 = GPIO 40)
"""

DEFAULT_CAPABILITIES = {"telemetry": True, "relay_control": True, "channels": [1]}


def normalize_capabilities(raw) -> dict:
    """Return a canonical capabilities dict from a raw (possibly partial, JSON-
    encoded, or None) declaration. Unknown/missing keys fall back to the
    hardware defaults; `relay_control: false` is honored explicitly."""
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict) or not raw:
        return dict(DEFAULT_CAPABILITIES)

    out = {}
    out["telemetry"] = bool(raw.get("telemetry", DEFAULT_CAPABILITIES["telemetry"]))
    out["relay_control"] = bool(raw.get("relay_control", DEFAULT_CAPABILITIES["relay_control"]))
    channels = raw.get("channels", DEFAULT_CAPABILITIES["channels"])
    if isinstance(channels, (list, tuple)) and channels:
        out["channels"] = [int(c) for c in channels if isinstance(c, int)]
    else:
        out["channels"] = list(DEFAULT_CAPABILITIES["channels"])
    return out


def encode_capabilities(raw) -> str:
    """Serialize a normalized capabilities dict to its canonical JSON form."""
    import json

    return json.dumps(normalize_capabilities(raw))