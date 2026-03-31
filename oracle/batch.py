"""Deterministic batch hash over window summaries for on-chain anchoring."""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Tuple

from oracle.windows import WindowSummary

BATCH_ROW_KEYS: Tuple[str, ...] = (
    "window_start_ms",
    "window_end_ms",
    "msg_count",
    "msgs_per_sec",
    "avg_latency_ms",
    "z_score",
    "is_anomaly",
)


def _summary_to_row(s: WindowSummary) -> dict:
    values = (
        s.window_start_ms,
        s.window_end_ms,
        s.msg_count,
        s.msgs_per_sec,
        s.avg_latency_ms,
        s.z_score,
        s.is_anomaly,
    )
    return dict(zip(BATCH_ROW_KEYS, values))


def build_batch(summaries: List[WindowSummary]) -> Optional[Tuple[bytes, int, int, int]]:
    """Return (sha256 digest, min start_ms, max end_ms, count) or None if summaries is empty."""
    if not summaries:
        return None
    # Canonicalize row order so the same logical batch hashes identically
    # regardless of input list ordering.
    list_of_dicts = sorted(
        (_summary_to_row(s) for s in summaries),
        key=lambda d: tuple(d[k] for k in BATCH_ROW_KEYS),
    )
    canonical_bytes = json.dumps(
        list_of_dicts, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    batch_hash = hashlib.sha256(canonical_bytes).digest()
    start_ms = min(s.window_start_ms for s in summaries)
    end_ms = max(s.window_end_ms for s in summaries)
    return (batch_hash, start_ms, end_ms, len(summaries))
