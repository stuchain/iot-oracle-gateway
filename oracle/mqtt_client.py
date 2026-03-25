"""MQTT subscriber: enqueue (payload_str, ingest_ts_ms) for the oracle pipeline."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

from oracle.config import MQTT_HOST, MQTT_PORT

LOG = logging.getLogger(__name__)

TELEMETRY_TOPIC = "iot/devices/+/telemetry"

RECONNECT_SLEEP_SEC = 5.0
CONNECT_RETRY_SLEEP_SEC = 3.0


def make_on_message_handler(message_queue: "queue.Queue[tuple[str, int]]"):
    """Build paho on_message callback that enqueues decoded payload + ingest time."""

    def on_message(_client: mqtt.Client, _userdata: Any, msg: Any) -> None:
        ingest_ts_ms = int(time.time() * 1000)
        payload_str = msg.payload.decode("utf-8")
        message_queue.put((payload_str, ingest_ts_ms))

    return on_message


def _on_disconnect_factory():
    def on_disconnect(_client: mqtt.Client, _userdata: Any, rc: int) -> None:
        if rc != 0:
            LOG.warning("MQTT disconnected unexpectedly (rc=%s)", rc)

    return on_disconnect


def _connect_with_retry(client: mqtt.Client, host: str, port: int) -> None:
    """Block until initial TCP connect succeeds (broker may start after oracle)."""
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


def _reconnect_watch_loop(client: mqtt.Client, host: str, port: int) -> None:
    """If the broker drops, retry reconnect indefinitely with sleep between attempts."""
    while True:
        time.sleep(RECONNECT_SLEEP_SEC)
        if not client.is_connected():
            LOG.warning("MQTT not connected; reconnecting to %s:%s ...", host, port)
            try:
                client.reconnect()
            except Exception as e:
                LOG.warning("MQTT reconnect failed: %s (retry in %.0fs)", e, RECONNECT_SLEEP_SEC)


def start_mqtt_consumer(
    message_queue: Optional["queue.Queue[tuple[str, int]]"] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> tuple[mqtt.Client, "queue.Queue[tuple[str, int]]", threading.Thread]:
    """Connect, subscribe to telemetry topic, and run the network loop in a daemon thread.

    Args:
        message_queue: Optional existing queue; if None, a new queue.Queue is created.
        host: Broker host (default: oracle.config.MQTT_HOST).
        port: Broker port (default: oracle.config.MQTT_PORT).

    Returns:
        (client, message_queue, loop_thread)
    """
    h = host if host is not None else MQTT_HOST
    p = port if port is not None else MQTT_PORT
    q: queue.Queue[tuple[str, int]] = message_queue if message_queue is not None else queue.Queue()

    client = mqtt.Client()
    client.on_message = make_on_message_handler(q)
    client.on_disconnect = _on_disconnect_factory()

    _connect_with_retry(client, h, p)

    client.subscribe(TELEMETRY_TOPIC)

    loop_thread = threading.Thread(target=client.loop_forever, daemon=True, name="oracle-mqtt-loop")
    loop_thread.start()

    reconnect_thread = threading.Thread(
        target=_reconnect_watch_loop,
        args=(client, h, p),
        daemon=True,
        name="oracle-mqtt-reconnect",
    )
    reconnect_thread.start()

    return client, q, loop_thread
