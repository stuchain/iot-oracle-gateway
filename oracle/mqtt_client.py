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


def make_on_message_handler(message_queue: "queue.Queue[tuple[str, int]]"):
    """Build paho on_message callback that enqueues decoded payload + ingest time."""

    def on_message(_client: mqtt.Client, _userdata: Any, msg: Any) -> None:
        ingest_ts_ms = int(time.time() * 1000)
        payload_str = msg.payload.decode("utf-8")
        message_queue.put((payload_str, ingest_ts_ms))

    return on_message


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

    try:
        client.connect(h, p)
    except OSError as e:
        LOG.error("MQTT connect failed to %s:%s: %s", h, p, e)
        raise

    client.subscribe(TELEMETRY_TOPIC)

    loop_thread = threading.Thread(target=client.loop_forever, daemon=True, name="oracle-mqtt-loop")
    loop_thread.start()

    return client, q, loop_thread
