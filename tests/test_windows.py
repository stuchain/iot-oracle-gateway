"""Tests for tumbling windows (ingest-time boundaries)."""

from oracle.windows import WindowAggregator, WindowSummary


def test_two_windows_two_messages_then_flush():
    """WINDOW_SEC=5: messages in [0,5s) and [5s,10s) produce two summaries with correct metrics."""
    agg = WindowAggregator(window_sec=5)
    window_ms = 5000

    # Window 0: ingest 1000, device ts 900 -> latency 100
    out1 = agg.add_message({"ts_ms": 900}, ingest_ts_ms=1000)
    assert out1 == []

    # Window 1: ingest 6000, ts 5900 -> latency 100; finalizes window 0
    out2 = agg.add_message({"ts_ms": 5900}, ingest_ts_ms=6000)
    assert len(out2) == 1
    s0 = out2[0]
    assert s0 == WindowSummary(
        window_start_ms=0,
        window_end_ms=window_ms,
        msg_count=1,
        msgs_per_sec=0.2,
        avg_latency_ms=100.0,
    )

    out_flush = agg.flush()
    assert len(out_flush) == 1
    s1 = out_flush[0]
    assert s1 == WindowSummary(
        window_start_ms=window_ms,
        window_end_ms=2 * window_ms,
        msg_count=1,
        msgs_per_sec=0.2,
        avg_latency_ms=100.0,
    )


def test_same_window_two_messages_avg_latency_and_msgs_per_sec():
    agg = WindowAggregator(window_sec=5)
    agg.add_message({"ts_ms": 900}, ingest_ts_ms=1000)  # latency 100
    agg.add_message({"ts_ms": 1800}, ingest_ts_ms=2000)  # latency 200
    out = agg.flush()
    assert len(out) == 1
    s = out[0]
    assert s.window_start_ms == 0
    assert s.msg_count == 2
    assert s.msgs_per_sec == 2 / 5
    assert s.avg_latency_ms == 150.0


def test_skipped_windows_emit_empty_summaries():
    """Jump from window 0 to window 10000ms: one empty window at 5000 in between."""
    agg = WindowAggregator(window_sec=5)
    window_ms = 5000

    agg.add_message({"ts_ms": 0}, ingest_ts_ms=1000)
    out = agg.add_message({"ts_ms": 11000}, ingest_ts_ms=12000)

    # finalize [0,5000), empty [5000,10000); new window [10000,15000) stays open with 1 msg
    assert len(out) == 2
    assert out[0].window_start_ms == 0 and out[0].msg_count == 1
    assert out[1].window_start_ms == window_ms and out[1].msg_count == 0
    assert out[1].msgs_per_sec == 0.0 and out[1].avg_latency_ms == 0.0

    flushed = agg.flush()
    assert len(flushed) == 1
    assert flushed[0].window_start_ms == 2 * window_ms
    assert flushed[0].msg_count == 1
