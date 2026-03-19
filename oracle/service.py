"""Oracle service: MQTT queue → verify → windows → CSV; GET /metrics (FastAPI)."""

from __future__ import annotations

import csv
import logging
import os
import queue
import threading
from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI

from oracle.config import HMAC_SECRET, WINDOW_SEC, WINDOWS_CSV_PATH
from oracle.mqtt_client import start_mqtt_consumer
from oracle.verify import verify_payload
from oracle.windows import WindowAggregator, WindowSummary

LOG = logging.getLogger(__name__)

CSV_COLUMNS = [
    "window_start_ms",
    "window_end_ms",
    "msg_count",
    "msgs_per_sec",
    "avg_latency_ms",
    "z_score",
    "is_anomaly",
]


class OracleState:
    """Thread-safe counters, latest window, CSV append, window aggregation."""

    def __init__(
        self,
        *,
        window_sec: int,
        secret: bytes,
        csv_path: str,
    ) -> None:
        self._lock = threading.Lock()
        self._window_sec = window_sec
        self._secret = secret
        self._csv_path = csv_path
        self.aggregator = WindowAggregator(window_sec)
        self.verified_count = 0
        self.rejected_count = 0
        self.latest_window: Optional[WindowSummary] = None
        self.last_anchor_info: dict[str, Any] = {
            "success": False,
            "batch_hash": None,
            "tx_hash": None,
        }
        self._ensure_csv_header()

    def _ensure_csv_header(self) -> None:
        parent = os.path.dirname(os.path.abspath(self._csv_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(self._csv_path) or os.path.getsize(self._csv_path) == 0:
            with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()

    def _append_window_row(self, summary: WindowSummary) -> None:
        with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(
                {
                    "window_start_ms": summary.window_start_ms,
                    "window_end_ms": summary.window_end_ms,
                    "msg_count": summary.msg_count,
                    "msgs_per_sec": summary.msgs_per_sec,
                    "avg_latency_ms": summary.avg_latency_ms,
                    "z_score": "",
                    "is_anomaly": 0,
                }
            )

    def handle_message(self, payload_str: str, ingest_ts_ms: int) -> None:
        """Verify one message; on success feed windows and persist finalized summaries."""
        parsed, ok = verify_payload(payload_str, self._secret)
        with self._lock:
            if not ok:
                self.rejected_count += 1
                return
            self.verified_count += 1
            summaries = self.aggregator.add_message(parsed, ingest_ts_ms)
            for s in summaries:
                self._append_window_row(s)
                self.latest_window = s

    def flush_windows(self) -> None:
        """Finalize open window and append CSV rows (e.g. on shutdown)."""
        with self._lock:
            for s in self.aggregator.flush():
                self._append_window_row(s)
                self.latest_window = s

    def metrics_payload(self) -> dict[str, Any]:
        with self._lock:
            lw = self.latest_window
            out: dict[str, Any] = {
                "verified_count": self.verified_count,
                "rejected_count": self.rejected_count,
                "window_start_ms": lw.window_start_ms if lw else None,
                "window_end_ms": lw.window_end_ms if lw else None,
                "msg_count": lw.msg_count if lw else None,
                "msgs_per_sec": lw.msgs_per_sec if lw else None,
                "avg_latency_ms": lw.avg_latency_ms if lw else None,
                "z_score": None,
                "is_anomaly": 0,
                "last_anchor_info": dict(self.last_anchor_info),
            }
            return out


def _consumer_loop(state: OracleState, message_queue: "queue.Queue[tuple[str, int]]", stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            payload_str, ingest_ts_ms = message_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        try:
            state.handle_message(payload_str, ingest_ts_ms)
        except Exception:
            LOG.exception("Error handling message")


def create_app(
    *,
    start_mqtt: bool = True,
    message_queue: Optional["queue.Queue[tuple[str, int]]"] = None,
    window_sec: Optional[int] = None,
    hmac_secret: Optional[str] = None,
    csv_path: Optional[str] = None,
) -> FastAPI:
    """Build FastAPI app and start background MQTT consumer unless ``start_mqtt=False``."""
    ws = window_sec if window_sec is not None else WINDOW_SEC
    secret_str = hmac_secret if hmac_secret is not None else HMAC_SECRET
    secret_bytes = secret_str.encode("utf-8")
    csv_p = csv_path if csv_path is not None else WINDOWS_CSV_PATH

    q: queue.Queue[tuple[str, int]] = message_queue if message_queue is not None else queue.Queue()
    mqtt_client = None
    mqtt_thread = None
    if start_mqtt:
        mqtt_client, q, _mqtt_loop_thread = start_mqtt_consumer(message_queue=q)

    state = OracleState(window_sec=ws, secret=secret_bytes, csv_path=csv_p)
    stop_consumer = threading.Event()
    consumer_thread = threading.Thread(
        target=_consumer_loop,
        args=(state, q, stop_consumer),
        daemon=True,
        name="oracle-consumer",
    )
    consumer_thread.start()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            stop_consumer.set()
            consumer_thread.join(timeout=5.0)
            try:
                state.flush_windows()
            except Exception:
                LOG.exception("flush_windows on shutdown")
            if mqtt_client is not None:
                try:
                    mqtt_client.loop_stop()
                    mqtt_client.disconnect()
                except Exception:
                    LOG.exception("MQTT disconnect")

    app = FastAPI(title="IoT Oracle Gateway", lifespan=lifespan)

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        return state.metrics_payload()

    app.state.oracle_state = state
    app.state.message_queue = q
    app.state.stop_consumer = stop_consumer
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
