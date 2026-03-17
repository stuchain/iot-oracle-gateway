"""N-device IoT telemetry simulator: one loop, MQTT publish with HMAC (no burst in this module)."""
import argparse
import json
import logging
import os
import random
import time

from dotenv import load_dotenv

from simulator.hmac_utils import compute_hmac

load_dotenv()

LOG = logging.getLogger(__name__)

TOPIC_PATTERN = "iot/devices/{device_id}/telemetry"

# Sensor ranges (doc: temp 20-30°C, humidity 40-80, power 10-100)
TEMP_RANGE = (20.0, 30.0)
HUMIDITY_RANGE = (40.0, 80.0)
POWER_RANGE = (10.0, 100.0)


def _int(key: str, default: int) -> int:
    try:
        val = os.getenv(key)
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_config():
    """Parse env with optional argparse override. Returns namespace with N_DEVICES, INTERVAL_SEC, MQTT_HOST, MQTT_PORT, HMAC_SECRET."""
    parser = argparse.ArgumentParser(description="IoT telemetry simulator")
    parser.add_argument("--devices", type=int, default=_int("N_DEVICES", 5), help="Number of devices (env: N_DEVICES)")
    parser.add_argument("--interval", type=float, default=float(os.getenv("INTERVAL_SEC", "1")), help="Tick interval seconds (env: INTERVAL_SEC)")
    parser.add_argument("--host", type=str, default=os.getenv("MQTT_HOST", "localhost"), help="MQTT broker host (env: MQTT_HOST)")
    parser.add_argument("--port", type=int, default=_int("MQTT_PORT", 1883), help="MQTT broker port (env: MQTT_PORT)")
    parser.add_argument("--secret", type=str, default=os.getenv("HMAC_SECRET", "change-me-in-production"), help="HMAC secret (env: HMAC_SECRET)")
    return parser.parse_args()


def device_ids(n: int) -> list[str]:
    """Return device IDs dev-01, dev-02, ... up to n."""
    return [f"dev-{i:02d}" for i in range(1, n + 1)]


def run_tick(client, device_ids_list: list[str], secret: str, host: str, port: int) -> None:
    """Publish one telemetry message per device. Client must be connected (or a mock)."""
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    for device_id in device_ids_list:
        payload = {
            "device_id": device_id,
            "ts_ms": int(time.time() * 1000),
            "temp_c": round(random.uniform(*TEMP_RANGE), 2),
            "humidity_pct": round(random.uniform(*HUMIDITY_RANGE), 2),
            "power_w": round(random.uniform(*POWER_RANGE), 2),
        }
        payload["hmac"] = compute_hmac(payload, secret_bytes)
        topic = TOPIC_PATTERN.format(device_id=device_id)
        body = json.dumps(payload)
        client.publish(topic, body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = get_config()
    devices = device_ids(cfg.devices)
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        LOG.error("paho-mqtt required; pip install paho-mqtt")
        raise
    client = mqtt.Client()
    client.connect(cfg.host, cfg.port)
    client.loop_start()
    tick = 0
    try:
        while True:
            run_tick(client, devices, cfg.secret, cfg.host, cfg.port)
            tick += 1
            if tick % 10 == 0 or tick == 1:
                LOG.info("tick %d: published %d messages", tick, len(devices))
            time.sleep(cfg.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
