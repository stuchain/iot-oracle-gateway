"""Integration-style tests for oracle service: queue → verify → windows → CSV → /metrics."""

from __future__ import annotations

import csv
import json
import queue
import time

from fastapi.testclient import TestClient
from simulator.hmac_utils import compute_hmac

from oracle.service import create_app


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
