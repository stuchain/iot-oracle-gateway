"""Tumbling windows keyed by ingest time (oracle pipeline)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class WindowSummary:
    """Aggregated metrics for one window [window_start_ms, window_end_ms)."""

    window_start_ms: int
    window_end_ms: int
    msg_count: int
    msgs_per_sec: float
    avg_latency_ms: float


class WindowAggregator:
    """Assign messages to fixed-length windows using ingest time.

    ``window_start_ms = (ingest_ts_ms // (WINDOW_SEC * 1000)) * (WINDOW_SEC * 1000)``.

    When a message falls into a later window than the current one, the current
    window is finalized. Any fully skipped windows in between emit empty
    summaries (``msg_count=0``, ``msgs_per_sec=0``, ``avg_latency_ms=0``), per
    phase spec.

    Call :meth:`flush` at shutdown to emit the last open window.
    """

    def __init__(self, window_sec: int) -> None:
        if window_sec <= 0:
            raise ValueError("window_sec must be positive")
        self.window_sec = window_sec
        self._window_ms = window_sec * 1000

        self._current_start: Optional[int] = None
        self._count: int = 0
        self._sum_latency_ms: float = 0.0

    def add_message(self, parsed: dict[str, Any], ingest_ts_ms: int) -> list[WindowSummary]:
        """Ingest one verified message; return finalized window summaries (oldest first)."""
        window_start = (ingest_ts_ms // self._window_ms) * self._window_ms
        latency_ms = float(ingest_ts_ms - int(parsed["ts_ms"]))

        emitted: list[WindowSummary] = []

        if self._current_start is None:
            self._current_start = window_start
            self._count = 1
            self._sum_latency_ms = latency_ms
            return emitted

        if window_start == self._current_start:
            self._count += 1
            self._sum_latency_ms += latency_ms
            return emitted

        if window_start > self._current_start:
            old_start = self._current_start
            emitted.append(self._finalize_current())
            ws = old_start + self._window_ms
            while ws < window_start:
                emitted.append(self._empty_summary(ws))
                ws += self._window_ms
            self._current_start = window_start
            self._count = 1
            self._sum_latency_ms = latency_ms
            return emitted

        # Out-of-order ingest (earlier window than current): finalize current and
        # move to this message's window without back-filling "future" empties.
        emitted.append(self._finalize_current())
        self._current_start = window_start
        self._count = 1
        self._sum_latency_ms = latency_ms
        return emitted

    def flush(self) -> list[WindowSummary]:
        """Finalize the open window, if any."""
        if self._current_start is None:
            return []
        return [self._finalize_current()]

    def _finalize_current(self) -> WindowSummary:
        assert self._current_start is not None
        start = self._current_start
        count = self._count
        sum_lat = self._sum_latency_ms
        self._current_start = None
        self._count = 0
        self._sum_latency_ms = 0.0
        return self._summary_from_state(start, count, sum_lat)

    def _empty_summary(self, window_start_ms: int) -> WindowSummary:
        return WindowSummary(
            window_start_ms=window_start_ms,
            window_end_ms=window_start_ms + self._window_ms,
            msg_count=0,
            msgs_per_sec=0.0,
            avg_latency_ms=0.0,
        )

    def _summary_from_state(self, window_start_ms: int, count: int, sum_latency_ms: float) -> WindowSummary:
        msgs_per_sec = count / self.window_sec
        avg_latency_ms = (sum_latency_ms / count) if count else 0.0
        return WindowSummary(
            window_start_ms=window_start_ms,
            window_end_ms=window_start_ms + self._window_ms,
            msg_count=count,
            msgs_per_sec=msgs_per_sec,
            avg_latency_ms=avg_latency_ms,
        )
