"""Integration-style tests for oracle service: queue → verify → windows → CSV → /metrics."""

from __future__ import annotations

import csv
import json
import queue
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from simulator.hmac_utils import compute_hmac

from oracle.service import OracleState, create_app


def _signed_payload(secret: str, ts_ms: int, **overrides) -> str:
    base = {
        "device_id": "dev-01",
        "ts_ms": ts_ms,
        "temp_c": 22.0,
        "humidity_pct": 50.0,
        "power_w": 30.0,
    }
    base.update(overrides)
    h = compute_hmac(base, secret.encode("utf-8"))
    return json.dumps({**base, "hmac": h})


def test_service_synthetic_queue_csv_and_metrics(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
    )
    with TestClient(app) as client:
        q.put((_signed_payload(secret, 900), 1000))
        q.put((_signed_payload(secret, 5900), 6000))
        time.sleep(0.6)
        r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["verified_count"] == 2
    assert data["rejected_count"] == 0
    for key in (
        "window_start_ms",
        "window_end_ms",
        "msg_count",
        "msgs_per_sec",
        "avg_latency_ms",
        "z_score",
        "is_anomaly",
        "last_anchor_info",
    ):
        assert key in data
    assert data["z_score"] == 0.0
    assert data["is_anomaly"] == 0
    assert isinstance(data["last_anchor_info"], dict)
    assert data["last_anchor_info"].get("success") is False

    text = csv_path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) >= 2
    assert "window_start_ms" in lines[0]


def test_service_burst_triggers_anomaly(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()

    # Use test overrides so the anomaly triggers deterministically with low sample sizes.
    ewma_alpha = 0.2
    z_threshold = 1.5
    ewma_epsilon = 1e-6

    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
        ewma_alpha=ewma_alpha,
        ewma_z_threshold=z_threshold,
        ewma_epsilon=ewma_epsilon,
    )

    # Reuse a single signed payload string; ingest_ts_ms controls windowing,
    # while payload ts_ms affects only latency_ms (not used in anomaly logic).
    signed = _signed_payload(secret, ts_ms=900)

    # Baseline: 5 msgs per window => msgs_per_sec = 1.0.
    for _ in range(5):
        q.put((signed, 1000))  # window [0,5000)
    for _ in range(5):
        q.put((signed, 6000))  # window [5000,10000)

    # Burst window: 50 msgs in one window => msgs_per_sec = 10.0.
    for _ in range(50):
        q.put((signed, 11000))  # window [10000,15000)

    # One more message in the next window forces finalization and CSV write for the burst window.
    q.put((signed, 16000))  # window [15000,20000)

    with TestClient(app) as client:
        time.sleep(1.2)
        r = client.get("/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "z_score" in data and "is_anomaly" in data

    # CSV should contain at least one anomaly row.
    found = False
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["is_anomaly"]) == 1:
                z = float(row["z_score"])
                if abs(z) >= z_threshold:
                    found = True
                    break

    assert found is True


def test_service_rejects_invalid_json(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
    )
    with TestClient(app) as client:
        q.put(("not-valid-json{{{", 1000))
        time.sleep(0.4)
        r = client.get("/metrics")
    assert r.status_code == 200
    assert r.json()["verified_count"] == 0
    assert r.json()["rejected_count"] == 1


def test_service_shutdown_flushes_open_window(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
    )
    with TestClient(app):
        # Only one message in the current window; no rollover yet.
        q.put((_signed_payload(secret, 1000), 1000))
        time.sleep(0.2)
    # Exiting TestClient triggers lifespan shutdown -> flush_windows.
    text = csv_path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) >= 2


def test_service_rejects_malformed_json_payload_matrix(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
    )
    bad_json_payloads = [
        json.dumps({"device_id": "dev-01", "ts_ms": 1000, "temp_c": 1.0, "humidity_pct": 1.0, "power_w": 1.0}),
        json.dumps({"device_id": "dev-01", "ts_ms": "1000", "temp_c": 1.0, "humidity_pct": 1.0, "power_w": 1.0}),
        json.dumps({"device_id": "dev-01", "ts_ms": 1000, "temp_c": True, "humidity_pct": 1.0, "power_w": 1.0}),
    ]
    with TestClient(app) as client:
        for p in bad_json_payloads:
            q.put((p, 2000))
        time.sleep(0.4)
        r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["verified_count"] == 0
    assert data["rejected_count"] == len(bad_json_payloads)


def test_service_anchor_failure_then_success_updates_state_and_drains_pending(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    calls: list[tuple[bytes, int, int, int]] = []

    def runner(batch_hash: bytes, start_ms: int, end_ms: int, count: int):
        calls.append((batch_hash, start_ms, end_ms, count))
        if len(calls) == 1:
            raise RuntimeError("temporary anchor failure")
        from oracle.anchor_contract import AnchorResult

        return AnchorResult(tx_hash="0xabc", success=True, block_number=11)

    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
        anchor_runner=runner,
        anchor_interval_sec=3600.0,
    )
    state = app.state.oracle_state
    with TestClient(app):
        q.put((_signed_payload(secret, 900), 1000))
        q.put((_signed_payload(secret, 5900), 6000))
        time.sleep(0.5)
        assert len(state._pending_anchor) >= 1
        state.anchor_tick()
        assert state.last_anchor_info["success"] is False
        assert state.last_anchor_info["error"] is not None
        pending_after_fail = len(state._pending_anchor)
        assert pending_after_fail >= 1
        state.anchor_tick()
        assert state.last_anchor_info["success"] is True
        assert state.last_anchor_info["tx_hash"] == "0xabc"
        assert len(state._pending_anchor) < pending_after_fail


def test_oracle_state_handle_message_continues_when_csv_append_fails(tmp_path):
    secret = "integration-test-secret"
    state = OracleState(
        window_sec=5,
        secret=secret.encode("utf-8"),
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        ewma_alpha=0.2,
        ewma_z_threshold=3.0,
        ewma_epsilon=1e-6,
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        anchor_send=None,
    )

    def _fail_append(*_args, **_kwargs):
        raise OSError("disk full")

    state._append_window_row = _fail_append  # type: ignore[method-assign]
    state.handle_message(_signed_payload(secret, 900), 1000)
    state.handle_message(_signed_payload(secret, 5900), 6000)

    assert state.verified_count == 2
    assert state.latest_window is not None
    assert state.latest_window.window_end_ms == 5000
    assert len(state._pending_anchor) >= 1


def test_oracle_state_flush_continues_when_csv_append_fails(tmp_path):
    secret = "integration-test-secret"
    state = OracleState(
        window_sec=5,
        secret=secret.encode("utf-8"),
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        ewma_alpha=0.2,
        ewma_z_threshold=3.0,
        ewma_epsilon=1e-6,
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        anchor_send=None,
    )

    def _fail_append(*_args, **_kwargs):
        raise OSError("permission denied")

    state._append_window_row = _fail_append  # type: ignore[method-assign]
    state.handle_message(_signed_payload(secret, 1000), 1000)
    state.flush_windows()

    assert state.latest_window is not None
    assert state.latest_window.window_start_ms == 0
    assert len(state._pending_anchor) >= 1


def test_metrics_schema_is_stable_before_any_messages(tmp_path):
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret="integration-test-secret",
    )
    with TestClient(app) as client:
        r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {
        "verified_count",
        "rejected_count",
        "window_start_ms",
        "window_end_ms",
        "msg_count",
        "msgs_per_sec",
        "avg_latency_ms",
        "z_score",
        "is_anomaly",
        "last_anchor_info",
    }
    assert data["verified_count"] == 0
    assert data["rejected_count"] == 0
    assert data["window_start_ms"] is None
    assert data["window_end_ms"] is None
    assert data["msg_count"] is None
    assert data["msgs_per_sec"] is None
    assert data["avg_latency_ms"] is None
    assert data["z_score"] is None
    assert data["is_anomaly"] == 0
    assert isinstance(data["last_anchor_info"], dict)


def test_metrics_rejection_only_traffic_keeps_window_fields_null(tmp_path):
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret="integration-test-secret",
    )
    with TestClient(app) as client:
        q.put(("not-json", 1000))
        q.put((json.dumps({"hmac": ""}), 1200))
        time.sleep(0.4)
        r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["verified_count"] == 0
    assert data["rejected_count"] == 2
    assert data["window_start_ms"] is None
    assert data["window_end_ms"] is None
    assert data["z_score"] is None
    assert data["is_anomaly"] == 0


def test_service_mixed_burst_valid_invalid_counts_and_windows_consistent(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    secret = "integration-test-secret"
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(csv_path),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret=secret,
    )
    valid_count = 120
    invalid_count = 30
    with TestClient(app) as client:
        # Window 0 and 1 traffic, mixed valid/invalid.
        for i in range(valid_count // 2):
            q.put((_signed_payload(secret, 900 + i), 1000))
        for _ in range(invalid_count // 2):
            q.put(("bad-json", 1000))
        for i in range(valid_count // 2, valid_count):
            q.put((_signed_payload(secret, 5900 + i), 6000))
        for _ in range(invalid_count - (invalid_count // 2)):
            q.put((json.dumps({"hmac": ""}), 6000))
        time.sleep(1.1)
        r = client.get("/metrics")

    assert r.status_code == 200
    data = r.json()
    assert data["verified_count"] == valid_count
    assert data["rejected_count"] == invalid_count
    # At least one finalized window should exist.
    assert data["window_start_ms"] is not None
    assert data["window_end_ms"] is not None
    assert data["msg_count"] is not None
    assert data["msgs_per_sec"] is not None
    assert isinstance(data["is_anomaly"], int)


@patch("oracle.service.start_mqtt_consumer")
def test_service_shutdown_calls_mqtt_loop_stop_and_disconnect(mock_start_mqtt, tmp_path):
    fake_client = MagicMock()
    fake_thread = MagicMock()
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    mock_start_mqtt.return_value = (fake_client, q, fake_thread)

    app = create_app(
        start_mqtt=True,
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret="integration-test-secret",
    )
    with TestClient(app):
        pass

    fake_client.loop_stop.assert_called_once()
    fake_client.disconnect.assert_called_once()


@patch("oracle.service.start_mqtt_consumer")
def test_service_shutdown_attempts_disconnect_even_if_loop_stop_fails(mock_start_mqtt, tmp_path):
    fake_client = MagicMock()
    fake_client.loop_stop.side_effect = RuntimeError("loop stop failed")
    fake_thread = MagicMock()
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    mock_start_mqtt.return_value = (fake_client, q, fake_thread)

    app = create_app(
        start_mqtt=True,
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        contract_address="",
        window_sec=5,
        hmac_secret="integration-test-secret",
    )
    with TestClient(app):
        pass

    fake_client.loop_stop.assert_called_once()
    fake_client.disconnect.assert_called_once()
