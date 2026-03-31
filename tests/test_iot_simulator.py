"""Tests for IoT simulator: one tick, correct topic and payload keys; effective_interval for burst."""
import argparse
import json
from unittest.mock import MagicMock

from simulator.iot_simulator import (
    _apply_sim_config_json,
    _parse_max_runtime_opt,
    compute_effective_interval,
    device_ids,
    run_tick,
)

# Fixed burst params for deterministic tests
INTERVAL_SEC = 1.0
BURST_START_SEC = 60
BURST_DURATION_SEC = 20
BURST_MULTIPLIER = 5.0
EXPECTED_BURST_INTERVAL = INTERVAL_SEC / BURST_MULTIPLIER  # 0.2


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


def test_effective_interval_outside_burst_window():
    """Outside [BURST_START_SEC, BURST_START_SEC + BURST_DURATION_SEC) -> INTERVAL_SEC."""
    for elapsed in (0, 50, 85):
        got = compute_effective_interval(
            elapsed, INTERVAL_SEC, True, BURST_START_SEC, BURST_DURATION_SEC, BURST_MULTIPLIER
        )
        assert got == INTERVAL_SEC


def test_effective_interval_inside_burst_window():
    """Inside burst window -> INTERVAL_SEC / BURST_MULTIPLIER."""
    for elapsed in (60, 70, 79):
        got = compute_effective_interval(
            elapsed, INTERVAL_SEC, True, BURST_START_SEC, BURST_DURATION_SEC, BURST_MULTIPLIER
        )
        assert got == EXPECTED_BURST_INTERVAL


def test_effective_interval_boundary_at_start_in_burst():
    """elapsed_sec == BURST_START_SEC -> in burst."""
    got = compute_effective_interval(
        60, INTERVAL_SEC, True, BURST_START_SEC, BURST_DURATION_SEC, BURST_MULTIPLIER
    )
    assert got == EXPECTED_BURST_INTERVAL


def test_effective_interval_boundary_at_end_not_in_burst():
    """elapsed_sec == BURST_START_SEC + BURST_DURATION_SEC -> not in burst."""
    got = compute_effective_interval(
        80, INTERVAL_SEC, True, BURST_START_SEC, BURST_DURATION_SEC, BURST_MULTIPLIER
    )
    assert got == INTERVAL_SEC


def test_effective_interval_burst_disabled_always_normal():
    """BURST_ENABLED false -> always INTERVAL_SEC even inside window."""
    got = compute_effective_interval(
        70, INTERVAL_SEC, False, BURST_START_SEC, BURST_DURATION_SEC, BURST_MULTIPLIER
    )
    assert got == INTERVAL_SEC


def test_apply_sim_config_json_overrides_namespace(tmp_path):
    """Dashboard JSON keys map onto argparse namespace used by the simulator."""
    path = tmp_path / "sim_config.json"
    path.write_text(
        json.dumps(
            {
                "N_DEVICES": 3,
                "INTERVAL_SEC": 2.5,
                "BURST_ENABLED": True,
                "BURST_START_SEC": 10,
                "BURST_DURATION_SEC": 15,
                "BURST_MULTIPLIER": 4.0,
            }
        ),
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        devices=1,
        interval=1.0,
        burst_enabled=False,
        burst_start=60,
        burst_duration=20,
        burst_multiplier=5.0,
    )
    _apply_sim_config_json(str(path), ns)
    assert ns.devices == 3
    assert ns.interval == 2.5
    assert ns.burst_enabled is True
    assert ns.burst_start == 10
    assert ns.burst_duration == 15
    assert ns.burst_multiplier == 4.0


def test_parse_max_runtime_opt():
    assert _parse_max_runtime_opt(None) is None
    assert _parse_max_runtime_opt("") is None
    assert _parse_max_runtime_opt("0") is None
    assert _parse_max_runtime_opt("-1") is None
    assert _parse_max_runtime_opt("10") == 10.0


def test_apply_sim_config_json_invalid_values_keep_existing_namespace(tmp_path):
    path = tmp_path / "sim_config.json"
    path.write_text(
        json.dumps(
            {
                "N_DEVICES": "abc",
                "INTERVAL_SEC": "bad",
                "BURST_ENABLED": "not-bool",
                "BURST_START_SEC": "bad",
                "BURST_DURATION_SEC": "bad",
                "BURST_MULTIPLIER": "bad",
            }
        ),
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        devices=2,
        interval=1.5,
        burst_enabled=False,
        burst_start=30,
        burst_duration=10,
        burst_multiplier=2.0,
    )
    _apply_sim_config_json(str(path), ns)
    assert ns.devices == 2
    assert ns.interval == 1.5
    assert ns.burst_enabled is False
    assert ns.burst_start == 30
    assert ns.burst_duration == 10
    assert ns.burst_multiplier == 2.0


def test_effective_interval_non_positive_burst_multiplier_falls_back():
    got_zero = compute_effective_interval(65, 1.0, True, 60, 20, 0.0)
    got_neg = compute_effective_interval(65, 1.0, True, 60, 20, -2.0)
    assert got_zero == 1.0
    assert got_neg == 1.0


def test_device_ids_zero_or_negative_is_empty():
    assert device_ids(0) == []
    assert device_ids(-3) == []
