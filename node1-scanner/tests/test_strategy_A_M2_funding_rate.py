"""Tests for A_M2 Funding Rate Harvest — Part 1 (detection + position management)."""
import asyncio
import time
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from strategies.A_M2_funding_rate import (
    Strategy, StrategyConfig, FundingRateMonitor, PositionManager,
    DeltaNeutralCalculator, PaperFundingSimulator, FundingOpportunity,
    FundingDirection, OpenPosition, PositionStatus, DEFAULT_CONFIG,
)
from latency.base_methods import TieredCache


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
            eq=MagicMock(return_value=MagicMock(
                execute=AsyncMock(return_value=MagicMock(data=[]))
            ))
        )),
        update=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(execute=AsyncMock()))
        )),
    ))
    return db

def make_tax():
    tax = MagicMock()
    tax.on_trade_closed = AsyncMock(return_value=MagicMock(
        amount_reserved_usdc=30.0, amount_reinvested_usdc=70.0
    ))
    return tax


class TestStrategyMetadata:
    def test_required_fields_set(self):
        strat = Strategy(make_ks(), make_db(), make_tax())
        assert strat.STRATEGY_ID == "A_M2_funding_rate"
        assert strat.CATEGORY == "A_math"
        assert strat.VERSION == "v1-base"
        assert strat.NODE_ID == "singapore-01"
        print("✓ Strategy metadata correct")


class TestFundingRateMonitor:

    @pytest.mark.asyncio
    async def test_detects_high_apr_opportunity(self):
        """Monitor must detect symbols with APR above threshold."""
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        await cache.set("funding:bybit:BTCUSDT", {
            "rate": 0.0003,                        # 0.03% per 8h
            "annualised": 0.0003 * 3 * 365,        # = 32.85% APR
        })
        await cache.set("price:binance:BTCUSDT", 67000.0)

        config = StrategyConfig(cache)
        monitor = FundingRateMonitor(cache, config)
        opps = await monitor.scan_all_opportunities()

        btc_opps = [o for o in opps if o.symbol == "BTCUSDT"]
        assert len(btc_opps) > 0
        assert btc_opps[0].direction == FundingDirection.POSITIVE
        assert btc_opps[0].annualised_rate > 0.10  # Above 10% threshold
        print(f"✓ High APR detected: {btc_opps[0].annualised_rate:.2%} APR")

    @pytest.mark.asyncio
    async def test_skips_low_apr_symbols(self):
        """Monitor must skip symbols below MIN_APR_TO_OPEN."""
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        await cache.set("funding:bybit:XRPUSDT", {
            "rate": 0.00005,             # Very low = ~5.5% APR
            "annualised": 0.00005 * 3 * 365,
        })
        await cache.set("price:binance:XRPUSDT", 0.60)

        config = StrategyConfig(cache)
        monitor = FundingRateMonitor(cache, config)
        opps = await monitor.scan_all_opportunities()

        xrp_opps = [o for o in opps if o.symbol == "XRPUSDT"]
        assert len(xrp_opps) == 0, "Low APR should be skipped"
        print("✓ Low APR symbol correctly skipped")

    @pytest.mark.asyncio
    async def test_detects_negative_funding(self):
        """Monitor must detect negative funding for bear mode."""
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        await cache.set("funding:bybit:ETHUSDT", {
            "rate": -0.0004,                        # Negative rate
            "annualised": -0.0004 * 3 * 365,        # = -43.8% APR
        })
        await cache.set("price:binance:ETHUSDT", 3200.0)

        config = StrategyConfig(cache)
        monitor = FundingRateMonitor(cache, config)
        opps = await monitor.scan_all_opportunities()

        eth_neg = [o for o in opps if o.symbol == "ETHUSDT" and o.direction == FundingDirection.NEGATIVE]
        assert len(eth_neg) > 0
        print(f"✓ Negative funding detected: {eth_neg[0].annualised_rate:.2%} APR")

    @pytest.mark.asyncio
    async def test_monitor_speed_under_10ms(self):
        """Scanning all symbols from cache must complete in < 10ms."""
        cache = TieredCache("redis://localhost:6379/0")
        await cache.connect()

        # Set data for all monitored symbols
        for sym in DEFAULT_CONFIG["monitored_symbols"]:
            await cache.set(f"funding:bybit:{sym}", {"rate": 0.0001, "annualised": 0.11})
            await cache.set(f"price:binance:{sym}", 100.0)

        config = StrategyConfig(cache)
        monitor = FundingRateMonitor(cache, config)

        start = time.perf_counter()
        for _ in range(50):
            await monitor.scan_all_opportunities()
        avg_ms = (time.perf_counter() - start) * 1000 / 50

        assert avg_ms < 10.0, f"Too slow: {avg_ms:.2f}ms"
        print(f"✓ Monitor speed: {avg_ms:.2f}ms avg (50 runs)")


class TestPositionManager:

    def make_position(self, symbol="BTCUSDT", size=1000.0) -> OpenPosition:
        return OpenPosition(
            position_id="test-pos-1",
            symbol=symbol,
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=size,
            perp_size_usdc=size,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=size / 67000.0,
            entry_apr=0.329,
            current_apr=0.329,
        )

    def test_blocks_opening_beyond_max_positions(self):
        config = StrategyConfig(None)
        pm = PositionManager(None, MagicMock(), config)

        # Fill up to max
        for i in range(config.max_positions_open):
            pos = self.make_position(symbol=f"TOKEN{i}USDT")
            pos.position_id = f"pos-{i}"
            pm._positions[pos.position_id] = pos

        can_open, reason = pm.can_open_new()
        assert not can_open
        print(f"✓ Position cap enforced: {reason}")

    def test_prevents_duplicate_symbol(self):
        config = StrategyConfig(None)
        pm = PositionManager(None, MagicMock(), config)

        pos = self.make_position("BTCUSDT")
        pm._positions[pos.position_id] = pos

        assert pm.is_already_open("BTCUSDT") is True
        assert pm.is_already_open("ETHUSDT") is False
        print("✓ Duplicate symbol prevention works")

    def test_marks_positions_for_close_when_rate_drops(self):
        config = StrategyConfig(None)
        pm = PositionManager(None, MagicMock(), config)

        pos = self.make_position("BTCUSDT")
        pos.status = PositionStatus.HOLDING
        pm._positions[pos.position_id] = pos

        # Simulate rate dropping below hold threshold
        to_close = pm.get_positions_needing_close({"BTCUSDT": 0.02})  # 2% < 5% threshold
        assert len(to_close) == 1
        assert to_close[0].symbol == "BTCUSDT"
        print(f"✓ Position flagged for close when APR drops to 2% (min hold: {config.min_apr_to_hold:.0%})")


class TestDeltaNeutralCalculator:

    def test_delta_zero_when_balanced(self):
        pos = OpenPosition(
            position_id="test",
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=1000.0 / 67000.0,  # 0.01493 BTC
        )
        # Price unchanged = delta should be near zero
        delta = DeltaNeutralCalculator.calculate_delta(pos, 67000.0)
        assert abs(delta) < 0.001
        print(f"✓ Delta near zero when balanced: {delta:.6f}")

    def test_delta_positive_when_price_rises(self):
        pos = OpenPosition(
            position_id="test",
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=1000.0 / 67000.0,
        )
        # BTC rises 5% — spot value increases, perp stays same
        delta = DeltaNeutralCalculator.calculate_delta(pos, 67000.0 * 1.05)
        assert delta > 0, "Delta should be positive when price rises"
        assert delta < 0.10, "Delta should be small (< 10%)"
        print(f"✓ Delta positive after 5% price rise: {delta:.4f}")

    def test_funding_income_calculation(self):
        pos = OpenPosition(
            position_id="test",
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=0.01493,
        )
        income = DeltaNeutralCalculator.calculate_funding_income(pos, 0.0003)
        assert abs(income - 0.30) < 0.01  # $0.30 on $1000 at 0.03%
        print(f"✓ Funding income: ${income:.4f} per 8h on $1,000 at 0.03%")


class TestPaperSimulator:

    @pytest.mark.asyncio
    async def test_simulate_open_models_slippage(self):
        sim = PaperFundingSimulator()
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            current_rate_8h=0.0003,
            predicted_rate_8h=0.0003,
            annualised_rate=0.329,
            next_funding_time=datetime.now(timezone.utc),
            minutes_to_next=240.0,
            current_price=67000.0,
            priority_score=100.0,
        )
        result = await sim.simulate_open(opp, 1000.0)
        assert result["simulated"] is True
        assert result["spot_fill_price"] > 67000.0  # Slippage on buy
        assert result["perp_fill_price"] < 67000.0  # Slippage on short
        print(f"✓ Open simulated with slippage: "
              f"spot=${result['spot_fill_price']:.2f}, "
              f"perp=${result['perp_fill_price']:.2f}")

    def test_funding_payment_calculation(self):
        sim = PaperFundingSimulator()
        pos = OpenPosition(
            position_id="test",
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=0.01493,
        )
        payment = sim.simulate_funding_payment(pos, 0.0003)
        # Expected: $1000 × 0.03% × 0.998 discount = $0.2994
        assert 0.29 < payment < 0.31
        print(f"✓ Funding payment: ${payment:.4f} (expected ~$0.30)")


# ─── Part 2 Tests ────────────────────────────────────────────────────────────

class TestLiveExecutor:

    def test_live_executor_requires_perp_leverage_1(self):
        """Perp leverage in config must always be 1."""
        from strategies.A_M2_funding_rate import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["perp_leverage"] == 1, "Leverage must always be 1"
        print("✓ Perp leverage hardcoded to 1")

    @pytest.mark.asyncio
    async def test_execute_open_returns_error_on_kill_switch(self):
        """Live executor must abort if kill switch fires."""
        from strategies.A_M2_funding_rate import LiveFundingExecutor, FundingOpportunity, FundingDirection
        ks = make_ks(allow=False)
        executor = LiveFundingExecutor(ks)

        opp = FundingOpportunity(
            symbol="BTCUSDT", direction=FundingDirection.POSITIVE,
            current_rate_8h=0.0003, predicted_rate_8h=0.0003,
            annualised_rate=0.329, next_funding_time=datetime.now(timezone.utc),
            minutes_to_next=240, current_price=67000.0, priority_score=100,
        )
        result = await executor.execute_open(opp, 1000.0)
        assert result["success"] is False
        assert "Kill switch" in result["error"]
        print("✓ Live executor aborts on kill switch")


class TestPromotionGates:

    @pytest.mark.asyncio
    async def test_gates_fail_with_no_positions(self):
        from strategies.A_M2_funding_rate import FundingPromotionGates
        db = make_db()
        gates = FundingPromotionGates(db)
        gates._get_paper_positions = AsyncMock(return_value=[])
        gates._get_paper_payments = AsyncMock(return_value=[])
        result = await gates.check_all_gates()
        assert result["all_passed"] is False
        print("✓ Gates fail with no positions")

    @pytest.mark.asyncio
    async def test_gates_pass_with_good_performance(self):
        from strategies.A_M2_funding_rate import FundingPromotionGates
        from datetime import timedelta

        db = make_db()
        gates = FundingPromotionGates(db)

        now = datetime.now(timezone.utc)
        good_positions = [
            {
                "status": "closed",
                "spot_size_usdc": 1000.0,
                "perp_size_usdc": 1000.0,
                "total_pnl_usdc": 8.50,
                "opened_at": (now - timedelta(days=3)).isoformat(),
                "closed_at": now.isoformat(),
                "close_data": {"success": True},
            }
            for _ in range(6)
        ]
        good_payments = [{"id": str(i), "position_id": "x"} for i in range(15)]

        gates._get_paper_positions = AsyncMock(return_value=good_positions)
        gates._get_paper_payments = AsyncMock(return_value=good_payments)

        result = await gates.check_all_gates()
        assert result["gates"]["min_positions_opened"]["passed"] is True
        assert result["gates"]["min_funding_payments"]["passed"] is True
        assert result["gates"]["zero_execution_errors"]["passed"] is True
        print(f"✓ Promotion gates pass with good performance")


class TestFundingIncomeAccuracy:

    def test_daily_income_at_known_apr(self):
        """Verify income calculation at known 32% APR."""
        from strategies.A_M2_funding_rate import DeltaNeutralCalculator, OpenPosition, FundingDirection

        pos = OpenPosition(
            position_id="test",
            symbol="BTCUSDT",
            direction=FundingDirection.POSITIVE,
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=67000.0,
            perp_entry_price=67000.0,
            spot_quantity=0.01493,
        )

        rate_8h = 0.0003  # 0.03% per 8h = ~32.85% APR
        payment = DeltaNeutralCalculator.calculate_funding_income(pos, rate_8h)
        daily = payment * 3       # 3 payments per day
        monthly = daily * 30
        annual = daily * 365

        assert abs(payment - 0.30) < 0.01
        assert abs(daily - 0.90) < 0.01
        assert abs(monthly - 27.0) < 0.5
        print(f"✓ Income at 32% APR: ${payment:.2f}/8h | ${daily:.2f}/day | ${monthly:.2f}/mo | ${annual:.0f}/yr")

    def test_negative_funding_income(self):
        """Negative funding must also generate income (in opposite direction)."""
        from strategies.A_M2_funding_rate import DeltaNeutralCalculator, OpenPosition, FundingDirection

        pos = OpenPosition(
            position_id="test",
            symbol="ETHUSDT",
            direction=FundingDirection.NEGATIVE,  # We long perp
            spot_size_usdc=1000.0,
            perp_size_usdc=1000.0,
            spot_entry_price=3200.0,
            perp_entry_price=3200.0,
            spot_quantity=0.3125,
        )
        rate_8h = -0.0004  # Negative rate
        income = DeltaNeutralCalculator.calculate_funding_income(pos, rate_8h)
        # abs() ensures negative rates still calculate positive income
        assert income > 0, "Negative funding should still generate income"
        print(f"✓ Negative funding income: ${income:.4f} per 8h")
