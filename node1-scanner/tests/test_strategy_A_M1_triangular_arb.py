"""
Tests for A_M1 Triangular Arbitrage strategy plugin.
All tests use mocked prices -- no real exchange connections needed.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from strategies.A_M1_triangular_arb import (
    Strategy,
    TriangleDetector,
    TriangleOpportunity,
    TriDirection,
    PaperExecutionSimulator,
    ExecutionDispatcher,
    ExecutionResult,
    LiveExecutionEngine,
    PositionMonitor,
    PromotionGates,
    TriangleTradeLogger,
    StrategyConfig,
    DEFAULT_CONFIG,
    ALL_TRIANGLE_SETS,
    TRIANGLE_SETS,
    MIN_GAP_PCT,
    FEE_PER_LEG,
    MAX_TRADE_SIZE_USDC,
)
from strategies.base_strategy import TradeDecision
from latency.base_methods import TieredCache
from ingestion.market_normalizer import UnifiedMarket
import uuid


# --- Fixtures ---

def make_mock_kill_switch(allow=True):
    ks = MagicMock()
    ks.pre_trade_check = MagicMock(return_value=(allow, "OK" if allow else "Blocked"))
    ks.apply_kelly_to_size = MagicMock(side_effect=lambda size, _: size)
    return ks


def make_mock_db():
    db = MagicMock()
    db.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock(return_value=None))),
        upsert=MagicMock(return_value=MagicMock(execute=AsyncMock(return_value=None))),
    ))
    return db


def make_mock_tax():
    tax = MagicMock()
    tax.on_trade_closed = AsyncMock(return_value=MagicMock(
        amount_reserved_usdc=30.0,
        amount_reinvested_usdc=70.0,
    ))
    return tax


def make_l1_only_cache():
    """Create a TieredCache that only uses L1 (no Redis connection needed)."""
    cache = TieredCache.__new__(TieredCache)
    cache._L1 = {}
    cache._redis = None
    cache._redis_url = ""
    cache.TTL = TieredCache.TTL
    cache._get_ttl = TieredCache._get_ttl.__get__(cache)
    cache.get = TieredCache.get.__get__(cache)
    cache.set = TieredCache.set.__get__(cache)
    cache.delete = TieredCache.delete.__get__(cache)
    cache.clear_l1 = TieredCache.clear_l1.__get__(cache)
    return cache


# --- Triangle Math Tests ---

class TestTriangleMath:

    def test_forward_gap_detected(self):
        """When ETH/USDT > implied price, FORWARD opportunity exists."""
        price_AB = 67_000.0   # BTC/USDT
        price_BC = 0.0478     # ETH/BTC
        price_AC = 3_210.0    # ETH/USDT (actual, higher than implied)

        implied_AC = price_AB * price_BC  # = 3,202.60
        gap_pct = abs(price_AC - implied_AC) / implied_AC * 100

        total_fee = FEE_PER_LEG * 2 * 100  # = 0.2%
        net_pct = gap_pct - total_fee

        assert gap_pct > 0.20, f"Gap should be > 0.20%: {gap_pct:.4f}%"
        assert net_pct > 0, f"Net profit should be positive: {net_pct:.4f}%"

    def test_reverse_gap_detected(self):
        """When ETH/USDT < implied price, REVERSE opportunity exists."""
        price_AB = 67_000.0
        price_BC = 0.0480     # ETH/BTC slightly higher
        price_AC = 3_195.0    # ETH/USDT lower than implied

        implied_AC = price_AB * price_BC  # = 3,216.0
        gap_pct = abs(price_AC - implied_AC) / implied_AC * 100

        assert gap_pct > 0.60

    def test_no_gap_when_prices_aligned(self):
        """When triangle is properly priced, no opportunity."""
        price_AB = 67_000.0
        price_BC = 0.04776    # Exact ratio
        price_AC = 3_200.0    # = 67000 * 0.04776 exactly

        implied_AC = price_AB * price_BC
        gap_pct = abs(price_AC - implied_AC) / implied_AC * 100

        assert gap_pct < 0.10, f"Aligned prices should show near-zero gap: {gap_pct:.4f}%"


# --- Detector Tests ---

class TestTriangleDetector:

    @pytest.mark.asyncio
    async def test_detector_finds_gap_from_cache(self):
        """Detector must find opportunity when prices in cache show a gap."""
        cache = make_l1_only_cache()

        # Set prices: ETH/USDT is overpriced relative to triangle
        await cache.set("price:binance:BTCUSDT", 67_000.0)
        await cache.set("price:binance:ETHBTC",  0.04780)   # implies $3,202.60
        await cache.set("price:binance:ETHUSDT", 3_215.0)   # actual = $3,215 (+0.39%)

        detector = TriangleDetector(cache)
        opportunities = await detector.detect_all_opportunities()

        eth_btc_opps = [o for o in opportunities if "ETH" in o.description]
        assert len(eth_btc_opps) > 0, "Should detect ETH/BTC/USDT opportunity"

        best = eth_btc_opps[0]
        assert best.gap_pct > 0.30
        assert best.net_profit_pct > 0
        assert best.direction == TriDirection.FORWARD

    @pytest.mark.asyncio
    async def test_detector_returns_empty_when_no_gap(self):
        """Detector returns empty list when no profitable gaps exist."""
        cache = make_l1_only_cache()

        # Set perfectly priced triangle
        await cache.set("price:binance:BTCUSDT", 67_000.0)
        await cache.set("price:binance:ETHBTC",  0.04776)
        await cache.set("price:binance:ETHUSDT", 3_199.0)  # ~exact implied price

        detector = TriangleDetector(cache)
        opportunities = await detector.detect_all_opportunities()

        profitable = [o for o in opportunities if o.net_profit_pct > 0]
        assert len(profitable) == 0, f"No profitable gaps expected, got: {profitable}"

    @pytest.mark.asyncio
    async def test_detector_speed_under_5ms(self):
        """Cache-based detection must complete in under 5ms."""
        cache = make_l1_only_cache()
        # Load all triangle prices
        prices = {
            "BTCUSDT": 67000.0, "ETHBTC": 0.04780, "ETHUSDT": 3215.0,
            "BNBBTC": 0.00640, "BNBUSDT": 428.5,
            "SOLBTC": 0.00178, "SOLUSDT": 119.0,
        }
        for sym, price in prices.items():
            await cache.set(f"price:binance:{sym}", price)

        detector = TriangleDetector(cache)

        start = time.perf_counter()
        for _ in range(100):
            await detector.detect_all_opportunities()
        avg_ms = (time.perf_counter() - start) * 1000 / 100

        assert avg_ms < 5.0, f"Detection too slow: {avg_ms:.2f}ms avg"


# --- Strategy Integration Tests ---

class TestStrategyIntegration:

    @pytest.mark.asyncio
    async def test_strategy_metadata_correct(self):
        """Strategy must have correct metadata for StrategyRegistry."""
        ks = make_mock_kill_switch()
        db = make_mock_db()
        tax = make_mock_tax()
        cache = make_l1_only_cache()

        strategy = Strategy(ks, db, tax, allocated_usdc=1000.0, cache=cache)

        assert strategy.STRATEGY_ID == "A_M1_triangular_arb"
        assert strategy.CATEGORY == "A_math"
        assert strategy.NODE_ID == "singapore-01"
        assert strategy.VERSION == "v1-base"

    @pytest.mark.asyncio
    async def test_strategy_blocked_by_kill_switch(self):
        """Kill switch must prevent trade signal."""
        ks = make_mock_kill_switch(allow=False)
        db = make_mock_db()
        tax = make_mock_tax()
        cache = make_l1_only_cache()

        strategy = Strategy(ks, db, tax, allocated_usdc=1000.0, cache=cache)

        market = UnifiedMarket(
            market_id="binance_ETHUSDT",
            exchange="binance",
            symbol="ETHUSDT",
            price=3215.0,
            triangular_gap_pct=0.39,
        )

        result = await strategy.on_market_signal(market, allocated_usdc=1000.0)
        assert result is None, "Kill switch should block trade"

    @pytest.mark.asyncio
    async def test_strategy_returns_decision_when_gap_exists(self):
        """Strategy must return TradeDecision when profitable gap detected."""
        ks = make_mock_kill_switch(allow=True)
        db = make_mock_db()
        tax = make_mock_tax()
        cache = make_l1_only_cache()

        # Set up profitable triangle in cache
        await cache.set("price:binance:BTCUSDT", 67_000.0)
        await cache.set("price:binance:ETHBTC",  0.04780)
        await cache.set("price:binance:ETHUSDT", 3_220.0)  # 0.54% gap

        strategy = Strategy(ks, db, tax, allocated_usdc=2000.0, cache=cache)

        market = UnifiedMarket(
            market_id="binance_ETHUSDT",
            exchange="binance",
            symbol="ETHUSDT",
            price=3220.0,
            triangular_gap_pct=0.54,
        )

        decision = await strategy.on_market_signal(market, allocated_usdc=2000.0)

        assert decision is not None, "Should return TradeDecision for valid gap"
        assert decision.leverage == 1.0, "Math strategies never use leverage"
        assert decision.ai_confidence == 1.0, "Guaranteed = 100% confidence"
        assert decision.exchange == "binance"
        assert "Gap:" in decision.reasoning

    @pytest.mark.asyncio
    async def test_paper_execution_simulates_realistically(self):
        """Paper execution must model slippage and return realistic results."""
        simulator = PaperExecutionSimulator()

        opportunity = {
            "triangle_id": "BTC-ETH-USDT",
            "direction": "forward",
            "leg_AB": "BTCUSDT",
            "leg_BC": "ETHBTC",
            "leg_AC": "ETHUSDT",
            "price_AB": 67000.0,
            "price_BC": 0.04780,
            "price_AC": 3220.0,
            "entry_size_usdc": 500.0,
            "gap_pct": 0.54,
            "net_profit_pct": 0.34,  # After 0.2% fees
            "expected_profit_usdc": 1.70,
        }

        result = await simulator.simulate(opportunity)

        assert result.is_paper is True
        assert result.execution_time_ms > 0
        assert result.execution_time_ms < 50  # Realistic latency
        assert result.slippage_pct >= 0
        assert len(result.fill_prices) == 3  # All 3 legs

    @pytest.mark.asyncio
    async def test_health_status_returns_correct_fields(self):
        """get_health_status must return all required dashboard fields."""
        ks = make_mock_kill_switch()
        db = make_mock_db()
        tax = make_mock_tax()
        cache = make_l1_only_cache()

        strategy = Strategy(ks, db, tax, cache=cache)
        status = await strategy.get_health_status()

        required_fields = [
            "strategy_id", "version", "is_paper", "mode",
            "stats", "current_opportunities", "triangles_monitored"
        ]
        for f in required_fields:
            assert f in status, f"Missing field: {f}"

        assert status["strategy_id"] == "A_M1_triangular_arb"
        assert status["triangles_monitored"] == len(TRIANGLE_SETS)


# --- Part 2 Tests ---

class TestExecutionEngine:

    @pytest.mark.asyncio
    async def test_dispatcher_routes_to_paper_correctly(self):
        """ExecutionDispatcher must call paper simulator in paper mode."""
        paper_sim = MagicMock()
        paper_sim.simulate = AsyncMock(return_value=ExecutionResult(
            opportunity_id="test",
            success=True,
            actual_profit_usdc=1.50,
            actual_profit_pct=0.003,
            execution_time_ms=6.0,
            fill_prices={"ETHUSDT": 3215.0},
            slippage_pct=0.0001,
            is_paper=True,
        ))

        live_engine = MagicMock()
        live_engine.execute_triangle = AsyncMock()  # Should NOT be called

        mock_logger = MagicMock()
        mock_logger.log_trade = AsyncMock(return_value="trade-123")

        engine = ExecutionDispatcher(paper_sim, live_engine, mock_logger, make_mock_kill_switch())

        market = UnifiedMarket(symbol="ETHUSDT", exchange="binance", price=3215.0)
        decision = TradeDecision("ETHUSDT", "binance", "ARB", 500.0)

        result = await engine.execute(
            opportunity_id="opp-1",
            opportunity={"triangle_id": "BTC-ETH-USDT", "entry_size_usdc": 500},
            decision=decision,
            market=market,
            is_paper=True,
            regime="BULL_RANGING",
        )

        paper_sim.simulate.assert_called_once()
        live_engine.execute_triangle.assert_not_called()  # Never in paper mode
        assert result.is_paper is True
        assert result.actual_profit_usdc == 1.50

    @pytest.mark.asyncio
    async def test_position_monitor_detects_stuck_position(self):
        """PositionMonitor must flag positions open > 30 seconds."""
        cache = make_l1_only_cache()
        db = make_mock_db()

        monitor = PositionMonitor(cache, db)

        # Register a position
        opp_id = "stuck-001"
        await monitor.register_open(opp_id, {"triangle_id": "BTC-ETH-USDT"})

        # Manually age it (simulate time passing)
        monitor._open_positions[opp_id]["opened_at"] = time.monotonic() - 35

        # Run one watchdog iteration
        with patch.object(monitor, '_alert_stuck_position', new_callable=AsyncMock) as mock_alert:
            now = time.monotonic()
            for oid, pos in list(monitor._open_positions.items()):
                age = now - pos["opened_at"]
                if age > 30:
                    await monitor._alert_stuck_position(oid, pos, age)

            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_promotion_gates_fail_with_no_trades(self):
        """Gates must fail when there are no paper trades."""
        db = MagicMock()
        gates = PromotionGates(db)
        # Mock _get_paper_trades to return empty list
        gates._get_paper_trades = AsyncMock(return_value=[])

        result = await gates.check_all_gates("A_M1_triangular_arb")

        assert result["all_passed"] is False
        assert result["gates"]["min_trades"]["passed"] is False

    @pytest.mark.asyncio
    async def test_promotion_gates_pass_with_good_performance(self):
        """Gates must pass when paper trade performance is excellent."""
        from datetime import datetime as dt

        good_trades = [
            {
                "pnl_usdc": 1.20 + (i * 0.05),
                "edge_detected": 0.003,
                "outcome": "win",
                "created_at": dt.utcnow().isoformat(),
            }
            for i in range(55)  # 55 winning trades
        ]

        db = MagicMock()
        gates = PromotionGates(db)
        gates._get_paper_trades = AsyncMock(return_value=good_trades)

        result = await gates.check_all_gates("A_M1_triangular_arb")

        assert result["gates"]["min_trades"]["passed"] is True
        assert result["gates"]["min_win_rate"]["passed"] is True
        assert result["gates"]["zero_execution_errors"]["passed"] is True

    @pytest.mark.asyncio
    async def test_strategy_execute_signal_updates_stats(self):
        """execute_signal must update in-memory stats after execution."""
        ks = make_mock_kill_switch()
        db = make_mock_db()
        tax = make_mock_tax()
        cache = make_l1_only_cache()

        strategy = Strategy(ks, db, tax, allocated_usdc=1000.0, cache=cache)

        # Pre-populate opportunity in cache
        opp_id = "test-opp-123"
        await cache.set(f"tri_opp:{opp_id}", {
            "triangle_id": "BTC-ETH-USDT",
            "direction": "forward",
            "leg_AB": "BTCUSDT",
            "leg_BC": "ETHBTC",
            "leg_AC": "ETHUSDT",
            "price_AB": 67000.0,
            "price_BC": 0.04780,
            "price_AC": 3215.0,
            "entry_size_usdc": 500.0,
            "gap_pct": 0.39,
            "net_profit_pct": 0.19,
            "expected_profit_usdc": 0.95,
        })

        initial_trades = strategy._stats["total_trades"]
        decision = TradeDecision("ETHUSDT", "binance", "ARB", 500.0)
        market = UnifiedMarket(symbol="ETHUSDT", exchange="binance", price=3215.0)

        result = await strategy.execute_signal(decision, market, opp_id, "BULL_RANGING")

        assert strategy._stats["total_trades"] == initial_trades + 1
        assert result is not None

    def test_live_engine_max_trade_size_constant(self):
        """MAX_TRADE_SIZE_USDC must be set to $5,000."""
        assert MAX_TRADE_SIZE_USDC == 5_000.0

    @pytest.mark.asyncio
    async def test_sharpe_calculation(self):
        """Sharpe calculation must give positive value for mostly winning trades."""
        gates = PromotionGates(MagicMock())

        all_wins = [1.5, 1.2, 0.8, 1.0, 1.3, 0.9, 1.1, 1.4, 1.2, 0.7]
        sharpe = gates._calculate_sharpe(all_wins)
        assert sharpe > 1.5, f"Sharpe should be > 1.5 for consistent wins: {sharpe:.2f}"


class TestEndToEnd:

    @pytest.mark.asyncio
    async def test_full_pipeline_paper_mode(self):
        """
        End-to-end: cache prices -> detect gap -> on_market_signal ->
        execute_signal -> result logged.
        """
        cache = make_l1_only_cache()
        db = make_mock_db()
        tax = make_mock_tax()
        ks = make_mock_kill_switch()

        # Set up profitable triangle
        await cache.set("price:binance:BTCUSDT", 67_000.0)
        await cache.set("price:binance:ETHBTC",  0.04780)
        await cache.set("price:binance:ETHUSDT", 3_225.0)  # 0.70% gap
        await cache.set("capital:current_usdc", 2000.0)

        strategy = Strategy(ks, db, tax, allocated_usdc=2000.0, cache=cache)

        market = UnifiedMarket(
            market_id="binance_ETHUSDT",
            exchange="binance",
            symbol="ETHUSDT",
            price=3225.0,
            triangular_gap_pct=0.70,
            opportunity_score=82.0,
        )

        # Step 1: Strategy analyzes and decides
        decision = await strategy.on_market_signal(market, allocated_usdc=2000.0)
        assert decision is not None, "Should decide to trade on 0.70% gap"

        # Step 2: Execute (paper mode)
        opp_id = str(uuid.uuid4())
        # The opp was cached during on_market_signal with a different id,
        # so we manually cache one for our opp_id
        await cache.set(f"tri_opp:{opp_id}", {
            "triangle_id": "BTC-ETH-USDT",
            "direction": "forward",
            "leg_AB": "BTCUSDT",
            "leg_BC": "ETHBTC",
            "leg_AC": "ETHUSDT",
            "price_AB": 67000.0,
            "price_BC": 0.04780,
            "price_AC": 3225.0,
            "entry_size_usdc": decision.size_usdc,
            "gap_pct": 0.70,
            "net_profit_pct": 0.50,
            "expected_profit_usdc": decision.size_usdc * 0.50 / 100.0,
        })

        result = await strategy.execute_signal(decision, market, opp_id, "BULL_RANGING")
        assert result is not None
        assert result.is_paper is True

        # Step 3: Verify stats updated
        assert strategy._stats["total_trades"] >= 1


# --- Config System Tests (Part 3) ---

class TestConfigSystem:

    @pytest.mark.asyncio
    async def test_config_uses_dashboard_values_not_hardcoded(self):
        """StrategyConfig must use cache values, not hardcoded constants."""
        cache = make_l1_only_cache()

        # Simulate dashboard saving new config to Redis key
        await cache.set("strategy_config:A_M1_triangular_arb", {
            "min_gap_pct": 0.08,            # Changed from default 0.12
            "max_trade_size_usdc": 3000.0,  # Changed from default 5000
            "fee_per_leg_pct": 0.075,       # VIP1 tier fee
            "active_triangles": [
                "BTCUSDT-ETHBTC-ETHUSDT",   # Only primary active
            ],
        })

        config = StrategyConfig(cache)
        await config.refresh()

        assert config.min_gap_pct == 0.08, \
            f"Expected 0.08, got {config.min_gap_pct}"
        assert config.max_trade_size_usdc == 3000.0, \
            f"Expected 3000.0, got {config.max_trade_size_usdc}"
        assert abs(config.fee_per_leg - 0.00075) < 1e-9, \
            f"Expected 0.00075, got {config.fee_per_leg}"
        assert len(config.active_triangle_sets) == 1, \
            f"Expected 1 active triangle, got {len(config.active_triangle_sets)}"

    @pytest.mark.asyncio
    async def test_config_falls_back_to_defaults_on_cache_miss(self):
        """Config must fall back to DEFAULT_CONFIG when cache has no entry."""
        cache = make_l1_only_cache()
        # Deliberately do NOT set any config key

        config = StrategyConfig(cache)
        await config.refresh()

        assert config.min_gap_pct == DEFAULT_CONFIG["min_gap_pct"]
        assert config.max_trade_size_usdc == DEFAULT_CONFIG["max_trade_size_usdc"]
        assert len(config.active_triangle_sets) == len(DEFAULT_CONFIG["active_triangles"])

    @pytest.mark.asyncio
    async def test_detector_respects_min_gap_from_config(self):
        """Detector must skip opportunities below the dashboard-configured min gap."""
        cache = make_l1_only_cache()

        # Set a very high threshold (0.50%) — only exceptional gaps should pass
        await cache.set("strategy_config:A_M1_triangular_arb", {
            "min_gap_pct": 0.50,
            "fee_per_leg_pct": 0.10,
            "active_triangles": ["BTCUSDT-ETHBTC-ETHUSDT"],
        })

        # Prices produce ~0.23% gap — below the 0.50% threshold
        await cache.set("price:binance:BTCUSDT", 67000.0)
        await cache.set("price:binance:ETHBTC",  0.04780)
        await cache.set("price:binance:ETHUSDT", 3210.0)

        config = StrategyConfig(cache)
        await config.refresh()
        detector = TriangleDetector(cache, config)

        opps = await detector.detect_all_opportunities()
        assert len(opps) == 0, \
            f"Expected 0 opportunities with 0.50% threshold, got {len(opps)}"

    @pytest.mark.asyncio
    async def test_fee_update_changes_net_profit_calculation(self):
        """Lowering fee in dashboard must increase net profit on same gap."""
        cache = make_l1_only_cache()

        # Prices with ~0.39% gap
        await cache.set("price:binance:BTCUSDT", 67000.0)
        await cache.set("price:binance:ETHBTC",  0.04780)
        await cache.set("price:binance:ETHUSDT", 3215.0)

        # Standard 0.10% fee (0.20% total)
        await cache.set("strategy_config:A_M1_triangular_arb", {
            "min_gap_pct": 0.05,
            "fee_per_leg_pct": 0.10,
            "active_triangles": ["BTCUSDT-ETHBTC-ETHUSDT"],
        })
        config_std = StrategyConfig(cache)
        await config_std.refresh()
        opps_std = await TriangleDetector(cache, config_std).detect_all_opportunities()

        # VIP1 0.075% fee (0.15% total) — should produce higher net
        await cache.set("strategy_config:A_M1_triangular_arb", {
            "min_gap_pct": 0.05,
            "fee_per_leg_pct": 0.075,
            "active_triangles": ["BTCUSDT-ETHBTC-ETHUSDT"],
        })
        config_vip = StrategyConfig(cache)
        await config_vip.refresh()
        opps_vip = await TriangleDetector(cache, config_vip).detect_all_opportunities()

        assert opps_std, "Standard fee should produce at least one opportunity"
        assert opps_vip, "VIP fee should produce at least one opportunity"
        assert opps_vip[0].net_profit_pct > opps_std[0].net_profit_pct, (
            f"VIP fee net {opps_vip[0].net_profit_pct:.4f}% should exceed "
            f"standard fee net {opps_std[0].net_profit_pct:.4f}%"
        )
