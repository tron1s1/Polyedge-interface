"""
StrategyRouter — routes high-scoring markets to the correct strategy plugins.
Routes by reading market signals set by OpportunityScorer.
Each route publishes an event that the target strategy subscribes to.
"""
import asyncio
import os
from typing import List, Dict, Optional
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import AsyncEventBus, TieredCache, pack
from database.supabase_client import SupabaseClient
import structlog

logger = structlog.get_logger()

# Routing thresholds — all configurable
THRESHOLDS = {
    "triangular_arb_min_gap":   0.05,   # % gap for A_M1
    "cex_arb_min_gap":          0.15,   # % gap for A_CEX
    "funding_harvest_min_apy":  0.10,   # APR for A_M2
    "stablecoin_depeg_trigger": 0.99,   # Price below $0.99 → A_STAB
    "news_spike_threshold":     50.0,   # velocity score for C_AI
    "fear_extreme_low":         15,     # Fear/Greed below → C_FEAR
    "fear_extreme_high":        85,     # Fear/Greed above → C_FEAR + D_SHORT
    "grid_bot_max_vol_24h":     2.0,    # % 24h vol for D_GRID
    "min_opportunity_score":    20.0,   # Minimum score to route at all
}


class StrategyRouter:
    """
    Routes markets to strategy plugins via event bus.
    Each strategy listens for its event: ROUTE_{STRATEGY_ID}
    """

    def __init__(
        self,
        event_bus: AsyncEventBus,
        cache: TieredCache,
        db: SupabaseClient,
    ):
        self._bus = event_bus
        self._cache = cache
        self._db = db
        self._enabled_strategies: set = set()

    async def refresh_enabled_strategies(self) -> None:
        """Load which strategies are enabled from Supabase flags (non-blocking)."""
        try:
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._db.table("strategy_flags").select(
                    "strategy_id, enabled, mode"
                ).execute()
            )

            self._enabled_strategies = {
                row["strategy_id"]
                for row in (result.data or [])
                if row.get("enabled", False)
            }

            # Also update cache for fast reads
            await self._cache.set("flag:enabled_strategies",
                                  list(self._enabled_strategies))
        except Exception as e:
            logger.warning("strategy_flag_refresh_error", error=str(e))
            # Fall back to cached value
            cached = await self._cache.get("flag:enabled_strategies")
            if cached:
                self._enabled_strategies = set(cached)

    async def route_market(
        self, market: UnifiedMarket
    ) -> List[str]:
        """
        Determine which strategies should analyze this market.
        Returns list of strategy IDs that received routing events.
        Routing decision is based on market signals set by scorer.
        """
        if market.opportunity_score < THRESHOLDS["min_opportunity_score"]:
            return []

        routes = []

        # ── Mathematical certainty routes (highest priority) ───────────────

        # A_M1: Triangular arb — same exchange, guaranteed
        if (market.triangular_gap_pct > THRESHOLDS["triangular_arb_min_gap"]
                and "A_M1_triangular_arb" in self._enabled_strategies):
            routes.append("A_M1_triangular_arb")

        # A_CEX: Cross-exchange price gap — guaranteed with fast execution
        if (market.max_exchange_gap_pct > THRESHOLDS["cex_arb_min_gap"]
                and "A_CEX_cross_arb" in self._enabled_strategies):
            routes.append("A_CEX_cross_arb")

        # A_M2: Funding rate harvest — guaranteed recurring income
        if (abs(market.funding.rate_annualised) > THRESHOLDS["funding_harvest_min_apy"]
                and "A_M2_funding_rate" in self._enabled_strategies):
            routes.append("A_M2_funding_rate")

        # A_STAB: Stablecoin depeg — guaranteed return to $1
        if (market.is_stablecoin
                and market.price < THRESHOLDS["stablecoin_depeg_trigger"]
                and "A_STAB_depeg" in self._enabled_strategies):
            routes.append("A_STAB_depeg")

        # A_M6: Stat arb — check BTC/ETH ratio
        # (Handled separately by scanner as it needs both markets)

        # ── Technical speed routes ─────────────────────────────────────────

        # B_LIST: Listing announcement detected
        listing_signal = await self._cache.get(f"listing_signal:{market.symbol}")
        if listing_signal and "B_LIST_frontrun" in self._enabled_strategies:
            routes.append("B_LIST_frontrun")

        # ── Information edge routes ────────────────────────────────────────

        # C_AI: Breaking news spike
        if (market.news_velocity > THRESHOLDS["news_spike_threshold"]
                and "C_AI_crypto_news" in self._enabled_strategies):
            routes.append("C_AI_crypto_news")

        # C_FEAR: Fear/Greed extremes
        if (market.fear_greed_index < THRESHOLDS["fear_extreme_low"]
                or market.fear_greed_index > THRESHOLDS["fear_extreme_high"]):
            if "C_FEAR_greed" in self._enabled_strategies:
                routes.append("C_FEAR_greed")

        # ── Timing / leverage routes ───────────────────────────────────────

        # D_SHORT: Overbought + high funding = short opportunity
        if (market.funding.current_rate > 0.0005
                and market.price_change_4h > 3.0
                and "D_SHORT_systematic" in self._enabled_strategies):
            routes.append("D_SHORT_systematic")

        # D_GRID: Low volatility = grid bot opportunity
        if (abs(market.price_change_24h) < THRESHOLDS["grid_bot_max_vol_24h"]
                and "D_GRID_trading" in self._enabled_strategies):
            routes.append("D_GRID_trading")

        # D_DCA: High volatility = DCA opportunity
        if (abs(market.price_change_24h) > 5.0
                and "D_DCA_volatility" in self._enabled_strategies):
            routes.append("D_DCA_volatility")

        # ── Publish routing events to event bus ───────────────────────────
        if routes:
            # Merge router routes with scorer suggestions (scorer may have added some)
            existing = set(market.suggested_strategies or [])
            existing.update(routes)
            market.suggested_strategies = list(existing)
            for strategy_id in routes:
                await self._bus.publish(f"ROUTE_{strategy_id.upper()}", {
                    "market": market.to_dict(),
                    "strategy_id": strategy_id,
                    "opportunity_score": market.opportunity_score,
                })
            logger.debug("market_routed",
                         symbol=market.symbol,
                         strategies=routes,
                         score=market.opportunity_score)

        return routes

    async def route_all(
        self, markets: List[UnifiedMarket]
    ) -> Dict[str, List[str]]:
        """Route all top markets. Returns dict of symbol → strategy_ids."""
        # Refresh flags every 30 seconds (cache handles this)
        await self.refresh_enabled_strategies()

        results = {}
        for market in markets:
            routed = await self.route_market(market)
            if routed:
                results[market.symbol] = routed

        return results
