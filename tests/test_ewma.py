from __future__ import annotations

import math

from oracle.ewma import EWMAZScoreAnomalyDetector


def test_ewma_constant_stream_has_low_z_scores():
    detector = EWMAZScoreAnomalyDetector(alpha=0.2, z_threshold=3.0, epsilon=1e-6)
    x = 5.0

    # First value: init should emit (0.0, False) per spec.
    z0, a0 = detector.update(x)
    assert z0 == 0.0
    assert a0 is False

    # Subsequent identical values: mean stays equal to x; z-score stays ~0.
    for _ in range(50):
        z, is_anomaly = detector.update(x)
        assert not is_anomaly
        assert math.isfinite(z)
        assert abs(z) < detector.z_threshold


def test_ewma_spike_triggers_anomaly():
    # With EWMA variance update, a rough upper bound for |z| when prior variance is
    # small is about 1/sqrt(alpha). Use alpha low enough to cross Z_THRESHOLD=3.0.
    detector = EWMAZScoreAnomalyDetector(alpha=0.1, z_threshold=3.0, epsilon=1e-6)
    x = 5.0

    # Establish baseline so variance has shrunk.
    detector.update(x)
    for _ in range(10):
        detector.update(x)

    # Large spike should produce a large z-score.
    z, is_anomaly = detector.update(50.0)
    assert is_anomaly is True
    assert abs(z) >= detector.z_threshold


def test_ewma_epsilon_zero_std_zero_is_safe():
    detector = EWMAZScoreAnomalyDetector(alpha=0.2, z_threshold=3.0, epsilon=0.0)

    # With epsilon=0, std remains 0 when observing zeros; should not crash.
    z0, a0 = detector.update(0.0)
    assert z0 == 0.0
    assert a0 is False

    z1, a1 = detector.update(0.0)
    assert z1 == 0.0
    assert a1 is False

