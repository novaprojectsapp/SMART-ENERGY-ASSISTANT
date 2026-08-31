"""
PZEM-004T Data Simulator
Sends realistic energy readings to the FastAPI backend.

Usage:
    python simulator.py [OPTIONS]

Options:
    --base-url    Backend URL (default: http://localhost:8000)
    --device-id   Device ID (default: esp32-pzem-001)
    --interval    Seconds between readings (default: 5)
    --limit       Max readings to send (default: unlimited)
    --dry-run     Print readings without sending
    --mode        Simulation mode: steady, varying, appliances (default: varying)
"""
import argparse
import json
import time
import random
import math
from datetime import datetime, timezone
import httpx


def generate_steady_reading(tick: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": round(230.0 + random.uniform(-2, 2), 2),
        "current": round(0.75 + random.uniform(-0.02, 0.02), 4),
        "power": round(172.5 + random.uniform(-5, 5), 2),
        "energy": round(0.001 * tick + random.uniform(0, 0.0001), 4),
        "frequency": round(50.0 + random.uniform(-0.1, 0.1), 2),
        "power_factor": round(0.98 + random.uniform(-0.01, 0.01), 3),
    }


def generate_varying_reading(tick: int) -> dict:
    t = tick * 5
    base_load = 100 + 80 * math.sin(t * 0.01) + 30 * math.sin(t * 0.003)
    noise = random.uniform(-8, 8)
    power = max(20, base_load + noise)
    voltage = 230.0 + random.uniform(-3, 3)
    pf = max(0.85, min(1.0, 0.97 + random.uniform(-0.05, 0.05)))
    current = power / (voltage * pf) if voltage * pf > 0 else 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": round(voltage, 2),
        "current": round(current, 4),
        "power": round(power, 2),
        "energy": round(0.001 * tick + random.uniform(0, 0.0005), 4),
        "frequency": round(50.0 + random.uniform(-0.15, 0.15), 2),
        "power_factor": round(pf, 3),
    }


def generate_appliance_reading(tick: int) -> dict:
    bulb1_on = bool(tick // 60 % 2)
    bulb2_on = bool(tick // 40 % 2)

    base = 5.0
    if bulb1_on:
        base += 40.0
    if bulb2_on:
        base += 60.0

    noise = random.uniform(-2, 2)
    power = max(3, base + noise)
    voltage = 230.0 + random.uniform(-2, 2)
    pf = 0.99 if power > 50 else 0.90
    current = power / (voltage * pf) if voltage * pf > 0 else 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": round(voltage, 2),
        "current": round(current, 4),
        "power": round(power, 2),
        "energy": round(0.001 * tick + random.uniform(0, 0.0002), 4),
        "frequency": round(50.0 + random.uniform(-0.1, 0.1), 2),
        "power_factor": round(pf, 3),
    }


MODES = {
    "steady": generate_steady_reading,
    "varying": generate_varying_reading,
    "appliances": generate_appliance_reading,
}


def ensure_device(base_url: str, device_id: str, client: httpx.Client):
    try:
        res = client.get(f"{base_url}/api/v1/devices/{device_id}")
        if res.status_code == 200:
            print(f"Device {device_id} already registered.")
            return
    except Exception:
        pass

    try:
        res = client.post(
            f"{base_url}/api/v1/devices",
            json={"id": device_id, "name": f"ESP32-S3 ({device_id})", "device_type": "PZEM-004T"},
        )
        if res.status_code in (200, 201):
            print(f"Device {device_id} registered.")
        else:
            print(f"Failed to register device: {res.status_code} {res.text}")
    except Exception as e:
        print(f"Error registering device: {e}")


def send_reading(base_url: str, device_id: str, reading: dict, client: httpx.Client, dry_run: bool):
    payload = {**reading, "data_source": "SIMULATOR"}
    if dry_run:
        print(f"[DRY RUN] {json.dumps(payload, indent=2)}")
        return True

    try:
        res = client.post(
            f"{base_url}/api/v1/devices/{device_id}/readings",
            json=payload,
            timeout=5.0,
        )
        if res.status_code in (200, 201):
            data = res.json()
            print(f"Sent: power={data.get('power', '?')}W voltage={data.get('voltage', '?')}V")
            return True
        else:
            print(f"Error {res.status_code}: {res.text[:100]}")
            return False
    except Exception as e:
        print(f"Send error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="PZEM-004T Data Simulator")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--device-id", default="esp32-pzem-001", help="Device ID")
    parser.add_argument("--interval", type=float, default=5, help="Seconds between readings")
    parser.add_argument("--limit", type=int, default=0, help="Max readings (0=unlimited)")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    parser.add_argument("--mode", choices=list(MODES.keys()), default="varying", help="Simulation mode")
    args = parser.parse_args()

    print(f"=== PZEM-004T Simulator ===")
    print(f"Mode: {args.mode}")
    print(f"Target: {args.base_url}")
    print(f"Device: {args.device_id}")
    print(f"Interval: {args.interval}s")
    print(f"Limit: {'unlimited' if args.limit == 0 else args.limit}")
    print(f"Dry run: {args.dry_run}")
    print()

    generator = MODES[args.mode]

    with httpx.Client() as client:
        if not args.dry_run:
            ensure_device(args.base_url, args.device_id, client)

        tick = 0
        sent = 0
        failed = 0

        try:
            while True:
                if args.limit > 0 and sent >= args.limit:
                    print(f"\nReached limit of {args.limit} readings.")
                    break

                reading = generator(tick)
                success = send_reading(args.base_url, args.device_id, reading, client, args.dry_run)

                if success:
                    sent += 1
                else:
                    failed += 1

                tick += 1
                time.sleep(args.interval)

        except KeyboardInterrupt:
            print(f"\n\nStopped. Sent: {sent}, Failed: {failed}")


if __name__ == "__main__":
    main()
