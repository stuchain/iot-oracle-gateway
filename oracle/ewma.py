"""EWMA z-score anomaly detector.

Phase 4: maintain an EWMA estimate of mean and variance (squared-error EWMA)
over a single input feature `x` (msgs_per_sec), then emit a z-score and
anomaly boolean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class EWMAZScoreAnomalyDetector:
    """Stateful EWMA z-score anomaly detector.

    First call initializes the EWMA mean to the input value and variance to
    `epsilon`, returning (0.0, False).
    """

    alpha: float
    z_threshold: float
    epsilon: float = 1e-6
    initialized: bool = False

    mean: float = 0.0
    var: float = 0.0

    # Used to guard division by zero / numerical underflow.
    tiny: float = 1e-12

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if self.z_threshold < 0.0:
            raise ValueError("z_threshold must be >= 0")
        if self.epsilon < 0.0:
            raise ValueError("epsilon must be >= 0")

    def update(self, value: float) -> tuple[float, bool]:
        """Update detector state with a new observation.

        Returns:
            (z_score, is_anomaly)
        """

        x = float(value)

        if not self.initialized:
            self.mean = x
            self.var = float(self.epsilon)
            self.initialized = True
            return 0.0, False

        # EWMA mean update.
        mean_new = self.alpha * x + (1.0 - self.alpha) * self.mean

        # Squared-error EWMA variance update.
        err = x - mean_new
        var_new = self.alpha * (err * err) + (1.0 - self.alpha) * self.var

        self.mean = mean_new
        self.var = var_new

        std = math.sqrt(self.var) if self.var > 0.0 else 0.0
        if std <= self.tiny:
            return 0.0, False

        z = (x - self.mean) / std
        is_anomaly = abs(z) >= self.z_threshold
        return z, is_anomaly

