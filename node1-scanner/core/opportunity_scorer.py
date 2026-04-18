"""
OpportunityScorer v2 — scores every market with 12 signals.
Higher score = more profitable opportunity.
Runs in parallel across all markets via B1 (asyncio.gather).
Performance target: 1,000 markets scored in < 1 second total.
"""
import asyncio
import time
from typing import List, Optional
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import TieredCache
import structlog

logger = structlog.get_logger()


class OpportunityScorer:
    """
    12-signal scoring engine. Single pass per market.
    All signals combine into one opportunity_score (0–300+).
    The scanner routes top-scoring markets to strategies.
    """

    def __init__(self, cache: TieredCache):
        self._cache = cache

    async def score_market(self, market: UnifiedMarket) -> UnifiedMarket:
        """
        Score a single market. All 12 signals computed.
        Returns market with opportunity_score and suggested_strategies set.
        """
        score = 0.0
        strategies = []

        # ─ SIGNAL 1: Volume spike (0–40 pts) ──────────────────────────────
        # Sudden trading = something happening the crowd knows about
        if market.volume_24h > 0 and market.volume_1h > 0:
            vol_ratio = market.volume_ratio  # 1h_vol / (24h_vol/24)
            if vol_ratio > 2.0:
                score += min((vol_ratio - 1.0) * 15, 40)

        # ─ SIGNAL 2: Price movement speed (0–30 pts) ──────────────────────
        # Fast price change = new information entering market
        abs_change_1h = abs(market.price_change_1h)
        if abs_change_1h > 0.5:
            score += min(abs_change_1h * 8, 30)

        # ─ SIGNAL 3: Cross-exchange gap → A_CEX (0–70 pts, highest!) ──────
        # LOOPHOLE 2: Price lag between exchanges = guaranteed arb
        if market.max_exchange_gap_pct > 0.15:
            score += min(market.max_exchange_gap_pct * 60, 70)
            if market.max_exchange_gap_pct > 0.15:
                strategies.append("A_CEX_cross_arb")

        # ─ SIGNAL 4: Triangular arb gap → A_M1 (0–80 pts) ────────────────
        # LOOPHOLE 1: Mathematical triangle violation = guaranteed profit
        if market.triangular_gap_pct > 0.05:
            score += min(market.triangular_gap_pct * 100, 80)
            strategies.append("A_M1_triangular_arb")

        # ─ SIGNAL 4b: Flash loan → A_FL (0–50 pts) ────────────────────────
        # Deep liquidity + extreme volume spike + tight spread = flash loan viable
        # Flash loans need: high volume, low spread, rapid price inefficiency
        if (market.volume_24h > 1_000_000
                and market.volume_ratio > 5.0
                and market.orderbook.spread_pct < 0.05):
            score += min(market.volume_ratio * 8, 50)
            strategies.append("A_FL_flash_loan")

        # ─ SIGNAL 4c: Futures basis → A_M4 (0–45 pts) ─────────────────────
        # Perpetual at premium/discount vs implied spot = cash-and-carry arb
        # Wide basis means perp and spot will converge → near-guaranteed spread
        _funding_apr = abs(market.funding.rate_annualised)
        if market.is_perpetual and _funding_apr > 0.05:  # > 5% APR = basis exists
            score += min(_funding_apr * 150, 45)
            strategies.append("A_M4_futures_basis")

        # ─ SIGNAL 4d: Statistical arb → A_M6 (0–35 pts) ───────────────────
        # Extreme orderbook imbalance on BTC-correlated asset = mean-reversion
        # Correlated pairs diverge then reconverge → stat arb edge
        if (market.is_btc_ladder
                and abs(market.orderbook_imbalance) > 0.6
                and market.volume_24h > 100_000):
            score += min(abs(market.orderbook_imbalance) * 35, 35)
            strategies.append("A_M6_stat_arb")

        # ─ SIGNAL 5: Funding rate → A_M2 (0–60 pts) ──────────────────────
        # High positive funding = longs paying a lot = harvest opportunity
        # High negative funding = bears paying = short harvest opportunity
        abs_funding = abs(market.funding.rate_annualised)
        if abs_funding > 0.10:  # > 10% APR
            score += min(abs_funding * 200, 60)
            strategies.append("A_M2_funding_rate")

        # ─ SIGNAL 6: Stablecoin depeg → A_STAB (0–90 pts, near-certain!) ─
        # When USDC/USDT depegs: buy and hold = guaranteed return to $1
        if market.is_stablecoin and market.price < 0.99:
            depeg_pct = (1.0 - market.price) * 100
            score += min(depeg_pct * 100, 90)  # Very high score — guaranteed
            strategies.append("A_STAB_depeg")

        # ─ SIGNAL 6b: Listing front-run → B_LIST (0–60 pts) ───────────────
        # Very new token + volume explosion = listing momentum window
        # Buy before the crowd pushes price up post-listing
        if market.is_new_token and market.token_age_hours < 48:
            listing_score = min((48 - market.token_age_hours) * 1.5, 40)
            if market.volume_ratio > 3.0:
                listing_score += 20
            score += listing_score
            strategies.append("B_LIST_frontrun")

        # ─ SIGNAL 6c: Bybit launchpool → B_BYBIT (0–50 pts) ───────────────
        # Bybit-listed new token with strong volume = launchpool farming window
        # Bybit incentivises staking into new pools; price pressure is predictable
        if (market.exchange == 'bybit'
                and market.is_new_token
                and market.token_age_hours < 72
                and market.volume_24h > 500_000):
            score += min(market.volume_ratio * 10, 50)
            strategies.append("B_BYBIT_launchpool")

        # ─ SIGNAL 7: News velocity → C_AI (0–25 pts) ─────────────────────
        # Reddit/Twitter + GDELT spike = crowd about to move the market
        if market.news_velocity > 30:
            score += min(market.news_velocity / 4, 25)
            if market.news_velocity > 50:
                strategies.append("C_AI_crypto_news")

        # ─ SIGNAL 8: Fear/Greed extremes → C_FEAR (0–40 pts) ────────────
        # Extreme fear < 15: historical 78% reversal
        # Extreme greed > 85: historical 73% pullback
        if market.fear_greed_index < 15:
            score += 40
            strategies.append("C_FEAR_greed")
        elif market.fear_greed_index > 85:
            score += 30
            strategies.append("C_FEAR_greed")
            strategies.append("D_SHORT_systematic")

        # ─ SIGNAL 9: Funding + overbought → D_SHORT (0–35 pts) ───────────
        # High positive funding + price overbought = short opportunity
        if market.funding.current_rate > 0.0005 and market.price_change_4h > 3.0:
            score += min(market.funding.current_rate * 30000 + market.price_change_4h * 3, 35)
            if "D_SHORT_systematic" not in strategies:
                strategies.append("D_SHORT_systematic")

        # ─ SIGNAL 10: Low volatility → D_GRID (0–30 pts) ─────────────────
        # Low ATR + sideways price = perfect for grid bot
        # Grid bot earns spread in ranging market
        if abs(market.price_change_24h) < 2.0 and abs(market.price_change_1h) < 0.5:
            score += 30
            strategies.append("D_GRID_trading")

        # ─ SIGNAL 10b: High volatility DCA → D_DCA (0–35 pts) ─────────────
        # Big drop on established coin = averaging down opportunity
        # Avoid new/small-cap tokens (pump-and-dump risk)
        if (market.price_change_24h < -5.0
                and market.volume_24h > 500_000
                and not market.is_new_token):
            score += min(abs(market.price_change_24h) * 3, 35)
            strategies.append("D_DCA_volatility")

        # ─ SIGNAL 10c: Pair long/short → D_PAIR (0–30 pts) ────────────────
        # Strong orderbook imbalance on liquid market = directional bias
        # Buy the dominant side, short the weak in same correlated sector
        if (abs(market.orderbook_imbalance) > 0.5
                and market.volume_24h > 1_000_000
                and not market.is_stablecoin
                and market.volume_ratio > 1.5):
            score += min(abs(market.orderbook_imbalance) * 30, 30)
            strategies.append("D_PAIR_long_short")

        # ─ SIGNAL 11: Liquidation cluster proximity (0–45 pts) ────────────
        # Near a large liquidation cluster = predictable cascade incoming
        if market.nearest_cluster_distance_pct < 3.0:
            proximity_score = (3.0 - market.nearest_cluster_distance_pct) * 15
            score += min(proximity_score, 45)

        # ─ SIGNAL 12: Volume modifier (multiplier, not additive) ──────────
        # Low-volume markets have BIGGER gaps and LESS competition
        score *= market.volume_modifier

        # ─ Finalize ───────────────────────────────────────────────────────
        market.opportunity_score = round(score, 2)
        market.suggested_strategies = list(set(strategies))  # dedup

        return market

    async def score_all(self, markets: List[UnifiedMarket]) -> List[UnifiedMarket]:
        """
        Score ALL markets in parallel.
        B1 pattern: asyncio.gather() — never sequential.
        Performance target: 1,000 markets in < 1 second.
        """
        start = time.perf_counter()
        scored = await asyncio.gather(
            *[self.score_market(m) for m in markets],
            return_exceptions=True
        )
        duration = (time.perf_counter() - start) * 1000

        # Filter exceptions
        clean = [m for m in scored if isinstance(m, UnifiedMarket)]

        logger.debug("scoring_complete",
                    total=len(markets),
                    scored=len(clean),
                    duration_ms=round(duration, 2))

        # Performance assertion
        if duration > 1000:
            logger.error("PERFORMANCE_VIOLATION",
                         duration_ms=duration,
                         target_ms=1000)

        return clean

    def get_top_opportunities(
        self,
        scored_markets: List[UnifiedMarket],
        top_n: int = 20
    ) -> List[UnifiedMarket]:
        """Return top N markets by opportunity score."""
        return sorted(
            [m for m in scored_markets if m.opportunity_score > 10],
            key=lambda m: m.opportunity_score,
            reverse=True
        )[:top_n]
