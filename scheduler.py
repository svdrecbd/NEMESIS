# scheduler.py — Periodic & Poisson scheduler (seedable)
from __future__ import annotations
import random, math

class TapScheduler:
    """
    Host-side scheduler for tap inter-arrival times.
    Modes:
      - Periodic: fixed period (seconds)
      - Poisson: exponential distribution with rate λ (taps per minute)
    """
    def __init__(self, seed: int | None = None):
        self._mode = "Periodic"
        self._period_s = 10.0
        self._lambda_per_min = 6.0
        self._rng = random.Random()
        if seed is not None:
            self.set_seed(seed)

    def set_seed(self, seed: int | None):
        self._rng = random.Random(None if seed is None else int(seed))

    def configure_periodic(self, period_s: float):
        if period_s <= 0:
            raise ValueError("period_s must be > 0")
        self._mode = "Periodic"
        self._period_s = float(period_s)

    def configure_poisson(self, lambda_per_min: float):
        if lambda_per_min <= 0:
            raise ValueError("lambda_per_min must be > 0")
        self._mode = "Poisson"
        self._lambda_per_min = float(lambda_per_min)

    def next_delay_s(self) -> float:
        if self._mode == "Periodic":
            return self._period_s
        # Poisson: exponential with mean = 60/λ
        rate_per_sec = max(1e-6, min(self._lambda_per_min / 60.0, 1e6))
        u = max(1e-12, self._rng.random())
        delay = -math.log(u) / rate_per_sec
        return max(0.001, min(delay, 3600.0))

    def descriptor(self) -> dict:
        return {
            "mode": self._mode,
            "period_s": self._period_s if self._mode == "Periodic" else None,
            "lambda_per_min": self._lambda_per_min if self._mode == "Poisson" else None,
        }
