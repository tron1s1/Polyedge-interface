"""
DynamicCapitalAllocator — regime-based capital allocation.
Updates every 5 minutes. Writes allocation to cache.
Strategies read their allocation from cache before sizing positions.
"""
import asyncio
import os
from typing import Dict, Optional
from latency.base_methods import TieredCache
from database.supabase_client import SupabaseClient
import structlog

logger = structlog.get_logger()

# Base allocations per regime (% of deployable capital)
# Deployable = total_capital - crash_reserve (15%) - emergency (10%)
REGIME_ALLOCATIONS = {
    "BULL_TRENDING": {
        "A_M2_funding_rate":   0.30,
        "A_M1_triangular_arb": 0.20,
        "A_CEX_cross_arb":     0.15,
        "C_AI_crypto_news":    0.15,
        "D_GRID_trading":      0.10,
        "A_M4_futures_basis":  0.05,
        "D_DCA_volatility":    0.05,
        # A_FL (flash loan) = 0% — earns without consuming capital
    },
    "BULL_RANGING": {
        "A_M2_funding_rate":   0.30,
        "D_GRID_trading":      0.25,
        "A_M1_triangular_arb": 0.20,
        "C_AI_crypto_news":    0.10,
        "A_CEX_cross_arb":     0.10,
        "D_DCA_volatility":    0.05,
    },
    "VOLATILE_UP": {
        "A_M1_triangular_arb": 0.35,  # Most arb gaps appear during volatility
        "A_CEX_cross_arb":     0.30,
        "A_M2_funding_rate":   0.20,
        "C_AI_crypto_news":    0.10,
        "D_DCA_volatility":    0.05,
    },
    "CRASH_MINOR": {
        "A_M2_funding_rate":   0.25,  # Funding may turn negative = short harvest
        "A_M1_triangular_arb": 0.20,
        "A_CEX_cross_arb":     0.15,
        "D_SHORT_systematic":  0.20,  # Bear strategy activates
        "A_STAB_depeg":        0.15,  # Watch for stablecoin issues
        "C_FEAR_greed":        0.05,
    },
    "CRASH_MAJOR": {
        "D_SHORT_systematic":  0.35,  # Bear mode: shorts dominate
        "A_M1_triangular_arb": 0.20,
        "A_STAB_depeg":        0.25,  # High chance of stablecoin issues
        "C_FEAR_greed":        0.15,  # Extreme fear = accumulation signal
        "A_M2_funding_rate":   0.05,
    },
    "RECOVERY": {
        "A_M2_funding_rate":   0.30,
        "A_M1_triangular_arb": 0.20,
        "D_DCA_volatility":    0.25,  # Accumulate during recovery
        "A_CEX_cross_arb":     0.15,
        "C_AI_crypto_news":    0.10,
    },
    "BLACK_SWAN": {
        "A_M1_triangular_arb": 0.50,  # Math only — no directional risk
        "A_M2_funding_rate":   0.30,
        "A_CEX_cross_arb":     0.20,
        # Everything else paused
    },
}


class DynamicCapitalAllocator:

    def __init__(self, cache: TieredCache, db: SupabaseClient):
        self._cache = cache
        self._db = db
        self._node_id = os.getenv("NODE_ID", "singapore-01")

    async def compute_and_store_allocation(self) -> Dict[str, float]:
        """
        Compute current capital allocation and store in cache.
        Called every 5 minutes by scanner.
        """
        # Get current state
        regime_data = await self._cache.get("regime:current") or {}
        regime = regime_data.get("regime", "BULL_RANGING")

        current_capital = await self._cache.get("capital:current_usdc") or 0.0

        if current_capital <= 0:
            logger.warning("no_capital_for_allocation")
            return {}

        # Reserve buckets (always maintained)
        crash_reserve = current_capital * 0.15   # 15% for bear opportunities
        emergency = current_capital * 0.10       # 10% never traded
        deployable = current_capital - crash_reserve - emergency

        # Get regime allocations
        base_alloc = REGIME_ALLOCATIONS.get(regime, REGIME_ALLOCATIONS["BULL_RANGING"])

        # Convert percentages to USDC amounts
        allocations = {}
        for strategy_id, pct in base_alloc.items():
            usdc_amount = deployable * pct

            # Apply per-strategy caps from strategy_plugins table
            # (Cap loaded from cache, set during startup)
            cap_key = f"strategy_cap:{strategy_id}"
            cap_pct = await self._cache.get(cap_key) or 0.30
            max_usdc = current_capital * cap_pct

            allocations[strategy_id] = min(usdc_amount, max_usdc)

        # Cache for strategies to read
        await self._cache.set("capital:allocation", {
            "total": current_capital,
            "crash_reserve": crash_reserve,
            "emergency": emergency,
            "deployable": deployable,
            "per_strategy": allocations,
            "regime": regime,
        })

        # Store in Supabase for dashboard (fire-and-forget, non-blocking)
        import asyncio as _asyncio
        _upd = {
            "current_balance": current_capital,
            "reserved_crash": crash_reserve,
            "reinvestable": deployable,
            "updated_at": "now()",
        }
        def _write_pool():
            try:
                self._db.table("capital_pools").update(_upd).eq("pool_id", "crypto_sg").execute()
            except Exception:
                pass
        _asyncio.get_event_loop().run_in_executor(None, _write_pool)

        logger.info("allocation_updated",
                    regime=regime,
                    total=current_capital,
                    deployable=deployable,
                    strategies=len(allocations))

        return allocations

    def get_strategy_allocation(self, strategy_id: str) -> float:
        """
        Fast sync read for strategy to get its allocation.
        Reads from _RISK_STATE (in-memory, pre-computed).
        """
        # Strategies call this — returns USDC amount they can deploy
        # In practice they read from the cache which is pre-populated
        return 0.0  # Placeholder — real impl reads from cache sync
