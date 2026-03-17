"""Tests for IoT simulator: one tick, correct topic and payload keys."""
import json
from unittest.mock import MagicMock

import pytest

from simulator.iot_simulator import run_tick


def test_one_tick_publishes_to_correct_topic_with_required_keys():
    """Mock Client; run one tick; assert topic is iot/devices/dev-01/telemetry and payload has device_id, ts_ms, temp_c, humidity_pct, power_w, hmac."""
    mock_client = MagicMock()
    device_ids_list = ["dev-01"]
    secret = "test-secret"
    run_tick(mock_client, device_ids_list, secret, "localhost", 1883)

    assert mock_client.publish.call_count == 1
    call_args = mock_client.publish.call_args
    topic, payload_str = call_args[0][0], call_args[0][1]
    assert topic == "iot/devices/dev-01/telemetry"
    payload = json.loads(payload_str)
    required = {"device_id", "ts_ms", "temp_c", "humidity_pct", "power_w", "hmac"}
    assert set(payload.keys()) == required
    assert payload["device_id"] == "dev-01"
    assert isinstance(payload["ts_ms"], int)
    assert isinstance(payload["temp_c"], (int, float))
    assert isinstance(payload["humidity_pct"], (int, float))
    assert isinstance(payload["power_w"], (int, float))
    assert isinstance(payload["hmac"], str)
    assert len(payload["hmac"]) == 64
