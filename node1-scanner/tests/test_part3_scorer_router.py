"""Tests for Part 3 — scorer, router, regime."""
import asyncio
import time
import pytest
from ingestion.market_normalizer import UnifiedMarket, FundingData
from core.opportunity_scorer import OpportunityScorer
from latency.base_methods import TieredCache


@pytest.mark.asyncio
async def test_scorer_1000_markets_under_1_second():
    """CRITICAL: Must score 1000 markets in under 1 second."""
    cache = TieredCache("redis://localhost:6379/0")
    scorer = OpportunityScorer(cache)

    markets = [
        UnifiedMarket(
            market_id=f"binance_TOKEN{i}USDT",
            exchange="binance",
            symbol=f"TOKEN{i}USDT",
            price=float(100 + i),
            volume_24h=float(1_000_000 * (i % 10 + 1)),
            volume_1h=float(50_000 * (i % 5 + 1)),
            price_change_24h=float((i % 10) - 5),
            price_change_1h=float((i % 4) - 2),
        )
        for i in range(1000)
    ]

    start = time.perf_counter()
    scored = await scorer.score_all(markets)
    duration = time.perf_counter() - start

    assert len(scored) == 1000
    assert duration < 1.0, f"PERFORMANCE VIOLATION: {duration:.3f}s > 1.0s"
    print(f"\u2713 Scored 1000 markets in {duration * 1000:.1f}ms")


@pytest.mark.asyncio
async def test_triangular_arb_gets_high_score():
    """Market with triangular arb gap must score > 70."""
    cache = TieredCache("redis://localhost:6379/0")
    scorer = OpportunityScorer(cache)

    market = UnifiedMarket(
        market_id="binance_BTCUSDT",
        exchange="binance",
        symbol="BTCUSDT",
        price=50000.0,
        triangular_gap_pct=0.80,  # 0.80% gap — very profitable
        volume_24h=5_000_000,
    )

    scored = await scorer.score_market(market)
    assert scored.opportunity_score > 70, f"Score too low: {scored.opportunity_score}"
    assert "A_M1_triangular_arb" in scored.suggested_strategies
    print(f"\u2713 Triangular arb score: {scored.opportunity_score:.1f}")


@pytest.mark.asyncio
async def test_funding_rate_routes_to_a_m2():
    """High funding rate must route to A_M2 strategy."""
    cache = TieredCache("redis://localhost:6379/0")
    scorer = OpportunityScorer(cache)

    market = UnifiedMarket(
        market_id="bybit_BTCUSDT",
        exchange="bybit",
        symbol="BTCUSDT",
        price=50000.0,
        market_type="perpetual",
        is_perpetual=True,
        funding=FundingData(current_rate=0.0003, rate_annualised=0.0003 * 3 * 365),
    )

    scored = await scorer.score_market(market)
    assert "A_M2_funding_rate" in scored.suggested_strategies
    print(f"\u2713 Funding rate routed to A_M2. Score: {scored.opportunity_score:.1f}")


@pytest.mark.asyncio
async def test_stablecoin_depeg_gets_max_priority():
    """Depegged stablecoin must get the highest score."""
    cache = TieredCache("redis://localhost:6379/0")
    scorer = OpportunityScorer(cache)

    market = UnifiedMarket(
        market_id="binance_USDCUSDT",
        exchange="binance",
        symbol="USDCUSDT",
        price=0.95,  # Depegged 5%!
        is_stablecoin=True,
        volume_24h=100_000_000,
    )

    scored = await scorer.score_market(market)
    assert scored.opportunity_score > 80, "Depeg should score very high"
    assert "A_STAB_depeg" in scored.suggested_strategies
    print(f"\u2713 Stablecoin depeg score: {scored.opportunity_score:.1f}")
