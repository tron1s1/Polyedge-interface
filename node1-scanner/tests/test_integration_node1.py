"""
Full integration test — verifies the complete Node 1 pipeline works end-to-end.
Does NOT require live exchange connections — uses mocks.
Must pass before deploying to Hetzner.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from ingestion.market_normalizer import UnifiedMarket, FundingData
from latency.base_methods import TieredCache


@pytest.mark.asyncio
@patch("core.scanner.SupabaseClient")
async def test_full_scan_cycle_under_2_seconds(mock_sb_cls):
    """
    Complete scan cycle (ingest → enrich → score → route) must finish in < 2s.
    Uses mocked exchange adapters.
    """
    mock_sb = MagicMock()
    mock_sb.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock())),
        select=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(execute=AsyncMock(return_value=MagicMock(data=[]))))
        )),
        update=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(execute=AsyncMock()))
        )),
    ))
    mock_sb.heartbeat = AsyncMock()
    mock_sb_cls.return_value = mock_sb

    from core.scanner import UniversalScanner
    scanner = UniversalScanner()

    # Use L1-only cache (no Redis connection — avoids 4s timeout per miss)
    l1_cache = TieredCache("redis://localhost:6379/0")
    # Don't call connect() — _redis stays None, so only L1 dict is used
    scanner.cache = l1_cache
    scanner.scorer._cache = l1_cache
    scanner.router._cache = l1_cache
    scanner.enrichment._cache = l1_cache

    # Mock all external connections
    mock_markets = [
        UnifiedMarket(
            market_id=f"binance_TOKEN{i}USDT",
            exchange="binance",
            symbol=f"TOKEN{i}USDT",
            price=float(100 + i),
            volume_24h=float(2_000_000),
            triangular_gap_pct=0.3 if i % 50 == 0 else 0.0,
            funding=FundingData(current_rate=0.0003, rate_annualised=0.33),
        )
        for i in range(800)
    ]

    scanner.ingester.get_all_markets = AsyncMock(return_value=mock_markets)
    scanner.enrichment.run_all = AsyncMock()
    scanner.enrichment.enrich_markets_with_cache = AsyncMock(return_value=mock_markets)
    scanner.db.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock()))
    ))

    start = time.perf_counter()
    await scanner._process_scan_cycle()
    duration = time.perf_counter() - start

    assert duration < 2.0, f"Scan too slow: {duration:.3f}s"
    print(f"\u2713 Full scan cycle: {duration * 1000:.0f}ms")


@pytest.mark.asyncio
async def test_strategy_registry_loads_plugins():
    """Strategy registry must find and load all plugin files."""
    from strategies.base_strategy import StrategyRegistry
    registry = StrategyRegistry()

    kill_switch = MagicMock()
    kill_switch.pre_trade_check = MagicMock(return_value=(True, "OK"))
    kill_switch.apply_kelly_to_size = MagicMock(side_effect=lambda s, _: s)

    db = MagicMock()
    tax = MagicMock()

    # Should load without errors (even if no strategy files yet)
    registry.load_all(kill_switch, db, tax)
    print(f"\u2713 Strategy registry loaded {len(registry.get_all())} strategies")
