"""
LatencyCircuitBreaker — global gate that trips when execution wire latency
degrades beyond safe thresholds.

When tripped:
  - BoundedParallelExecutor refuses to fire new live/dry-run trades
  - Scanner keeps finding opportunities (paper sim still runs)
  - Dashboard shows TRIPPED state + current p95
  - Auto-resets when p95 drops back below the reset threshold for
    <reset_window> consecutive samples

Sources of latency samples (all in ms):
  1. OrderAck.latency_ms from each leg (real wire RTT including sign)
  2. Per-trade total execution_ms (sum of leg latencies + internal overhead)

Thresholds (configurable):
  trip_p95_ms        — trip when 30-sample p95 exceeds this
  reset_p95_ms       — reset when 30-sample p95 drops below this for N samples
  min_samples        — need at least this many samples before any action
"""
import time
from collections import deque
from typing import Deque, Optional

import structlog

logger = structlog.get_logger()


class LatencyCircuitBreaker:
    def __init__(
        self,
        trip_p95_ms: float = 40.0,
        reset_p95_ms: float = 25.0,
        window: int = 30,
        min_samples: int = 10,
        reset_consecutive_samples: int = 5,
    ):
        self.trip_p95_ms = trip_p95_ms
        self.reset_p95_ms = reset_p95_ms
        self.window = window
        self.min_samples = min_samples
        self.reset_consecutive_samples = reset_consecutive_samples

        self._samples: Deque[float] = deque(maxlen=window)
        self._tripped = False
        self._tripped_at: Optional[float] = None
        self._recent_healthy: int = 0

    # ── Public ────────────────────────────────────────────────────────────

    def record(self, latency_ms: float) -> None:
        """Feed a new observation. May trip or reset the breaker."""
        if latency_ms < 0:
            return
        self._samples.append(latency_ms)
        if len(self._samples) < self.min_samples:
            return

        p95 = self._p95()
        if not self._tripped and p95 >= self.trip_p95_ms:
            self._tripped = True
            self._tripped_at = time.time()
            self._recent_healthy = 0
            logger.warning("latency_breaker_tripped",
                           p95_ms=round(p95, 2),
                           trip_threshold=self.trip_p95_ms)
            return

        if self._tripped:
            if p95 < self.reset_p95_ms:
                self._recent_healthy += 1
                if self._recent_healthy >= self.reset_consecutive_samples:
                    self._tripped = False
                    self._tripped_at = None
                    self._recent_healthy = 0
                    logger.info("latency_breaker_reset",
                                p95_ms=round(p95, 2))
            else:
                self._recent_healthy = 0

    def is_tripped(self) -> bool:
        return self._tripped

    def status(self) -> dict:
        p95 = self._p95() if len(self._samples) >= self.min_samples else None
        return {
            "tripped": self._tripped,
            "tripped_at": self._tripped_at,
            "samples": len(self._samples),
            "p95_ms": round(p95, 2) if p95 is not None else None,
            "trip_threshold_ms": self.trip_p95_ms,
            "reset_threshold_ms": self.reset_p95_ms,
            "recent_healthy": self._recent_healthy,
        }

    def force_reset(self) -> None:
        """Manual override — use only if latency has been investigated."""
        self._tripped = False
        self._tripped_at = None
        self._recent_healthy = 0
        logger.info("latency_breaker_force_reset")

    # ── Internal ──────────────────────────────────────────────────────────

    def _p95(self) -> float:
        if not self._samples:
            return 0.0
        s = sorted(self._samples)
        k = int(len(s) * 0.95)
        if k >= len(s): k = len(s) - 1
        return s[k]
