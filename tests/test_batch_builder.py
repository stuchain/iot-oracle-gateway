"""Batch hash: canonical JSON + SHA-256."""

from oracle.batch import build_batch
from oracle.windows import WindowSummary


def _sample_a() -> WindowSummary:
    return WindowSummary(
        window_start_ms=0,
        window_end_ms=5000,
        msg_count=10,
        msgs_per_sec=2.0,
        avg_latency_ms=50.0,
        z_score=0.5,
        is_anomaly=False,
    )


def _sample_b() -> WindowSummary:
    return WindowSummary(
        window_start_ms=5000,
        window_end_ms=10000,
        msg_count=3,
        msgs_per_sec=0.6,
        avg_latency_ms=12.0,
        z_score=2.5,
        is_anomaly=True,
    )


def test_build_batch_empty_returns_none():
    assert build_batch([]) is None


def test_build_batch_deterministic():
    rows = [_sample_a(), _sample_b()]
    h1 = build_batch(rows)
    h2 = build_batch(rows)
    assert h1 is not None and h2 is not None
    assert h1[0] == h2[0]
    assert h1 == h2


def test_build_batch_change_field_changes_hash():
    base = _sample_a()
    changed = WindowSummary(
        window_start_ms=base.window_start_ms,
        window_end_ms=base.window_end_ms,
        msg_count=base.msg_count,
        msgs_per_sec=base.msgs_per_sec,
        avg_latency_ms=99.0,
        z_score=base.z_score,
        is_anomaly=base.is_anomaly,
    )
    h_base = build_batch([base])
    h_changed = build_batch([changed])
    assert h_base is not None and h_changed is not None
    assert h_base[0] != h_changed[0]


def test_build_batch_one_vs_two_summaries_differ():
    one = build_batch([_sample_a()])
    two = build_batch([_sample_a(), _sample_b()])
    assert one is not None and two is not None
    assert one[0] != two[0]
