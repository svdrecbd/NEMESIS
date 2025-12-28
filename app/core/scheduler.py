# scheduler.py — Periodic & Poisson scheduler (seedable)
from __future__ import annotations
import random, math

DEFAULT_PERIOD_S = 10.0
DEFAULT_LAMBDA_PER_MIN = 6.0
SECONDS_PER_MIN = 60.0
MIN_RATE_PER_SEC = 1e-6
MAX_RATE_PER_SEC = 1e6
MIN_UNIFORM = 1e-12
MIN_DELAY_S = 0.001
MAX_DELAY_S = 3600.0

class TapScheduler:
    """
    Host-side scheduler for tap inter-arrival times.
    Modes:
      - Periodic: fixed period (seconds)
      - Poisson: exponential distribution with rate λ (taps per minute)
    """
    def __init__(self, seed: int | None = None):
        self._mode = "Periodic"
        self._period_s = DEFAULT_PERIOD_S
        self._lambda_per_min = DEFAULT_LAMBDA_PER_MIN
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
        rate_per_sec = max(MIN_RATE_PER_SEC, min(self._lambda_per_min / SECONDS_PER_MIN, MAX_RATE_PER_SEC))
        u = max(MIN_UNIFORM, self._rng.random())
        delay = -math.log(u) / rate_per_sec
        return max(MIN_DELAY_S, min(delay, MAX_DELAY_S))

    def descriptor(self) -> dict:
        return {
            "mode": self._mode,
            "period_s": self._period_s if self._mode == "Periodic" else None,
            "lambda_per_min": self._lambda_per_min if self._mode == "Poisson" else None,
        }
