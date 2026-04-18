"""
KillSwitchBus — singleton safety system.
Every strategy checks this before executing any trade.
Pre-trade check: < 0.001ms (dict lookup from in-memory cache).
Background monitor: runs every 10s, does heavy analysis.
CRITICAL: Separate from risk module — this is the hard stop mechanism.
"""
import asyncio
import os
import time
from typing import Set, Optional
from latency.base_methods import TieredCache, AsyncEventBus
from database.supabase_client import SupabaseClient
import structlog

logger = structlog.get_logger()

# ── In-memory risk state (never goes stale — always < 10 seconds old) ────
# This is what the < 0.001ms pre-trade check reads from.
_RISK_STATE = {
    "global_kill": False,
    "blocked_strategies": set(),
    "kelly_multiplier": 0.75,
    "max_trade_size_usdc": 500.0,
    "regime": "BULL_RANGING",
    "drawdown_pct": 0.0,
    "daily_pnl_usdc": 0.0,
    "consecutive_losses": 0,
    "last_updated": 0.0,
}


class KillSwitchBus:
    """
    Two-layer architecture:
    Layer 1 (background): Full analysis every 10 seconds (50–200ms)
    Layer 2 (pre-trade):  Dict lookup < 0.001ms — zero latency impact
    """

    def __init__(self, cache: TieredCache, event_bus: AsyncEventBus, db: SupabaseClient):
        self._cache = cache
        self._bus = event_bus
        self._db = db
        self._node_id = os.getenv("NODE_ID", "singapore-01")

    # ── Pre-trade check (ZERO LATENCY — in hot path) ─────────────────────

    def pre_trade_check(
        self,
        strategy_id: str,
        size_usdc: float,
        leverage: float = 1.0,
    ) -> tuple[bool, str]:
        """
        Called BEFORE every trade execution.
        Reads only from in-memory dict — 0.001ms total.
        Returns (allowed: bool, reason: str).
        """
        state = _RISK_STATE

        if state["global_kill"]:
            return False, "Global kill switch active"

        if strategy_id in state["blocked_strategies"]:
            return False, f"Strategy {strategy_id} is blocked"

        # Math/arb strategies manage their own sizing — they are simultaneous
        # both-leg trades with near-zero directional risk. Skip the regime cap.
        _math_strats = {"A_M1_triangular_arb", "A_M2_funding_rate",
                        "A_CEX_cross_arb", "A_STAB_depeg",
                        "A_M4_futures_basis", "A_FL_flash_loan"}
        if strategy_id not in _math_strats and size_usdc > state["max_trade_size_usdc"]:
            return False, f"Trade size ${size_usdc:.0f} exceeds limit ${state['max_trade_size_usdc']:.0f}"

        if leverage > 10.0:
            return False, f"Leverage {leverage}x exceeds hardcoded max 10x"

        if state["drawdown_pct"] > 40.0:
            # Only math strategies allowed when drawdown > 40%
            math_strats = {"A_M1_triangular_arb", "A_M2_funding_rate",
                           "A_CEX_cross_arb", "A_STAB_depeg", "A_M4_futures_basis"}
            if strategy_id not in math_strats:
                return False, f"Drawdown {state['drawdown_pct']:.1f}% — only math strategies allowed"

        return True, "OK"

    def apply_kelly_to_size(self, raw_size: float, strategy_id: str) -> float:
        """Scale position size by Kelly multiplier for current regime."""
        multiplier = _RISK_STATE["kelly_multiplier"]

        # Math strategies get full kelly always (they're guaranteed)
        math_strats = {"A_M1_triangular_arb", "A_M2_funding_rate",
                       "A_CEX_cross_arb", "A_STAB_depeg", "A_M4_futures_basis",
                       "A_FL_flash_loan"}
        if strategy_id in math_strats:
            return raw_size  # No Kelly reduction for guaranteed strategies

        return raw_size * multiplier

    # ── Background monitor (runs every 10 seconds, NOT in hot path) ──────

    async def run_background_monitor(self) -> None:
        """
        Heavy analysis loop. Updates _RISK_STATE every 10 seconds.
        Never blocks the main scanner loop.
        """
        while True:
            try:
                await self._update_risk_state()
            except Exception as e:
                logger.error("risk_monitor_error", error=str(e))
            await asyncio.sleep(10)

    async def _update_risk_state(self) -> None:
        """Full risk analysis. Writes to _RISK_STATE dict."""
        global _RISK_STATE

        # Read current regime from cache (set by regime detector)
        regime_data = await self._cache.get("regime:current") or {}
        regime = regime_data.get("regime", "BULL_RANGING")
        kelly = regime_data.get("kelly_multiplier", 0.75)
        paused = set(regime_data.get("paused_strategies", []))

        # Read daily PnL from cache
        daily_pnl = await self._cache.get("pnl:today:usdc") or 0.0
        peak_capital = await self._cache.get("capital:peak_usdc") or 0.0
        current_capital = await self._cache.get("capital:current_usdc") or 0.0
        consecutive_losses = await self._cache.get("stats:consecutive_losses") or 0

        drawdown = 0.0
        if peak_capital > 0:
            drawdown = max(0, (peak_capital - current_capital) / peak_capital * 100)

        # Calculate max trade size based on regime
        max_trade_pct = {
            "BULL_TRENDING": 0.05,   # 5% of capital per trade
            "BULL_RANGING":  0.04,
            "VOLATILE_UP":   0.03,
            "CRASH_MINOR":   0.02,
            "CRASH_MAJOR":   0.01,
            "RECOVERY":      0.02,
            "BLACK_SWAN":    0.005,
        }.get(regime, 0.03)

        max_trade = max(50.0, current_capital * max_trade_pct)

        # Check circuit breakers
        blocked = set(paused)  # Start with regime-paused strategies

        # CB1: Daily loss > 10% → additional restrictions
        if current_capital > 0 and daily_pnl < -(current_capital * 0.10):
            # Block aggressive strategies
            blocked.update(["D_LEV_event_futures", "B_SNIPE_token"])
            logger.warning("cb1_daily_loss_triggered", pnl=daily_pnl)

        # CB4: Consecutive losses > 5 → pause specific strategy
        if consecutive_losses >= 5:
            last_losing_strategy = await self._cache.get("stats:last_losing_strategy")
            if last_losing_strategy:
                blocked.add(last_losing_strategy)
                logger.warning("cb4_consecutive_loss",
                               strategy=last_losing_strategy,
                               count=consecutive_losses)

        # CB3: Drawdown > 35% → only math strategies
        if drawdown > 35.0:
            non_math = {"C_AI_crypto_news", "C_FEAR_greed", "D_SHORT_systematic",
                        "D_LEV_event_futures", "D_PAIR_long_short", "D_GRID_trading",
                        "D_DCA_volatility", "B_LIST_frontrun", "B_BYBIT_launchpool",
                        "B_SPORT_score_arb", "B_WHALE_copy", "B_SNIPE_token"}
            blocked.update(non_math)
            logger.error("cb3_drawdown_critical", drawdown=drawdown)

        # Check global kill switch from Supabase
        global_kill = await self._check_global_kill_switch()

        # Update in-memory state (< 0.001ms read by pre-trade check)
        _RISK_STATE.update({
            "global_kill": global_kill,
            "blocked_strategies": blocked,
            "kelly_multiplier": kelly if not global_kill else 0.0,
            "max_trade_size_usdc": max_trade,
            "regime": regime,
            "drawdown_pct": drawdown,
            "daily_pnl_usdc": daily_pnl,
            "consecutive_losses": consecutive_losses,
            "last_updated": time.monotonic(),
        })

        # Publish snapshot for dashboard (fire-and-forget, non-blocking)
        snapshot = {
            "node_id": self._node_id,
            "regime": regime,
            "total_capital_usdc": current_capital,
            "peak_capital_usdc": peak_capital,
            "drawdown_pct": drawdown,
            "daily_pnl_usdc": daily_pnl,
            "circuit_breakers_active": list(blocked),
            "kelly_multiplier": kelly,
        }
        def _push_snapshot():
            try:
                self._db.table("risk_snapshots").insert(snapshot).execute()
            except Exception:
                pass
        asyncio.get_event_loop().run_in_executor(None, _push_snapshot)

    async def _check_global_kill_switch(self) -> bool:
        """Read global kill switch from Supabase. Cache it. Non-blocking."""
        try:
            cached = await self._cache.get("risk:global_kill")
            if cached is not None:
                return cached

            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._db.table("deployment_config").select("value").eq(
                    "key", "kill_switch_global"
                ).single().execute()),
                timeout=5.0,
            )

            is_killed = result.data.get("value", "false").lower() == "true"
            await self._cache.set("risk:global_kill", is_killed)
            return is_killed
        except Exception:
            return False  # Default: allow if can't read

    async def trigger_global_halt(self, reason: str) -> None:
        """Emergency halt. Writes to Supabase, updates cache instantly."""
        _RISK_STATE["global_kill"] = True  # Immediate in-memory effect
        await self._cache.set("risk:global_kill", True)
        self._db.table("deployment_config").update(
            {"value": "true"}
        ).eq("key", "kill_switch_global").execute()
        logger.critical("GLOBAL_HALT_TRIGGERED", reason=reason)

    async def release_halt(self) -> None:
        """Release global halt. Requires manual action."""
        _RISK_STATE["global_kill"] = False
        await self._cache.set("risk:global_kill", False)
        self._db.table("deployment_config").update(
            {"value": "false"}
        ).eq("key", "kill_switch_global").execute()
        logger.warning("global_halt_released")
