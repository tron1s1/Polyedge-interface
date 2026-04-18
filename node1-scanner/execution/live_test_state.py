"""
LiveTestState — arm/disarm counter + master trading toggle.

Two orthogonal flags:
  master_trading_enabled   — if False, NO live/dry-run orders are sent.
                             Strategy still scans, still paper-simulates.
  armed_count              — how many live-test trades to fire on next N
                             opportunities. Decrements per fire. When 0,
                             execution reverts to paper even if master is on.

Plus:
  dry_run_enabled          — when True, live fires go to Binance as IOC LIMIT
                             with a tiny quantity that guarantees -2010
                             insufficient-balance reject. Real wire latency
                             captured, zero capital at risk. Used before
                             flipping to real live-test.
  live_test_size_usdc      — per-fire capital (default $10). Only used when
                             dry_run_enabled=False.
  cooldown_s               — minimum seconds between fires (default 30).

Backing store: TieredCache keys. This survives scanner restarts so a
previously-armed 5 trades picks up where it left off.
"""
import time
from typing import Optional, Dict

import structlog

logger = structlog.get_logger()

# Cache key prefix, namespaced per strategy
_CACHE_KEY = "live_test_state"

# Default sane values on first boot
_DEFAULTS = {
    "master_trading_enabled": False,
    "armed_count": 0,
    "dry_run_enabled": True,       # Safer default
    "live_test_size_usdc": 10.0,
    "cooldown_s": 30,
    "last_fire_ts": 0.0,
    "last_fire_result": None,       # {"outcome": ..., "pnl_usdc": ..., "ts": ...}
    "total_fires": 0,
}


class LiveTestState:
    def __init__(self, cache, strategy_id: str):
        self.cache = cache
        self.strategy_id = strategy_id
        self._state: Dict = dict(_DEFAULTS)
        self._loaded = False

    def _key(self) -> str:
        return f"{_CACHE_KEY}:{self.strategy_id}"

    async def load(self) -> None:
        """Pull persisted state from cache. Called once on strategy startup
        and then periodically by reload_loop() so changes from the API
        process (dashboard toggles, arm/disarm) are picked up within ~2s."""
        try:
            stored = await self.cache.get(self._key())
            if isinstance(stored, dict):
                # Overlay over defaults so missing keys get sensible values
                for k, v in stored.items():
                    if k in _DEFAULTS:
                        self._state[k] = v
        except Exception as e:
            logger.warning("live_test_state_load_failed", error=str(e))
        self._loaded = True

    async def reload_loop(self, interval_s: float = 2.0) -> None:
        """Background task: re-read cache every interval_s so cross-process
        writes (API → cache) propagate to the scanner."""
        import asyncio
        while True:
            try:
                await asyncio.sleep(interval_s)
                stored = await self.cache.get(self._key())
                if isinstance(stored, dict):
                    for k, v in stored.items():
                        if k in _DEFAULTS:
                            self._state[k] = v
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("live_test_state_reload_failed", error=str(e))

    async def _persist(self) -> None:
        try:
            await self.cache.set(self._key(), dict(self._state), ttl=86400)
        except Exception as e:
            logger.warning("live_test_state_persist_failed", error=str(e))

    # ── State accessors (sync — hot path) ────────────────────────────────

    def master_enabled(self) -> bool:
        return bool(self._state.get("master_trading_enabled"))

    def armed_count(self) -> int:
        return int(self._state.get("armed_count") or 0)

    def dry_run_enabled(self) -> bool:
        return bool(self._state.get("dry_run_enabled"))

    def test_size_usdc(self) -> float:
        return float(self._state.get("live_test_size_usdc") or 10.0)

    def cooldown_s(self) -> float:
        return float(self._state.get("cooldown_s") or 30)

    def in_cooldown(self) -> bool:
        return (time.time() - float(self._state.get("last_fire_ts") or 0)) < self.cooldown_s()

    def should_fire_live(self) -> bool:
        """True if the next opportunity should route to live (or dry-run) mode."""
        if not self.master_enabled():
            return False
        if self.armed_count() <= 0:
            return False
        if self.in_cooldown():
            return False
        return True

    def status(self) -> Dict:
        s = dict(self._state)
        s["in_cooldown"] = self.in_cooldown()
        s["should_fire_live"] = self.should_fire_live()
        return s

    # ── State mutators (async — persist) ──────────────────────────────────

    async def set_master(self, enabled: bool) -> None:
        self._state["master_trading_enabled"] = bool(enabled)
        await self._persist()
        logger.info("live_test_master_set", enabled=enabled)

    async def set_dry_run(self, enabled: bool) -> None:
        self._state["dry_run_enabled"] = bool(enabled)
        await self._persist()
        logger.info("live_test_dry_run_set", enabled=enabled)

    async def set_test_size(self, size_usdc: float) -> None:
        if size_usdc <= 0 or size_usdc > 1000:
            raise ValueError(f"size_usdc out of allowed range: {size_usdc}")
        self._state["live_test_size_usdc"] = float(size_usdc)
        await self._persist()

    async def set_cooldown(self, seconds: float) -> None:
        self._state["cooldown_s"] = max(0, float(seconds))
        await self._persist()

    async def arm(self, count: int) -> Dict:
        """Add N live fires to the queue."""
        count = max(0, int(count))
        self._state["armed_count"] = self.armed_count() + count
        await self._persist()
        logger.info("live_test_armed", added=count, total=self.armed_count())
        return self.status()

    async def disarm(self) -> Dict:
        self._state["armed_count"] = 0
        await self._persist()
        logger.info("live_test_disarmed")
        return self.status()

    async def record_fire(self, result_summary: Dict) -> None:
        """Called after each live/dry-run fire completes."""
        self._state["armed_count"] = max(0, self.armed_count() - 1)
        self._state["last_fire_ts"] = time.time()
        self._state["last_fire_result"] = result_summary
        self._state["total_fires"] = int(self._state.get("total_fires") or 0) + 1
        await self._persist()
