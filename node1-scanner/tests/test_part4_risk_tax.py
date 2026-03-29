"""Tests for Part 4 — risk module, capital allocator, tax engine."""
import time
import pytest
from core.kill_switch_bus import KillSwitchBus, _RISK_STATE
from core.india_tax_engine import IndiaTaxEngine
from latency.base_methods import TieredCache
from unittest.mock import MagicMock, AsyncMock


def test_pre_trade_check_under_001ms():
    """Pre-trade check must be under 0.001ms (dict lookup only)."""
    cache = MagicMock()
    bus = MagicMock()
    db = MagicMock()
    ksb = KillSwitchBus(cache, bus, db)

    # Set a known state
    _RISK_STATE.update({
        "global_kill": False,
        "blocked_strategies": set(),
        "kelly_multiplier": 0.75,
        "max_trade_size_usdc": 1000.0,
        "drawdown_pct": 5.0,
    })

    start = time.perf_counter()
    for _ in range(10_000):
        allowed, reason = ksb.pre_trade_check("A_M1_triangular_arb", 100.0)
    duration_per_call = (time.perf_counter() - start) * 1000 / 10_000

    assert allowed is True
    assert duration_per_call < 0.001, f"Too slow: {duration_per_call:.6f}ms"
    print(f"\u2713 Pre-trade check: {duration_per_call*1000:.3f}\u00b5s per call")


def test_pre_trade_blocks_killed_strategy():
    """Blocked strategy must be rejected."""
    cache = MagicMock()
    ksb = KillSwitchBus(cache, MagicMock(), MagicMock())
    _RISK_STATE["blocked_strategies"] = {"B_SNIPE_token"}
    _RISK_STATE["global_kill"] = False

    allowed, reason = ksb.pre_trade_check("B_SNIPE_token", 100.0)
    assert allowed is False
    assert "blocked" in reason.lower()
    print(f"\u2713 Blocked strategy rejected: {reason}")


def test_pre_trade_blocks_global_kill():
    """Global kill switch must block all trades."""
    cache = MagicMock()
    ksb = KillSwitchBus(cache, MagicMock(), MagicMock())
    _RISK_STATE["global_kill"] = True

    allowed, reason = ksb.pre_trade_check("A_M1_triangular_arb", 100.0)
    assert allowed is False
    _RISK_STATE["global_kill"] = False  # Reset for other tests


def test_pre_trade_blocks_excessive_leverage():
    """Leverage above 10x must be rejected — hardcoded rule."""
    cache = MagicMock()
    ksb = KillSwitchBus(cache, MagicMock(), MagicMock())
    _RISK_STATE["global_kill"] = False
    _RISK_STATE["blocked_strategies"] = set()

    allowed, reason = ksb.pre_trade_check("D_LEV_event_futures", 100.0, leverage=15.0)
    assert allowed is False
    assert "10x" in reason
    print(f"\u2713 Excessive leverage blocked: {reason}")


@pytest.mark.asyncio
async def test_tax_engine_30_percent():
    """Tax calculation must be 30% of profit."""
    cache = TieredCache("redis://localhost:6379/0")
    db = MagicMock()
    db.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock(return_value=None)))
    ))

    engine = IndiaTaxEngine(cache, db)

    # Mock the USD/INR rate
    await cache.set("forex:usd_inr", 84.0)
    await cache.set("tax:reserve_usdc", 0.0)
    await cache.set("capital:current_usdc", 5000.0)

    # $100 profit on Binance (foreign exchange — full manual TDS)
    calc = await engine.on_trade_closed(
        trade_id="test-1",
        strategy_id="A_M1_triangular_arb",
        pnl_usdc=100.0,
        exchange="binance",
        asset="BTC",
        gross_sell_value_usdc=5100.0,
    )

    # Tax: 30% of ₹8,400 (100 × 84) = ₹2,520 = $30
    assert abs(calc.tax_30pct_inr - 2520.0) < 1.0
    assert calc.amount_reinvested_usdc < 100.0  # Less than gross profit
    assert calc.amount_reserved_usdc > 0.0
    assert calc.amount_reinvested_usdc + calc.amount_reserved_usdc == pytest.approx(100.0, abs=0.01)
    print(f"\u2713 Tax: reserved=${calc.amount_reserved_usdc:.2f}, reinvested=${calc.amount_reinvested_usdc:.2f}")
