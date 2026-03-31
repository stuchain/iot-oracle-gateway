"""N-device IoT telemetry simulator: one loop, MQTT publish with HMAC and optional burst mode."""
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

CONNECT_RETRY_SLEEP_SEC = 3.0

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


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes")


def _parse_max_runtime_opt(s: str | None) -> float | None:
    if s is None or str(s).strip() == "":
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _apply_sim_config_json(path: str, ns: argparse.Namespace) -> None:
    """Apply dashboard-written JSON (N_DEVICES, INTERVAL_SEC, BURST_*) onto parsed namespace."""
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    if "N_DEVICES" in j:
        try:
            ns.devices = int(j["N_DEVICES"])
        except (ValueError, TypeError):
            LOG.warning("Ignoring invalid N_DEVICES in %s: %r", path, j["N_DEVICES"])
    if "INTERVAL_SEC" in j:
        try:
            ns.interval = float(j["INTERVAL_SEC"])
        except (ValueError, TypeError):
            LOG.warning("Ignoring invalid INTERVAL_SEC in %s: %r", path, j["INTERVAL_SEC"])
    if "BURST_ENABLED" in j:
        v = j["BURST_ENABLED"]
        if isinstance(v, bool):
            ns.burst_enabled = v
        else:
            ns.burst_enabled = str(v).lower() in ("1", "true", "yes")
    if "BURST_START_SEC" in j:
        try:
            ns.burst_start = int(j["BURST_START_SEC"])
        except (ValueError, TypeError):
            LOG.warning("Ignoring invalid BURST_START_SEC in %s: %r", path, j["BURST_START_SEC"])
    if "BURST_DURATION_SEC" in j:
        try:
            ns.burst_duration = int(j["BURST_DURATION_SEC"])
        except (ValueError, TypeError):
            LOG.warning("Ignoring invalid BURST_DURATION_SEC in %s: %r", path, j["BURST_DURATION_SEC"])
    if "BURST_MULTIPLIER" in j:
        try:
            ns.burst_multiplier = float(j["BURST_MULTIPLIER"])
        except (ValueError, TypeError):
            LOG.warning("Ignoring invalid BURST_MULTIPLIER in %s: %r", path, j["BURST_MULTIPLIER"])


def get_config():
    """Parse env with optional argparse override. Returns namespace with N_DEVICES, INTERVAL_SEC, MQTT, HMAC_SECRET, and burst options."""
    parser = argparse.ArgumentParser(description="IoT telemetry simulator")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON file from the dashboard (e.g. config/sim_config.json): N_DEVICES, INTERVAL_SEC, BURST_*",
    )
    parser.add_argument("--devices", type=int, default=_int("N_DEVICES", 5), help="Number of devices (env: N_DEVICES)")
    parser.add_argument("--interval", type=float, default=float(os.getenv("INTERVAL_SEC", "1")), help="Tick interval seconds (env: INTERVAL_SEC)")
    parser.add_argument("--host", type=str, default=os.getenv("MQTT_HOST", "localhost"), help="MQTT broker host (env: MQTT_HOST)")
    parser.add_argument("--port", type=int, default=_int("MQTT_PORT", 1883), help="MQTT broker port (env: MQTT_PORT)")
    parser.add_argument("--secret", type=str, default=os.getenv("HMAC_SECRET", "change-me-in-production"), help="HMAC secret (env: HMAC_SECRET)")
    parser.add_argument("--burst-enabled", type=lambda x: str(x).lower() in ("1", "true", "yes"), default=_bool("BURST_ENABLED", False), help="Enable burst window (env: BURST_ENABLED)")
    parser.add_argument("--burst-start", type=int, default=_int("BURST_START_SEC", 60), help="Burst start time in seconds (env: BURST_START_SEC)")
    parser.add_argument("--burst-duration", type=int, default=_int("BURST_DURATION_SEC", 20), help="Burst duration in seconds (env: BURST_DURATION_SEC)")
    parser.add_argument("--burst-multiplier", type=float, default=float(os.getenv("BURST_MULTIPLIER", "5")), help="Interval divisor during burst (env: BURST_MULTIPLIER)")
    parser.add_argument(
        "--max-runtime-sec",
        type=_parse_max_runtime_opt,
        default=_parse_max_runtime_opt(os.getenv("MAX_RUNTIME_SEC")),
        dest="max_runtime_sec",
        metavar="SEC",
        help="Exit after this many seconds (env: MAX_RUNTIME_SEC). Omit or 0 for unlimited.",
    )
    args = parser.parse_args()
    if args.config:
        _apply_sim_config_json(args.config, args)
    return args


def compute_effective_interval(
    elapsed_sec: float,
    interval_sec: float,
    burst_enabled: bool,
    burst_start_sec: int,
    burst_duration_sec: int,
    burst_multiplier: float,
) -> float:
    """Return sleep interval for this tick: shorter during burst window, else interval_sec."""
    if not burst_enabled:
        return interval_sec
    if burst_multiplier <= 0:
        return interval_sec
    in_window = burst_start_sec <= elapsed_sec < burst_start_sec + burst_duration_sec
    return interval_sec / burst_multiplier if in_window else interval_sec


def device_ids(n: int) -> list[str]:
    """Return device IDs dev-01, dev-02, ... up to n."""
    return [f"dev-{i:02d}" for i in range(1, n + 1)]


def _mqtt_connect_with_retry(client, host: str, port: int) -> None:
    """Block until connected to the broker (retries if broker is not up yet)."""
    while True:
        try:
            client.connect(host, port)
            return
        except OSError as e:
            LOG.warning(
                "MQTT connect failed to %s:%s: %s — retry in %.0fs",
                host,
                port,
                e,
                CONNECT_RETRY_SLEEP_SEC,
            )
            time.sleep(CONNECT_RETRY_SLEEP_SEC)


def _mqtt_ensure_connected(client, host: str, port: int) -> None:
    """If the session dropped, reconnect before publishing."""
    while not client.is_connected():
        LOG.warning("Reconnecting to MQTT broker at %s:%s ...", host, port)
        try:
            client.reconnect()
        except Exception as e:
            LOG.warning("MQTT reconnect failed: %s — retry in %.0fs", e, CONNECT_RETRY_SLEEP_SEC)
            time.sleep(CONNECT_RETRY_SLEEP_SEC)


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
    start_time = time.time()
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        LOG.error("paho-mqtt required; pip install paho-mqtt")
        raise
    client = mqtt.Client()

    def on_disconnect(_client, _userdata, rc):
        if rc != 0:
            LOG.warning("MQTT disconnected unexpectedly (rc=%s)", rc)

    client.on_disconnect = on_disconnect
    _mqtt_connect_with_retry(client, cfg.host, cfg.port)
    client.loop_start()
    tick = 0
    in_burst = False
    try:
        while True:
            elapsed_sec = time.time() - start_time
            now_in_burst = (
                cfg.burst_enabled
                and cfg.burst_start <= elapsed_sec < cfg.burst_start + cfg.burst_duration
            )
            if now_in_burst and not in_burst:
                LOG.info("Burst started")
            elif in_burst and not now_in_burst:
                LOG.info("Burst ended")
            in_burst = now_in_burst

            _mqtt_ensure_connected(client, cfg.host, cfg.port)
            run_tick(client, devices, cfg.secret, cfg.host, cfg.port)
            tick += 1
            if tick % 10 == 0 or tick == 1:
                LOG.info("tick %d: published %d messages", tick, len(devices))

            if cfg.max_runtime_sec is not None and elapsed_sec >= cfg.max_runtime_sec:
                LOG.info("max runtime reached (%.1f s)", cfg.max_runtime_sec)
                break

            effective_interval = compute_effective_interval(
                elapsed_sec,
                cfg.interval,
                cfg.burst_enabled,
                cfg.burst_start,
                cfg.burst_duration,
                cfg.burst_multiplier,
            )
            time.sleep(effective_interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
