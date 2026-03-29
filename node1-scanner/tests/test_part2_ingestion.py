"""Tests for Part 2 — ingestion layer."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, patch
from ingestion.market_normalizer import UnifiedMarket
from ingestion.ingestion_manager import MarketIngester
from latency.base_methods import TieredCache


def make_mock_markets(exchange: str, count: int) -> list:
    return [
        UnifiedMarket(
            market_id=f"{exchange}_BTC{i}USDT",
            exchange=exchange,
            symbol=f"BTC{i}USDT",
            price=50000.0 + i,
            volume_24h=1_000_000.0,
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_ingester_parallel_under_500ms():
    """Ingestion from all exchanges should complete under 500ms."""
    cache = TieredCache("redis://localhost:6379/0")

    ingester = MarketIngester(cache)

    # Mock all adapters to return fast
    ingester.binance.fetch_markets = AsyncMock(return_value=make_mock_markets("binance", 400))
    ingester.bybit.fetch_markets = AsyncMock(return_value=make_mock_markets("bybit", 200))
    ingester.okx.fetch_markets = AsyncMock(return_value=make_mock_markets("okx", 200))
    ingester.binance.get_triangular_markets = AsyncMock(return_value=[])
    ingester.bybit.fetch_funding_rates = AsyncMock(return_value={})

    start = time.perf_counter()
    markets = await ingester.get_all_markets()
    duration = time.perf_counter() - start

    assert len(markets) == 800
    assert duration < 0.5, f"Too slow: {duration:.3f}s > 0.5s"
    print(f"\u2713 Ingestion: 800 markets in {duration * 1000:.1f}ms")


@pytest.mark.asyncio
async def test_cross_exchange_gap_detection():
    """Cross-exchange gaps should be correctly calculated."""
    cache = TieredCache("redis://localhost:6379/0")
    ingester = MarketIngester(cache)

    # BTC is $50,000 on Binance but $50,300 on OKX (0.6% gap)
    markets = [
        UnifiedMarket(market_id="binance_BTCUSDT", exchange="binance", symbol="BTCUSDT", price=50000),
        UnifiedMarket(market_id="okx_BTCUSDT", exchange="okx", symbol="BTCUSDT", price=50300),
    ]
    exchange_markets = {
        "binance": {"BTCUSDT": markets[0]},
        "okx": {"BTCUSDT": markets[1]},
    }

    enriched = await ingester._enrich_cross_exchange_gaps(markets, exchange_markets)

    btc_binance = next(m for m in enriched if m.exchange == "binance")
    assert btc_binance.max_exchange_gap_pct > 0.5, "Gap should be detected"
    print(f"\u2713 Gap detected: {btc_binance.max_exchange_gap_pct:.2f}%")


def test_unified_market_schema():
    """UnifiedMarket must have all required fields."""
    market = UnifiedMarket(
        market_id="binance_BTCUSDT",
        exchange="binance",
        symbol="BTCUSDT",
        price=50000.0,
    )
    assert market.opportunity_score == 0.0
    assert market.volume_modifier == 1.0
    assert market.is_crypto is True
    assert market.funding.current_rate == 0.0
    print("\u2713 UnifiedMarket schema correct")
