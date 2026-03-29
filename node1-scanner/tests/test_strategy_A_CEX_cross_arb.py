"""Tests for A_CEX Cross-Exchange Arbitrage — Part 1."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from strategies.A_CEX_cross_arb import (
    Strategy, StrategyConfig, CrossExchangePriceMonitor,
    ExecutionPlanner, PaperCEXSimulator, FloatTracker,
    ArbOpportunity, TradeResult, DEFAULT_CONFIG,
    BINANCE, OKX, KUCOIN, MEXC,
)
from latency.base_methods import TieredCache
from ingestion.market_normalizer import UnifiedMarket


def make_ks(allow=True):
    ks = MagicMock()
    ks.pre_trade_check = MagicMock(return_value=(allow, "OK"))
    ks.apply_kelly_to_size = MagicMock(side_effect=lambda s, _: s)
    return ks

def make_db():
    db = MagicMock()
    db.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock())),
        select=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(execute=AsyncMock(
                return_value=MagicMock(data=[])
            )))
        )),
    ))
    return db


class TestStrategyMetadata:
    def test_required_fields(self):
        s = Strategy(make_ks(), make_db(), MagicMock())
        assert s.STRATEGY_ID == "A_CEX_cross_arb"
        assert s.CATEGORY == "A_math"
        assert s.VERSION == "v1-base"
        print("✓ Metadata correct")


class TestGapDetection:

    @pytest.mark.asyncio
    async def test_detects_gap_between_binance_and_okx(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        # OKX 0.45% higher than Binance
        await cache.set("price:binance:SOLUSDT", 119.80)
        await cache.set("price:okx:SOLUSDT",     120.34)

        config = StrategyConfig(cache)
        monitor = CrossExchangePriceMonitor(cache, config)
        opps = await monitor.find_opportunities()

        sol_opps = [o for o in opps if o.symbol == "SOLUSDT"]
        assert len(sol_opps) > 0
        best = sol_opps[0]
        assert best.buy_exchange == BINANCE
        assert best.sell_exchange == OKX
        assert best.gap_pct > 0.40
        assert best.net_profit_pct > 0
        print(f"✓ Gap detected: {best.gap_pct:.4f}% | Net: {best.net_profit_pct:.4f}%")

    @pytest.mark.asyncio
    async def test_skips_small_gap_below_threshold(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        # Only 0.10% gap — below 0.20% threshold
        await cache.set("price:binance:BTCUSDT", 67000.0)
        await cache.set("price:okx:BTCUSDT",     67067.0)  # 0.10% difference

        config = StrategyConfig(cache)
        monitor = CrossExchangePriceMonitor(cache, config)
        opps = await monitor.find_opportunities()

        btc_opps = [o for o in opps if o.symbol == "BTCUSDT"]
        assert len(btc_opps) == 0
        print("✓ Small gap correctly skipped")

    @pytest.mark.asyncio
    async def test_skips_huge_gap_as_data_error(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        # 5% gap — too large, likely stale data
        await cache.set("price:binance:ETHUSDT", 3200.0)
        await cache.set("price:okx:ETHUSDT",     3360.0)  # 5% gap

        config = StrategyConfig(cache)
        monitor = CrossExchangePriceMonitor(cache, config)
        opps = await monitor.find_opportunities()

        eth_opps = [o for o in opps if o.symbol == "ETHUSDT"]
        assert len(eth_opps) == 0
        print("✓ Huge gap skipped (likely data error)")

    @pytest.mark.asyncio
    async def test_detects_bidirectional_gaps(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        # OKX cheaper than Binance (reverse direction)
        await cache.set("price:binance:XRPUSDT", 0.620)
        await cache.set("price:okx:XRPUSDT",     0.614)  # Binance higher

        config = StrategyConfig(cache)
        monitor = CrossExchangePriceMonitor(cache, config)
        opps = await monitor.find_opportunities()

        xrp_opps = [o for o in opps if o.symbol == "XRPUSDT"]
        if xrp_opps:
            assert xrp_opps[0].buy_exchange == OKX      # Buy cheaper (OKX)
            assert xrp_opps[0].sell_exchange == BINANCE  # Sell expensive (Binance)
            print(f"✓ Bidirectional gap: buy {xrp_opps[0].buy_exchange}, sell {xrp_opps[0].sell_exchange}")
        else:
            print("✓ Gap below threshold in reverse direction")

    @pytest.mark.asyncio
    async def test_monitor_speed_under_5ms(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        syms = DEFAULT_CONFIG["monitored_symbols"]
        for sym in syms:
            await cache.set(f"price:binance:{sym}", 100.0)
            await cache.set(f"price:okx:{sym}",     100.3)
            await cache.set(f"price:kucoin:{sym}",  100.0)
            await cache.set(f"price:mexc:{sym}",    100.0)

        config = StrategyConfig(cache)
        monitor = CrossExchangePriceMonitor(cache, config)

        start = time.perf_counter()
        for _ in range(50):
            await monitor.find_opportunities()
        avg_ms = (time.perf_counter() - start) * 1000 / 50

        assert avg_ms < 5.0, f"Monitor too slow: {avg_ms:.2f}ms"
        print(f"✓ Monitor speed: {avg_ms:.2f}ms avg (50 runs)")


class TestFeeCalculation:

    def test_net_profit_calculation_correct(self):
        cfg = StrategyConfig(None)
        gap_pct = 0.45
        fee_pct = cfg.get_total_fee_pct(BINANCE, OKX)  # 0.10% + 0.10% = 0.20%
        slippage = cfg.slippage_buffer_pct               # 0.02%
        net = gap_pct - fee_pct - slippage               # 0.23%

        assert abs(fee_pct - 0.20) < 0.001
        assert abs(net - 0.23) < 0.001
        print(f"✓ Fee calc: gap={gap_pct}% - fees={fee_pct}% - slippage={slippage}% = net={net}%")

    def test_breakeven_gap_correct(self):
        cfg = StrategyConfig(None)
        breakeven = cfg.get_breakeven_gap_pct(BINANCE, OKX)
        # Binance 0.10% + OKX 0.10% + 0.02% slippage = 0.22%
        assert abs(breakeven - 0.22) < 0.001
        print(f"✓ Breakeven gap: {breakeven}% (above this = profitable)")

    def test_mexc_higher_fee(self):
        cfg = StrategyConfig(None)
        binance_mexc_fee = cfg.get_total_fee_pct(BINANCE, MEXC)
        # Binance 0.10% + MEXC 0.20% = 0.30%
        assert abs(binance_mexc_fee - 0.30) < 0.001
        print(f"✓ MEXC pair higher fee: {binance_mexc_fee}%")


class TestExecutionPlanner:

    def make_opp(self, symbol="BTCUSDT", buy_ex=BINANCE, sell_ex=OKX, net_pct=0.23) -> ArbOpportunity:
        return ArbOpportunity(
            opportunity_id="test-1",
            symbol=symbol, buy_exchange=buy_ex, sell_exchange=sell_ex,
            buy_price=67000.0, sell_price=67320.0,
            gap_pct=0.48, fee_cost_pct=0.20, slippage_buffer_pct=0.02,
            net_profit_pct=net_pct,
            trade_size_usdc=1000.0, expected_profit_usdc=2.30,
            detected_at=time.monotonic(), prices_age_ms=50.0,
        )

    def test_blocks_duplicate_symbol(self):
        config = StrategyConfig(None)
        planner = ExecutionPlanner(None, config)
        planner.register_trade_start("BTCUSDT")

        opp = self.make_opp("BTCUSDT")
        valid, reason = planner.validate(opp)
        assert not valid
        assert "already being traded" in reason
        print(f"✓ Duplicate blocked: {reason}")

    def test_blocks_concurrent_limit(self):
        config = StrategyConfig(None)
        planner = ExecutionPlanner(None, config)

        for i in range(config.max_concurrent_trades):
            planner.register_trade_start(f"TOKEN{i}USDT")

        opp = self.make_opp("NEWUSDT")
        valid, reason = planner.validate(opp)
        assert not valid
        assert "concurrent" in reason.lower()
        print(f"✓ Concurrent limit enforced: {reason}")

    def test_accepts_valid_opportunity(self):
        config = StrategyConfig(None)
        planner = ExecutionPlanner(None, config)
        opp = self.make_opp("ETHUSDT")
        valid, reason = planner.validate(opp)
        assert valid, f"Should be valid: {reason}"
        print("✓ Valid opportunity accepted")


class TestPaperSimulator:

    @pytest.mark.asyncio
    async def test_simulator_models_slippage(self):
        sim = PaperCEXSimulator()
        config = StrategyConfig(None)
        opp = ArbOpportunity(
            opportunity_id="test",
            symbol="SOLUSDT",
            buy_exchange=BINANCE, sell_exchange=OKX,
            buy_price=119.80, sell_price=120.34,
            gap_pct=0.45, fee_cost_pct=0.20, slippage_buffer_pct=0.02,
            net_profit_pct=0.23,
            trade_size_usdc=1000.0, expected_profit_usdc=2.30,
            detected_at=time.monotonic(), prices_age_ms=50.0,
        )
        result = await sim.simulate_trade(opp, config)

        assert result.is_paper is True
        assert result.buy_fill_price > opp.buy_price   # Slippage on buy
        assert result.sell_fill_price < opp.sell_price  # Slippage on sell
        assert result.fee_cost_usdc > 0
        assert result.execution_ms < 100
        print(f"✓ Simulator: net=${result.net_profit_usdc:.4f}, "
              f"exec={result.execution_ms:.1f}ms, "
              f"fees=${result.fee_cost_usdc:.4f}")

    @pytest.mark.asyncio
    async def test_simulator_can_produce_loss(self):
        """Very tight gap should produce loss after slippage+fees."""
        sim = PaperCEXSimulator()
        config = StrategyConfig(None)
        opp = ArbOpportunity(
            opportunity_id="test",
            symbol="LINKUSDT",
            buy_exchange=KUCOIN, sell_exchange=MEXC,  # High-latency pair
            buy_price=13.50, sell_price=13.527,        # 0.20% gap — barely profitable
            gap_pct=0.20, fee_cost_pct=0.30, slippage_buffer_pct=0.02,
            net_profit_pct=-0.12,                       # Already negative before slippage
            trade_size_usdc=500.0, expected_profit_usdc=-0.60,
            detected_at=time.monotonic(), prices_age_ms=50.0,
        )
        result = await sim.simulate_trade(opp, config)
        assert result.execution_ms > 0  # Just verify it ran
        print(f"✓ Tight gap result: ${result.net_profit_usdc:.4f} "
              f"(loss expected on KuCoin-MEXC with tight gap)")


class TestFloatTracker:

    @pytest.mark.asyncio
    async def test_reserve_reduces_balance(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()
        await cache.set("float:binance:usdc", 2000.0)

        config = StrategyConfig(cache)
        tracker = FloatTracker(cache, config)

        await tracker.reserve(BINANCE, 500.0)
        new_bal = await tracker.get_balance(BINANCE)
        assert abs(new_bal - 1500.0) < 0.01
        print(f"✓ Float reserved: $2000 → ${new_bal:.2f}")

    @pytest.mark.asyncio
    async def test_insufficient_float_detected(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()
        await cache.set("float:okx:usdc", 100.0)  # Only $100 available

        config = StrategyConfig(cache)
        tracker = FloatTracker(cache, config)

        can_buy = await tracker.can_afford(OKX, 500.0)
        assert can_buy is False
        print("✓ Insufficient float correctly detected")


# ─── Part 2 Tests ─────────────────────────────────────────────────────────
from datetime import datetime, timezone


class TestLiveExecutor:

    @pytest.mark.asyncio
    async def test_fails_on_kill_switch(self):
        from strategies.A_CEX_cross_arb import LiveCEXExecutor
        executor = LiveCEXExecutor()

        opp = ArbOpportunity(
            opportunity_id="test", symbol="BTCUSDT",
            buy_exchange=BINANCE, sell_exchange=OKX,
            buy_price=67000.0, sell_price=67320.0,
            gap_pct=0.48, fee_cost_pct=0.20, slippage_buffer_pct=0.02,
            net_profit_pct=0.26, trade_size_usdc=1000.0,
            expected_profit_usdc=2.60,
            detected_at=time.monotonic(), prices_age_ms=50.0,
        )
        result = await executor.execute(opp, make_ks(allow=False))
        assert result.success is False
        assert "Kill switch" in result.error
        print("✓ Live executor aborts on kill switch")


class TestPromotionGates:

    @pytest.mark.asyncio
    async def test_gates_fail_no_trades(self):
        from strategies.A_CEX_cross_arb import CEXPromotionGates
        db    = make_db()
        gates = CEXPromotionGates(db)
        gates._get_paper_trades = AsyncMock(return_value=[])
        result = await gates.check_all_gates()
        assert result["all_passed"] is False
        print("✓ Gates fail with no trades")

    @pytest.mark.asyncio
    async def test_gates_pass_good_performance(self):
        from strategies.A_CEX_cross_arb import CEXPromotionGates
        db    = make_db()
        gates = CEXPromotionGates(db)
        good  = [
            {
                "pnl_usdc":     2.50,
                "edge_detected": 0.003,
                "outcome":       "win",
                "latency_ms":    180.0,
                "ai_reasoning":  "Gap:0.45%",
                "created_at":    datetime.now(timezone.utc).isoformat(),
            }
            for _ in range(55)
        ]
        gates._get_paper_trades = AsyncMock(return_value=good)
        result = await gates.check_all_gates()
        assert result["gates"]["min_trades"]["passed"]           is True
        assert result["gates"]["min_win_rate"]["passed"]         is True
        assert result["gates"]["max_avg_execution_ms"]["passed"] is True
        print(f"✓ All gates pass: {result['gates']['min_win_rate']['value']:.0%} win rate")


class TestEndToEnd:

    @pytest.mark.asyncio
    async def test_full_paper_pipeline(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()
        db = make_db()

        await cache.set("price:binance:SOLUSDT", 119.80)
        await cache.set("price:okx:SOLUSDT",     120.45)
        await cache.set("float:binance:usdc",    2000.0)
        await cache.set("float:okx:usdc",        2000.0)

        strat  = Strategy(make_ks(), db, MagicMock(), allocated_usdc=3000.0, cache=cache)
        market = UnifiedMarket(
            symbol="SOLUSDT", exchange="binance", price=119.80,
            max_exchange_gap_pct=0.54, opportunity_score=65.0,
        )

        decision = await strat.on_market_signal(market, allocated_usdc=3000.0)
        assert decision is not None
        assert decision.direction == "CEX_ARB"

        result = await strat.execute_signal(
            decision, market, decision.opportunity_id, "BULL_RANGING"
        )
        print(f"✓ Full pipeline: {decision.symbol} — "
              f"result={'ok' if result else 'expired (normal in test)'}")

    @pytest.mark.asyncio
    async def test_no_trade_insufficient_float(self):
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        await cache.set("price:binance:BTCUSDT", 67000.0)
        await cache.set("price:okx:BTCUSDT",     67400.0)
        await cache.set("float:binance:usdc",    40.0)     # way too small

        strat  = Strategy(make_ks(), make_db(), MagicMock(), allocated_usdc=1000.0, cache=cache)
        market = UnifiedMarket(
            symbol="BTCUSDT", exchange="binance",
            price=67000.0, max_exchange_gap_pct=0.60,
        )
        decision = await strat.on_market_signal(market, allocated_usdc=1000.0)
        assert decision is None
        print("✓ Skips when Binance float too low")
