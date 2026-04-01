"""Oracle service: MQTT queue → verify → windows → CSV; GET /metrics (FastAPI)."""

from __future__ import annotations

import csv
import logging
import os
import queue
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import uvicorn
from fastapi import FastAPI

from oracle.anchor_contract import AnchorResult, send_anchor
from oracle.batch import build_batch
from oracle.config import (
    ALLOW_INSECURE_DEFAULT_SECRET,
    ANCHORING_LOG_PATH,
    ANCHOR_INTERVAL_SEC,
    CONTRACT_ABI_PATH,
    CONTRACT_ADDRESS,
    DEBUG,
    DEFAULT_HMAC_SECRET,
    EWMA_ALPHA,
    GANACHE_URL,
    HMAC_SECRET,
    SAFE_ERRORS,
    WINDOW_SEC,
    WINDOWS_CSV_PATH,
    Z_THRESHOLD,
    redact_path,
    sanitize_exception,
)
from oracle.ewma import EWMAZScoreAnomalyDetector
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

ANCHORING_CSV_COLUMNS = [
    "timestamp_iso",
    "batch_hash",
    "tx_hash",
    "success",
    "skipped",
    "start_ms",
    "end_ms",
    "count",
    "error",
]

AnchorSendFn = Callable[[bytes, int, int, int], AnchorResult]


class OracleState:
    """Thread-safe counters, latest window, CSV append, window aggregation."""

    def __init__(
        self,
        *,
        window_sec: int,
        secret: bytes,
        csv_path: str,
        ewma_alpha: float,
        ewma_z_threshold: float,
        ewma_epsilon: float,
        anchoring_log_path: str,
        anchor_send: Optional[AnchorSendFn] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._window_sec = window_sec
        self._secret = secret
        self._csv_path = csv_path
        self._anchoring_log_path = anchoring_log_path
        self._anchor_send = anchor_send
        self._pending_anchor: list[WindowSummary] = []
        self.aggregator = WindowAggregator(window_sec)
        self._ewma_detector = EWMAZScoreAnomalyDetector(
            alpha=ewma_alpha, z_threshold=ewma_z_threshold, epsilon=ewma_epsilon
        )
        self.verified_count = 0
        self.rejected_count = 0
        self.latest_window: Optional[WindowSummary] = None
        self.latest_z_score: Optional[float] = None
        self.latest_is_anomaly: int = 0
        self.last_anchor_info: dict[str, Any] = {
            "success": False,
            "batch_hash": None,
            "tx_hash": None,
            "skipped": False,
            "error": None,
            "block_number": None,
        }
        self._ensure_csv_header()
        self._log_every_n = 100

    def _ensure_csv_header(self) -> None:
        parent = os.path.dirname(os.path.abspath(self._csv_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(self._csv_path) or os.path.getsize(self._csv_path) == 0:
            with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()

    def _append_anchoring_log(
        self,
        *,
        batch_hash: str,
        tx_hash: str,
        success: bool,
        skipped: bool,
        error: str,
        start_ms: str = "",
        end_ms: str = "",
        count: str = "",
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        parent = os.path.dirname(os.path.abspath(self._anchoring_log_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        write_header = not os.path.exists(self._anchoring_log_path) or os.path.getsize(
            self._anchoring_log_path
        ) == 0
        with open(self._anchoring_log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=ANCHORING_CSV_COLUMNS)
            if write_header:
                w.writeheader()
            w.writerow(
                {
                    "timestamp_iso": ts,
                    "batch_hash": batch_hash,
                    "tx_hash": tx_hash,
                    "success": "1" if success else "0",
                    "skipped": "1" if skipped else "0",
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "count": count,
                    "error": error,
                }
            )

    def _append_window_row(self, summary: WindowSummary, z_score: float, is_anomaly: bool) -> None:
        with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(
                {
                    "window_start_ms": summary.window_start_ms,
                    "window_end_ms": summary.window_end_ms,
                    "msg_count": summary.msg_count,
                    "msgs_per_sec": summary.msgs_per_sec,
                    "avg_latency_ms": summary.avg_latency_ms,
                    "z_score": z_score,
                    "is_anomaly": 1 if is_anomaly else 0,
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
            if self.verified_count % self._log_every_n == 0:
                LOG.info("Verified %d telemetry messages (logging every %d)", self.verified_count, self._log_every_n)
            summaries = self.aggregator.add_message(parsed, ingest_ts_ms)
            for s in summaries:
                z_score, is_anomaly = self._ewma_detector.update(s.msgs_per_sec)
                try:
                    self._append_window_row(s, z_score=z_score, is_anomaly=is_anomaly)
                except OSError as e:
                    LOG.warning("Failed to append window CSV row: %s", e)
                except Exception:
                    LOG.exception("Unexpected error while appending window CSV row")
                enriched = replace(s, z_score=z_score, is_anomaly=is_anomaly)
                self._pending_anchor.append(enriched)
                self.latest_window = s
                self.latest_z_score = z_score
                self.latest_is_anomaly = 1 if is_anomaly else 0
                if is_anomaly:
                    LOG.info("Window [%s-%s]: z=%.4f -> anomaly=True", s.window_start_ms, s.window_end_ms, z_score)

    def flush_windows(self) -> None:
        """Finalize open window and append CSV rows (e.g. on shutdown)."""
        with self._lock:
            for s in self.aggregator.flush():
                z_score, is_anomaly = self._ewma_detector.update(s.msgs_per_sec)
                try:
                    self._append_window_row(s, z_score=z_score, is_anomaly=is_anomaly)
                except OSError as e:
                    LOG.warning("Failed to append window CSV row during flush: %s", e)
                except Exception:
                    LOG.exception("Unexpected error while appending window CSV row during flush")
                enriched = replace(s, z_score=z_score, is_anomaly=is_anomaly)
                self._pending_anchor.append(enriched)
                self.latest_window = s
                self.latest_z_score = z_score
                self.latest_is_anomaly = 1 if is_anomaly else 0

    def anchor_tick(self) -> None:
        """One anchoring attempt: batch pending windows, skip if empty, else send tx."""
        if self._anchor_send is None:
            return
        with self._lock:
            snapshot = list(self._pending_anchor)
        batch = build_batch(snapshot)
        if batch is None:
            with self._lock:
                self.last_anchor_info = {
                    "success": False,
                    "batch_hash": None,
                    "tx_hash": None,
                    "skipped": True,
                    "error": None,
                    "block_number": None,
                }
            try:
                self._append_anchoring_log(
                    batch_hash="",
                    tx_hash="",
                    success=False,
                    skipped=True,
                    error="",
                    start_ms="",
                    end_ms="",
                    count="",
                )
            except OSError as e:
                LOG.warning("Failed to append anchoring log row (skip): %s", e)
            except Exception:
                LOG.exception("Unexpected error while appending anchoring log row (skip)")
            return
        batch_hash, start_ms, end_ms, count = batch
        try:
            result = self._anchor_send(batch_hash, start_ms, end_ms, count)
        except Exception as e:
            if DEBUG:
                LOG.warning("anchor send failed: %s", e)
            else:
                LOG.warning("anchor send failed")
            result = AnchorResult(
                None,
                False,
                error=sanitize_exception(
                    e,
                    fallback="anchor_send_failed",
                    debug=DEBUG,
                ),
            )
        with self._lock:
            if result.success:
                del self._pending_anchor[: len(snapshot)]
            self.last_anchor_info = {
                "success": result.success,
                "batch_hash": batch_hash.hex(),
                "tx_hash": result.tx_hash,
                "skipped": False,
                "error": result.error,
                "block_number": result.block_number,
            }
        try:
            self._append_anchoring_log(
                batch_hash=batch_hash.hex(),
                tx_hash=result.tx_hash or "",
                success=result.success,
                skipped=False,
                error=result.error or "",
                start_ms=str(start_ms),
                end_ms=str(end_ms),
                count=str(count),
            )
        except OSError as e:
            LOG.warning("Failed to append anchoring log row: %s", e)
        except Exception:
            LOG.exception("Unexpected error while appending anchoring log row")

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
                "z_score": self.latest_z_score if lw else None,
                "is_anomaly": self.latest_is_anomaly if lw else 0,
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


def _anchor_loop(state: OracleState, interval_sec: float, stop_event: threading.Event) -> None:
    while not stop_event.wait(interval_sec):
        try:
            state.anchor_tick()
        except Exception:
            LOG.exception("anchor tick failed")


def create_app(
    *,
    start_mqtt: bool = True,
    message_queue: Optional["queue.Queue[tuple[str, int]]"] = None,
    window_sec: Optional[int] = None,
    hmac_secret: Optional[str] = None,
    csv_path: Optional[str] = None,
    ewma_alpha: Optional[float] = None,
    ewma_z_threshold: Optional[float] = None,
    ewma_epsilon: Optional[float] = None,
    anchor_interval_sec: Optional[float] = None,
    contract_address: Optional[str] = None,
    ganache_url: Optional[str] = None,
    contract_abi_path: Optional[str] = None,
    anchoring_log_path: Optional[str] = None,
    anchor_runner: Optional[AnchorSendFn] = None,
) -> FastAPI:
    """Build FastAPI app and start background MQTT consumer unless ``start_mqtt=False``."""
    ws = window_sec if window_sec is not None else WINDOW_SEC
    secret_str = hmac_secret if hmac_secret is not None else HMAC_SECRET
    if (
        secret_str == DEFAULT_HMAC_SECRET
        and not DEBUG
        and not ALLOW_INSECURE_DEFAULT_SECRET
    ):
        raise RuntimeError(
            "Refusing to start with default HMAC secret. "
            "Set HMAC_SECRET or ALLOW_INSECURE_DEFAULT_SECRET=true for local dev."
        )
    secret_bytes = secret_str.encode("utf-8")
    csv_p = csv_path if csv_path is not None else WINDOWS_CSV_PATH
    alpha = ewma_alpha if ewma_alpha is not None else EWMA_ALPHA
    z_threshold = ewma_z_threshold if ewma_z_threshold is not None else Z_THRESHOLD
    epsilon = ewma_epsilon if ewma_epsilon is not None else 1e-6
    anchor_log_p = anchoring_log_path if anchoring_log_path is not None else ANCHORING_LOG_PATH

    ca = CONTRACT_ADDRESS if contract_address is None else contract_address
    gu = GANACHE_URL if ganache_url is None else ganache_url
    ap = CONTRACT_ABI_PATH if contract_abi_path is None else contract_abi_path
    interval = ANCHOR_INTERVAL_SEC if anchor_interval_sec is None else float(anchor_interval_sec)

    anchor_send: Optional[AnchorSendFn] = None
    if anchor_runner is not None:
        anchor_send = anchor_runner
    elif ca:
        if not os.path.isfile(ap):
            if DEBUG:
                LOG.error("CONTRACT_ABI_PATH not found: %s - anchoring disabled", ap)
            else:
                LOG.error(
                    "CONTRACT_ABI_PATH not found (%s) - anchoring disabled",
                    redact_path(ap),
                )
        else:

            def _send(bh: bytes, sm: int, em: int, c: int) -> AnchorResult:
                return send_anchor(gu, ca, ap, bh, sm, em, c)

            anchor_send = _send

    q: queue.Queue[tuple[str, int]] = message_queue if message_queue is not None else queue.Queue()
    mqtt_client = None
    mqtt_thread = None
    if start_mqtt:
        mqtt_client, q, _mqtt_loop_thread = start_mqtt_consumer(message_queue=q)

    state = OracleState(
        window_sec=ws,
        secret=secret_bytes,
        csv_path=csv_p,
        ewma_alpha=alpha,
        ewma_z_threshold=z_threshold,
        ewma_epsilon=epsilon,
        anchoring_log_path=anchor_log_p,
        anchor_send=anchor_send,
    )
    stop_consumer = threading.Event()
    consumer_thread = threading.Thread(
        target=_consumer_loop,
        args=(state, q, stop_consumer),
        daemon=True,
        name="oracle-consumer",
    )
    consumer_thread.start()

    stop_anchor = threading.Event()
    anchor_thread: Optional[threading.Thread] = None
    if anchor_send is not None:
        anchor_thread = threading.Thread(
            target=_anchor_loop,
            args=(state, interval, stop_anchor),
            daemon=True,
            name="oracle-anchor",
        )
        anchor_thread.start()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            stop_consumer.set()
            stop_anchor.set()
            consumer_thread.join(timeout=5.0)
            if anchor_thread is not None:
                anchor_thread.join(timeout=5.0)
            try:
                state.flush_windows()
            except Exception:
                LOG.exception("flush_windows on shutdown")
            if mqtt_client is not None:
                try:
                    mqtt_client.loop_stop()
                except Exception:
                    LOG.exception("MQTT loop_stop")
                try:
                    mqtt_client.disconnect()
                except Exception:
                    LOG.exception("MQTT disconnect")

    app = FastAPI(title="IoT Oracle Gateway", lifespan=lifespan)

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        payload = state.metrics_payload()
        anchor = payload.get("last_anchor_info")
        if isinstance(anchor, dict):
            raw_error = anchor.get("error")
            if raw_error and SAFE_ERRORS and not DEBUG:
                anchor["error"] = "anchor_send_failed"
        return payload

    app.state.oracle_state = state
    app.state.message_queue = q
    app.state.stop_consumer = stop_consumer
    app.state.stop_anchor = stop_anchor
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
