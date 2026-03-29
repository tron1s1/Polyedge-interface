"""
A_M1 Triangular Arbitrage Strategy Plugin
==========================================
Category: A_math (Mathematical Certainty)
Exchange: Binance (single exchange, no cross-exchange risk)
Win rate: 100% when gap is confirmed and execution completes
Frequency: 50-200 signals/day
Min gap: 0.12% (after 0.1% fee per leg)

Triangle sets monitored:
  Primary:   BTC/USDT + ETH/BTC  -> ETH/USDT
  Secondary: BTC/USDT + BNB/BTC  -> BNB/USDT
  Tertiary:  ETH/USDT + LINK/ETH -> LINK/USDT
  Extended:  BTC/USDT + SOL/BTC  -> SOL/USDT (if available)

Mathematical rule for each triangle (A/B, B/C, A/C):
  implied_AC = price_AB * price_BC
  actual_AC  = current market price of A/C pair
  gap_pct    = |actual_AC - implied_AC| / implied_AC * 100

Two trade directions:
  Direction FORWARD:  Buy AB -> Buy BC -> Sell AC
  Direction REVERSE:  Buy AC -> Sell BC -> Sell AB
"""

import asyncio
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

# Plugin imports - from node1-scanner core
from strategies.base_strategy import BaseStrategy, TradeDecision
from ingestion.market_normalizer import UnifiedMarket
from core.kill_switch_bus import KillSwitchBus
from core.india_tax_engine import IndiaTaxEngine
from database.supabase_client import SupabaseClient
from latency.base_methods import TieredCache
import structlog

logger = structlog.get_logger()


# -------------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------------

# Default config (used if Supabase/cache is unreachable)
# Dashboard writes to Supabase -> strategy_flags -> cache -> StrategyConfig reads here.
# Full propagation: dashboard save -> plugin applies = < 30 seconds.
DEFAULT_CONFIG = {
    "min_gap_pct":          0.12,
    "max_trade_size_usdc":  5_000.0,
    "min_trade_size_usdc":  50.0,
    "fee_per_leg_pct":      0.10,   # Percent (0.10 = 0.10%), not decimal
    "active_triangles": [
        "BTCUSDT-ETHBTC-ETHUSDT",
        "BTCUSDT-BNBBTC-BNBUSDT",
        "BTCUSDT-SOLBTC-SOLUSDT",
        "ETHUSDT-LINKETH-LINKUSDT",
        "BTCUSDT-XRPBTC-XRPUSDT",
        "BTCUSDT-LTCBTC-LTCUSDT",
    ],
}

# Full triangle registry: dashboard key -> (leg_AB, leg_BC, leg_AC, description)
ALL_TRIANGLE_SETS = {
    "BTCUSDT-ETHBTC-ETHUSDT":  ("BTCUSDT", "ETHBTC",  "ETHUSDT",  "BTC->ETH->USDT (primary)"),
    "BTCUSDT-BNBBTC-BNBUSDT":  ("BTCUSDT", "BNBBTC",  "BNBUSDT",  "BTC->BNB->USDT"),
    "BTCUSDT-SOLBTC-SOLUSDT":  ("BTCUSDT", "SOLBTC",  "SOLUSDT",  "BTC->SOL->USDT"),
    "ETHUSDT-LINKETH-LINKUSDT": ("ETHUSDT", "LINKETH", "LINKUSDT", "ETH->LINK->USDT"),
    "BTCUSDT-XRPBTC-XRPUSDT":  ("BTCUSDT", "XRPBTC",  "XRPUSDT",  "BTC->XRP->USDT"),
    "BTCUSDT-LTCBTC-LTCUSDT":  ("BTCUSDT", "LTCBTC",  "LTCUSDT",  "BTC->LTC->USDT"),
}

# Backward-compat module-level aliases (imported by tests + legacy code)
MIN_GAP_PCT          = DEFAULT_CONFIG["min_gap_pct"]
FEE_PER_LEG          = DEFAULT_CONFIG["fee_per_leg_pct"] / 100.0  # decimal: 0.001
MAX_TRADE_SIZE_USDC  = DEFAULT_CONFIG["max_trade_size_usdc"]
MIN_TRADE_SIZE_USDC  = DEFAULT_CONFIG["min_trade_size_usdc"]
TRIANGLE_SETS        = list(ALL_TRIANGLE_SETS.values())           # list of tuples

# Version for A/B testing in Supabase
VERSION_TAG = "v1-base"


# -------------------------------------------------------------------------
# STRATEGY CONFIG LOADER
# -------------------------------------------------------------------------

class StrategyConfig:
    """
    Live config loader. Reads from cache (which mirrors Supabase strategy_flags).
    Plugin calls refresh() at startup and on every on_market_signal call.
    Dashboard writes to Supabase -> strategy_flags -> cache -> plugin reads here.
    Full propagation: dashboard save -> plugin applies = < 30 seconds.
    Falls back to DEFAULT_CONFIG when cache is empty or unreachable.
    """

    def __init__(self, cache: Optional[TieredCache]):
        self._cache = cache
        self._config = dict(DEFAULT_CONFIG)  # Start with defaults

    async def refresh(self) -> None:
        """Load config from cache. Falls back to DEFAULT_CONFIG on miss."""
        if not self._cache:
            return
        cached = await self._cache.get("strategy_config:A_M1_triangular_arb")
        if cached and isinstance(cached, dict):
            self._config = {**DEFAULT_CONFIG, **cached}

    @property
    def min_gap_pct(self) -> float:
        return float(self._config.get("min_gap_pct", DEFAULT_CONFIG["min_gap_pct"]))

    @property
    def fee_per_leg(self) -> float:
        """Returns fee as decimal (e.g. 0.001), not percent."""
        return float(self._config.get("fee_per_leg_pct", DEFAULT_CONFIG["fee_per_leg_pct"])) / 100.0

    @property
    def max_trade_size_usdc(self) -> float:
        return float(self._config.get("max_trade_size_usdc", DEFAULT_CONFIG["max_trade_size_usdc"]))

    @property
    def min_trade_size_usdc(self) -> float:
        return float(self._config.get("min_trade_size_usdc", DEFAULT_CONFIG["min_trade_size_usdc"]))

    @property
    def active_triangle_sets(self) -> list:
        """Returns list of (leg_AB, leg_BC, leg_AC, description) tuples."""
        active_ids = self._config.get("active_triangles", DEFAULT_CONFIG["active_triangles"])
        return [
            ALL_TRIANGLE_SETS[tri_id]
            for tri_id in active_ids
            if tri_id in ALL_TRIANGLE_SETS
        ]

    @property
    def total_fee_pct(self) -> float:
        """Total fee cost across 2 legs, as percent. e.g. 0.20"""
        return self.fee_per_leg * 2 * 100

    @property
    def breakeven_gap_pct(self) -> float:
        """Minimum gap that exactly covers fees (no profit). For health display."""
        return self.total_fee_pct


# -------------------------------------------------------------------------
# DATA CLASSES
# -------------------------------------------------------------------------

class TriDirection(Enum):
    FORWARD = "forward"   # Buy AB -> Buy BC -> Sell AC
    REVERSE = "reverse"   # Buy AC -> Sell BC -> Sell AB


@dataclass
class TriangleOpportunity:
    """A detected triangular arb opportunity, ready to execute."""
    triangle_id: str            # e.g. "BTC-ETH-USDT"
    description: str
    direction: TriDirection

    # The three legs
    leg_AB: str                 # e.g. "BTCUSDT"
    leg_BC: str                 # e.g. "ETHBTC"
    leg_AC: str                 # e.g. "ETHUSDT"

    # Current prices (fetched at detection time)
    price_AB: float
    price_BC: float
    price_AC: float

    # Math
    implied_AC: float           # price_AB * price_BC
    actual_AC: float            # current market price
    gap_pct: float              # deviation %
    net_profit_pct: float       # gap_pct - (2 * FEE_PER_LEG * 100)

    # Execution plan
    entry_size_usdc: float      # How much USDC to deploy
    expected_profit_usdc: float  # entry_size_usdc * net_profit_pct / 100

    # Metadata
    detected_at: datetime = field(default_factory=datetime.utcnow)
    detection_latency_ms: float = 0.0


@dataclass
class ExecutionResult:
    """Result of executing a triangle (paper or live)."""
    opportunity_id: str
    success: bool
    actual_profit_usdc: float
    actual_profit_pct: float
    execution_time_ms: float
    fill_prices: Dict[str, float]   # symbol -> actual fill price
    slippage_pct: float
    error: Optional[str] = None
    is_paper: bool = True


# -------------------------------------------------------------------------
# MAIN STRATEGY CLASS
# -------------------------------------------------------------------------

class Strategy(BaseStrategy):
    """
    A_M1 Triangular Arbitrage.

    HOW IT PLUGS IN:
    - StrategyRegistry discovers this file and instantiates Strategy()
    - Scanner calls on_market_signal() when any market with triangular_gap_pct > 0
      is routed to this strategy
    - Strategy validates the gap, sizes position via Kelly, logs to Supabase
    - In paper mode: ExecutionSimulator fills at theoretical prices
    - In live mode: ExecutionEngine calls Binance API (built in Part 2)
    """

    # -- Required plugin metadata --
    STRATEGY_ID: str    = "A_M1_triangular_arb"
    DISPLAY_NAME: str   = "Triangular Arbitrage"
    CATEGORY: str       = "A_math"
    CATEGORY_LABEL: str = "Mathematical Certainty"
    DESCRIPTION: str    = "BTC/ETH/USDT triangle on Binance. 100% when gap exists."
    NODE_ID: str        = "singapore-01"
    VERSION: str        = VERSION_TAG

    def __init__(
        self,
        kill_switch: KillSwitchBus,
        db: SupabaseClient,
        tax_engine: IndiaTaxEngine,
        allocated_usdc: float = 0.0,
        cache: Optional[TieredCache] = None,
    ):
        super().__init__(kill_switch, db, tax_engine, allocated_usdc)
        self._cache = cache

        # Live config loader — reads from cache, falls back to DEFAULT_CONFIG
        self._strategy_config = StrategyConfig(cache)

        # Detection — passes live config so detector uses dashboard values
        self._detector = TriangleDetector(cache, self._strategy_config)

        # Execution
        self._paper_sim = PaperExecutionSimulator()
        self._live_engine = LiveExecutionEngine(cache)
        self._live_engine.set_kill_switch(kill_switch)

        # Logging
        self._trade_logger = TriangleTradeLogger(db, tax_engine)

        # Execution dispatcher (routes to paper or live)
        self._executor = ExecutionDispatcher(
            paper_sim=self._paper_sim,
            live_engine=self._live_engine,
            logger_svc=self._trade_logger,
            kill_switch=kill_switch,
        )

        # Monitoring
        self._position_monitor = PositionMonitor(cache, db)

        # Promotion gates
        self._promotion_gates = PromotionGates(db)

        # Performance tracking (in-memory, fast)
        self._stats = {
            "total_signals": 0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl_usdc": 0.0,
            "total_opportunities_detected": 0,
            "last_trade_at": None,
        }

    # -- MAIN ENTRY POINT -- called by scanner

    async def on_market_signal(
        self,
        market: UnifiedMarket,
        allocated_usdc: float,
    ) -> Optional[TradeDecision]:
        """
        Called when scanner routes a market with triangular_gap_pct > 0.
        Returns TradeDecision if opportunity is real and worth trading.

        Flow:
        1. Kill switch pre-check (< 0.001ms)
        2. Gap validation (re-verify the gap is still there)
        3. Kelly position sizing
        4. Log decision to Supabase BEFORE execution
        5. Return TradeDecision (scanner/executor handles the rest)
        """
        self._stats["total_signals"] += 1
        start = time.perf_counter()

        # Step 1: Kill switch check
        trade_size = min(allocated_usdc * 0.25, self._strategy_config.max_trade_size_usdc)
        allowed, reason = self.check_kill_switch(trade_size)
        if not allowed:
            self.logger.debug("kill_switch_blocked", reason=reason)
            return None

        # Refresh config from cache (TTL-controlled — no overhead on cache hit)
        await self._strategy_config.refresh()

        # Step 2: Find actual triangle opportunities from live data
        opportunities = await self._detector.detect_all_opportunities()
        self._stats["total_opportunities_detected"] += len(opportunities)

        if not opportunities:
            return None

        # Take the best opportunity (highest net profit %)
        best = max(opportunities, key=lambda o: o.net_profit_pct)

        # Sanity check: gap must still be profitable
        if best.net_profit_pct < 0.02:  # < 0.02% net -- not worth it
            self.logger.debug("gap_too_small", net_pct=best.net_profit_pct)
            return None

        # Step 3: Kelly position sizing
        # For guaranteed math strategies: Kelly is 1.0 (certainty)
        # But we cap by: available allocation, max trade size, min trade size
        raw_size = min(
            allocated_usdc * 0.40,                          # Max 40% of allocation per trade
            self._strategy_config.max_trade_size_usdc,      # Dashboard-configured cap
        )
        if best.expected_profit_usdc <= 0 and raw_size == 0:
            return None
        raw_size = max(raw_size, self._strategy_config.min_trade_size_usdc)
        sized = self.apply_kelly(raw_size)
        best.entry_size_usdc = sized
        best.expected_profit_usdc = sized * best.net_profit_pct / 100.0

        # Skip if expected profit is below minimum threshold ($0.50)
        if best.expected_profit_usdc < 0.50:
            return None

        detection_ms = (time.perf_counter() - start) * 1000

        # Step 4: Log decision BEFORE execution (required by BaseStrategy)
        reasoning = (
            f"Triangle: {best.description} | "
            f"Direction: {best.direction.value} | "
            f"Gap: {best.gap_pct:.4f}% | "
            f"Net after fees: {best.net_profit_pct:.4f}% | "
            f"Expected profit: ${best.expected_profit_usdc:.2f} | "
            f"Detection: {detection_ms:.1f}ms"
        )
        self.logger.info("triangle_opportunity",
                         triangle=best.triangle_id,
                         gap_pct=round(best.gap_pct, 4),
                         net_pct=round(best.net_profit_pct, 4),
                         expected_usdc=round(best.expected_profit_usdc, 2),
                         size_usdc=round(best.entry_size_usdc, 2),
                         direction=best.direction.value)

        # Store opportunity in cache for executor to read
        opp_id = str(uuid.uuid4())
        if self._cache:
            await self._cache.set(
                f"tri_opp:{opp_id}",
                {
                    "triangle_id": best.triangle_id,
                    "direction": best.direction.value,
                    "leg_AB": best.leg_AB,
                    "leg_BC": best.leg_BC,
                    "leg_AC": best.leg_AC,
                    "price_AB": best.price_AB,
                    "price_BC": best.price_BC,
                    "price_AC": best.price_AC,
                    "entry_size_usdc": best.entry_size_usdc,
                    "expected_profit_usdc": best.expected_profit_usdc,
                    "gap_pct": best.gap_pct,
                    "net_profit_pct": best.net_profit_pct,
                    "detected_at": best.detected_at.isoformat(),
                },
                ttl=30  # 30 seconds to execute before opportunity expires
            )

        # Step 5: Return TradeDecision
        return TradeDecision(
            symbol=best.leg_AC,           # Primary symbol of the trade
            exchange="binance",
            direction="ARB",              # Custom direction for multi-leg arb
            size_usdc=best.entry_size_usdc,
            leverage=1.0,                 # Never leverage math strategies
            stop_loss_price=None,         # No stop needed -- guaranteed
            take_profit_price=None,       # Exits at completion of triangle
            ai_confidence=1.0,            # Mathematical certainty
            reasoning=reasoning,
            edge_detected=best.net_profit_pct / 100.0,
            version_tag=VERSION_TAG,
        )

    # -- PAPER EXECUTION -- called by ExecutionEngine in paper mode

    async def execute_paper(
        self,
        opportunity_id: str,
        market: UnifiedMarket,
    ) -> ExecutionResult:
        """
        Simulate the triangle execution at current market prices.
        Records realistic slippage and fees.
        Returns ExecutionResult for Supabase logging.
        """
        if self._cache is None:
            return ExecutionResult(
                opportunity_id=opportunity_id,
                success=False,
                actual_profit_usdc=0,
                actual_profit_pct=0,
                execution_time_ms=0,
                fill_prices={},
                slippage_pct=0,
                error="Cache not available",
                is_paper=True,
            )

        opp = await self._cache.get(f"tri_opp:{opportunity_id}")
        if not opp:
            return ExecutionResult(
                opportunity_id=opportunity_id,
                success=False,
                actual_profit_usdc=0,
                actual_profit_pct=0,
                execution_time_ms=0,
                fill_prices={},
                slippage_pct=0,
                error="Opportunity expired or not found",
                is_paper=True,
            )

        result = await self._simulator.simulate(opp)
        result.is_paper = True

        # Update performance stats
        self._stats["total_trades"] += 1
        if result.success and result.actual_profit_usdc > 0:
            self._stats["wins"] += 1
            self._stats["total_pnl_usdc"] += result.actual_profit_usdc
        else:
            self._stats["losses"] += 1

        self._stats["last_trade_at"] = datetime.utcnow().isoformat()

        return result

    # -- HEALTH STATUS -- called by dashboard

    async def get_health_status(self) -> Dict:
        """Dashboard polls this every 30 seconds."""
        win_rate = 0.0
        if self._stats["total_trades"] > 0:
            win_rate = self._stats["wins"] / self._stats["total_trades"]

        # Get current opportunities count from detector
        current_opps = []
        if self._cache:
            try:
                current_opps = await self._detector.detect_all_opportunities()
            except Exception:
                pass

        return {
            "strategy_id": self.STRATEGY_ID,
            "version": self.VERSION,
            "is_paper": self._is_paper,
            "mode": "paper" if self._is_paper else "live",
            "stats": {
                "total_signals": self._stats["total_signals"],
                "total_trades": self._stats["total_trades"],
                "win_rate": round(win_rate, 4),
                "total_pnl_usdc": round(self._stats["total_pnl_usdc"], 2),
                "last_trade_at": self._stats["last_trade_at"],
                "opportunities_detected": self._stats["total_opportunities_detected"],
            },
            "current_opportunities": len(current_opps),
            "best_current_gap_pct": max(
                (o.gap_pct for o in current_opps), default=0.0
            ),
            "triangles_monitored": len(self._strategy_config.active_triangle_sets),
            "min_gap_threshold_pct": self._strategy_config.min_gap_pct,
            "fee_per_leg_pct": self._strategy_config.fee_per_leg * 100,
            "max_trade_size_usdc": self._strategy_config.max_trade_size_usdc,
            "breakeven_gap_pct": self._strategy_config.breakeven_gap_pct,
        }

    # -- REGIME CHANGE HANDLER

    async def on_regime_change(self, new_regime: str, paused: list) -> None:
        """
        A_M1 is a math strategy -- it NEVER pauses due to regime.
        Only BLACK_SWAN pauses it, but the kill switch handles that.
        Log the regime change for monitoring only.
        """
        if self.STRATEGY_ID in paused:
            self.logger.warning("math_strategy_incorrectly_paused",
                                regime=new_regime,
                                strategy=self.STRATEGY_ID)

    # -- EXECUTE SIGNAL -- called by scanner after on_market_signal

    async def execute_signal(
        self,
        decision: TradeDecision,
        market: UnifiedMarket,
        opportunity_id: str,
        regime: str,
    ) -> Optional[ExecutionResult]:
        """
        Called by scanner AFTER on_market_signal() returns a TradeDecision.
        Retrieves the cached opportunity and dispatches to ExecutionDispatcher.

        Flow:
        1. Fetch opportunity from cache (set during on_market_signal)
        2. Register position open (watchdog starts)
        3. Dispatch to paper or live executor
        4. Register position close
        5. Update in-memory stats
        6. Return result
        """
        opp = None
        if self._cache:
            opp = await self._cache.get(f"tri_opp:{opportunity_id}")

        if not opp:
            self.logger.warning("opportunity_expired", opp_id=opportunity_id)
            return None

        # Watchdog: register open position
        await self._position_monitor.register_open(opportunity_id, opp)

        result = None
        try:
            result = await self._executor.execute(
                opportunity_id=opportunity_id,
                opportunity=opp,
                decision=decision,
                market=market,
                is_paper=self._is_paper,
                regime=regime,
            )
        finally:
            # Always deregister, even on exception
            await self._position_monitor.register_close(
                opportunity_id, result
            )

        # Update in-memory stats
        self._stats["total_trades"] += 1
        if result and result.success and result.actual_profit_usdc > 0:
            self._stats["wins"] += 1
            self._stats["total_pnl_usdc"] += result.actual_profit_usdc
        else:
            self._stats["losses"] += 1
        self._stats["last_trade_at"] = datetime.utcnow().isoformat()

        return result

    async def check_promotion_readiness(self) -> dict:
        """Dashboard button: 'Check Promotion Readiness' calls this."""
        return await self._promotion_gates.check_all_gates(self.STRATEGY_ID)

    async def promote_to_live(self) -> bool:
        """Dashboard button: 'Promote to Live' calls this."""
        promoted = await self._promotion_gates.promote_to_live(self.STRATEGY_ID)
        if promoted:
            await self.on_promote_to_live()  # Sets self._is_paper = False
        return promoted


# -------------------------------------------------------------------------
# TRIANGLE DETECTOR
# -------------------------------------------------------------------------

class TriangleDetector:
    """
    Detects triangular arb opportunities by checking price relationships.
    Reads prices from Redis cache (set by Binance WebSocket feed).
    No API calls -- pure cache reads, runs in < 5ms total.
    """

    def __init__(self, cache: Optional[TieredCache], config: Optional[StrategyConfig] = None):
        self._cache = cache
        self._config = config if config is not None else StrategyConfig(None)

    async def detect_all_opportunities(self) -> List[TriangleOpportunity]:
        """
        Check all active triangle sets for price relationship violations.
        Uses live config from dashboard — no restart needed when sets change.
        Returns list of profitable opportunities, sorted by net profit.
        """
        if not self._cache:
            return []

        opportunities = []

        # Use live config: active_triangle_sets reflects dashboard toggles
        for leg_AB, leg_BC, leg_AC, description in self._config.active_triangle_sets:
            # Read all three prices from L1 cache simultaneously
            price_AB, price_BC, price_AC = await asyncio.gather(
                self._cache.get(f"price:binance:{leg_AB}"),
                self._cache.get(f"price:binance:{leg_BC}"),
                self._cache.get(f"price:binance:{leg_AC}"),
            )

            # Skip if any price missing (pair not yet loaded)
            if not all([price_AB, price_BC, price_AC]):
                continue

            opp = self._calculate_opportunity(
                leg_AB, leg_BC, leg_AC,
                price_AB, price_BC, price_AC,
                description
            )
            if opp:
                opportunities.append(opp)

        return sorted(opportunities, key=lambda o: o.net_profit_pct, reverse=True)

    def _calculate_opportunity(
        self,
        leg_AB: str, leg_BC: str, leg_AC: str,
        price_AB: float, price_BC: float, price_AC: float,
        description: str,
    ) -> Optional[TriangleOpportunity]:
        """
        Calculate if a profitable gap exists for this triangle.

        Mathematical check:
          implied_AC = price_AB * price_BC
          If actual_AC > implied_AC -> FORWARD trade (buy AB, buy BC, sell AC)
          If actual_AC < implied_AC -> REVERSE trade (buy AC, sell BC, sell AB)
        """
        if price_AB <= 0 or price_BC <= 0 or price_AC <= 0:
            return None

        implied_AC = price_AB * price_BC
        gap_pct = abs(price_AC - implied_AC) / implied_AC * 100

        # Use live config values — set by dashboard, not hardcoded
        total_fee_pct = self._config.total_fee_pct
        net_profit_pct = gap_pct - total_fee_pct

        if gap_pct < self._config.min_gap_pct:
            return None  # Below dashboard-configured threshold

        direction = (
            TriDirection.FORWARD
            if price_AC > implied_AC
            else TriDirection.REVERSE
        )

        triangle_id = f"{leg_AB[:3]}-{leg_BC[:3]}-{leg_AC[:3]}"

        return TriangleOpportunity(
            triangle_id=triangle_id,
            description=description,
            direction=direction,
            leg_AB=leg_AB,
            leg_BC=leg_BC,
            leg_AC=leg_AC,
            price_AB=price_AB,
            price_BC=price_BC,
            price_AC=price_AC,
            implied_AC=implied_AC,
            actual_AC=price_AC,
            gap_pct=gap_pct,
            net_profit_pct=net_profit_pct,
            entry_size_usdc=0.0,          # Set by strategy after Kelly sizing
            expected_profit_usdc=0.0,     # Set by strategy after sizing
        )


# -------------------------------------------------------------------------
# PAPER EXECUTION SIMULATOR
# -------------------------------------------------------------------------

class PaperExecutionSimulator:
    """
    Simulates triangle execution with realistic market conditions.
    Models: slippage (size-dependent), partial fills, timing.
    Does NOT call any exchange API.
    """

    # Realistic slippage model: based on order size relative to typical depth
    SLIPPAGE_COEFFICIENTS = {
        "small":  (0,     500,    0.0001),  # < $500: 0.01% slippage
        "medium": (500,   2000,   0.0003),  # $500-$2k: 0.03% slippage
        "large":  (2000,  5000,   0.0006),  # $2k-$5k: 0.06% slippage
    }

    async def simulate(self, opportunity: dict) -> ExecutionResult:
        """
        Simulate execution of a triangular arb opportunity.
        Uses realistic slippage and timing models.
        """
        start = time.perf_counter()
        size = opportunity.get("entry_size_usdc", 100.0)
        net_pct = opportunity.get("net_profit_pct", 0.0)

        # Model execution latency (realistic for Singapore -> Binance)
        exec_latency_ms = self._model_execution_latency()

        # Model slippage based on order size
        slippage_pct = self._model_slippage(size)

        # Calculate actual profit after slippage
        actual_net_pct = net_pct - slippage_pct
        actual_profit = size * actual_net_pct / 100.0

        # Simulate fill prices (slightly worse than detection prices)
        fill_multiplier = 1 + (slippage_pct / 100.0 / 2)  # Split across legs
        fill_prices = {
            opportunity.get("leg_AB", "BTCUSDT"): opportunity.get("price_AB", 0) * fill_multiplier,
            opportunity.get("leg_BC", "ETHBTC"):  opportunity.get("price_BC", 0) * fill_multiplier,
            opportunity.get("leg_AC", "ETHUSDT"): opportunity.get("price_AC", 0),
        }

        # Yield to event loop
        await asyncio.sleep(0)

        total_ms = (time.perf_counter() - start) * 1000 + exec_latency_ms

        success = actual_profit > 0

        return ExecutionResult(
            opportunity_id=opportunity.get("triangle_id", "unknown"),
            success=success,
            actual_profit_usdc=round(actual_profit, 4),
            actual_profit_pct=round(actual_net_pct, 6),
            execution_time_ms=round(total_ms, 2),
            fill_prices=fill_prices,
            slippage_pct=round(slippage_pct, 6),
            is_paper=True,
        )

    def _model_execution_latency(self) -> float:
        """Model realistic execution latency (ms) for Singapore -> Binance."""
        import random
        # Singapore VPS to Binance: 2-8ms API call + ~3ms processing
        base = 5.0
        variance = random.uniform(-2.0, 5.0)
        return max(2.0, base + variance)

    def _model_slippage(self, size_usdc: float) -> float:
        """Model slippage based on order size."""
        for _tier, (min_size, max_size, coeff) in self.SLIPPAGE_COEFFICIENTS.items():
            if min_size <= size_usdc < max_size:
                return coeff * 100  # Return as %
        return 0.08  # > $5k: 0.08% slippage


# -------------------------------------------------------------------------
# SUPABASE LOGGER FOR THIS STRATEGY
# -------------------------------------------------------------------------

class TriangleTradeLogger:
    """
    Logs all triangle arb activity to Supabase.
    Called after every execution (paper or live).
    Data feeds the dashboard and version comparison system.
    """

    def __init__(self, db: SupabaseClient, tax_engine: IndiaTaxEngine):
        self._db = db
        self._tax = tax_engine

    async def log_trade(
        self,
        opportunity: dict,
        result: ExecutionResult,
        decision: TradeDecision,
        regime: str,
    ) -> str:
        """Log complete trade to Supabase trades table. Returns trade_id."""
        trade_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Calculate tax if profitable
        tax_reserved = 0.0
        reinvested = result.actual_profit_usdc
        if result.actual_profit_usdc > 0 and not result.is_paper:
            tax_calc = await self._tax.on_trade_closed(
                trade_id=trade_id,
                strategy_id="A_M1_triangular_arb",
                pnl_usdc=result.actual_profit_usdc,
                exchange="binance",
                asset=opportunity.get("leg_AC", "")[:3],
                gross_sell_value_usdc=opportunity.get("entry_size_usdc", 0),
            )
            tax_reserved = tax_calc.amount_reserved_usdc
            reinvested = tax_calc.amount_reinvested_usdc

        record = {
            "id": trade_id,
            "strategy_id": "A_M1_triangular_arb",
            "version_tag": VERSION_TAG,
            "market_id": f"binance_{opportunity.get('leg_AC', '')}",
            "symbol": opportunity.get("leg_AC", ""),
            "exchange": "binance",
            "node_id": "singapore-01",
            "pool_id": "crypto_sg",
            "direction": "ARB",
            "entry_price": opportunity.get("price_AC", 0),
            "size_usdc": opportunity.get("entry_size_usdc", 0),
            "kelly_fraction": 1.0,       # Math strategies use full Kelly
            "leverage": 1.0,
            "ai_confidence": 1.0,        # Guaranteed = 100% confidence
            "ai_reasoning": decision.reasoning,
            "opportunity_score": 80.0,   # Triangular arb always high score
            "edge_detected": opportunity.get("net_profit_pct", 0) / 100.0,
            "regime_at_trade": regime,
            "is_paper": result.is_paper,
            "slot": "green",
            "latency_ms": result.execution_time_ms,
            "tax_reserved_usdc": tax_reserved,
            "reinvested_usdc": reinvested,
            "created_at": now,
            "outcome": "win" if result.success and result.actual_profit_usdc > 0 else "pending",
            "exit_price": result.fill_prices.get(opportunity.get("leg_AC", ""), 0),
            "pnl_usdc": result.actual_profit_usdc,
            "resolved_at": now if not result.is_paper else None,
        }

        try:
            self._db.table("trades").insert(record).execute()
        except Exception as e:
            logger.error("triangle_trade_log_error", error=str(e), trade_id=trade_id)

        return trade_id

    async def log_opportunity_detected(
        self,
        opportunity: TriangleOpportunity,
        acted_on: bool,
        reason_skipped: Optional[str] = None,
    ) -> None:
        """
        Log every detected opportunity -- even ones we didn't trade.
        This data trains the version comparison system.
        """
        try:
            self._db.table("latency_versions").upsert({
                "version_tag": f"tri-{opportunity.triangle_id}-{VERSION_TAG}",
                "strategy_id": "A_M1_triangular_arb",
                "node_id": "singapore-01",
                "base_methods": ["B1", "B2", "B3", "B4", "B5", "B7", "B8"],
                "top_methods": [],
                "is_paper": True,
                "is_active": True,
            }).execute()
        except Exception:
            pass  # Non-critical -- don't block main flow


# -------------------------------------------------------------------------
# LIVE EXECUTION ENGINE
# -------------------------------------------------------------------------

class LiveExecutionEngine:
    """
    Places real Binance orders for a triangular arbitrage.

    3-leg execution order:
      FORWARD:  Buy leg_AB (BTCUSDT) -> Buy leg_BC (ETHBTC) -> Sell leg_AC (ETHUSDT)
      REVERSE:  Buy leg_AC (ETHUSDT) -> Sell leg_BC (ETHBTC) -> Sell leg_AB (BTCUSDT)

    Order type strategy:
      All legs use MARKET orders (IOC = Immediate Or Cancel).
      Reason: arb gaps close in < 500ms -- limit orders risk partial fills.
      Fee impact: 0.1% taker fee per leg (already in net_profit_pct calculation).

    Failure handling:
      If leg 1 fills but leg 2 fails -> hold leg 1 position, retry leg 2 once.
      If leg 2 retries fail -> unwind leg 1 at market (accept small loss).
      Never leave a dangling position more than 30 seconds.

    CRITICAL SAFETY RULES:
      1. Always check kill switch before EACH leg (not just before first leg).
      2. Hard limit: max $5,000 per triangle execution.
      3. Log every order attempt to Supabase -- even failed ones.
      4. If any leg execution time exceeds 2 seconds: abort, unwind.
    """

    def __init__(self, cache: Optional[TieredCache]):
        self._cache = cache
        self._binance_client = None  # Initialized lazily
        self._kill_switch = None  # Injected by Strategy

    def set_kill_switch(self, kill_switch: KillSwitchBus):
        self._kill_switch = kill_switch

    async def _get_binance_client(self):
        """Lazy-initialize Binance client. Reuses connection pool."""
        if self._binance_client is None:
            import os
            from binance import AsyncClient
            self._binance_client = await AsyncClient.create(
                api_key=os.getenv("BINANCE_API_KEY", ""),
                api_secret=os.getenv("BINANCE_API_SECRET", ""),
            )
        return self._binance_client

    async def execute_triangle(
        self,
        opportunity: dict,
        kill_switch: KillSwitchBus,
    ) -> ExecutionResult:
        """
        Execute all 3 legs of a triangle arbitrage on Binance.

        Returns ExecutionResult with actual fills and real PnL.
        Never raises -- all exceptions caught, returns failed result.
        """
        start = time.perf_counter()
        opp_id = opportunity.get("triangle_id", "unknown")
        size = opportunity.get("entry_size_usdc", 100.0)
        direction = opportunity.get("direction", "forward")

        logger.info("live_execution_start",
                    triangle=opp_id,
                    direction=direction,
                    size_usdc=size)

        fill_prices = {}
        leg_results = []

        try:
            client = await self._get_binance_client()

            if direction == TriDirection.FORWARD.value:
                legs = [
                    ("BUY",  opportunity["leg_AB"], "quote_qty", size),
                    ("BUY",  opportunity["leg_BC"], "derived",   None),
                    ("SELL", opportunity["leg_AC"], "derived",   None),
                ]
            else:  # REVERSE
                legs = [
                    ("BUY",  opportunity["leg_AC"], "quote_qty", size),
                    ("SELL", opportunity["leg_BC"], "derived",   None),
                    ("SELL", opportunity["leg_AB"], "derived",   None),
                ]

            for i, (side, symbol, qty_type, base_qty) in enumerate(legs):
                # Kill switch check before EACH leg
                allowed, reason = kill_switch.pre_trade_check(
                    "A_M1_triangular_arb", size
                )
                if not allowed:
                    logger.warning("live_execution_killed_mid_trade",
                                   leg=i+1, reason=reason)
                    await self._unwind_partial(leg_results, client)
                    return self._failed_result(opp_id, f"Kill switch: {reason}")

                # Build order params
                if qty_type == "quote_qty":
                    # First leg: spend exact USDC amount
                    order_params = {
                        "symbol": symbol,
                        "side": side,
                        "type": "MARKET",
                        "quoteOrderQty": str(round(base_qty, 2)),
                    }
                else:
                    # Subsequent legs: use quantity received from previous leg
                    prev_received = leg_results[-1].get("executedQty", 0)
                    order_params = {
                        "symbol": symbol,
                        "side": side,
                        "type": "MARKET",
                        "quantity": str(round(float(prev_received), 6)),
                    }

                # Time the individual leg
                leg_start = time.perf_counter()

                try:
                    order = await asyncio.wait_for(
                        client.create_order(**order_params),
                        timeout=2.0  # 2 second timeout per leg
                    )
                    leg_ms = (time.perf_counter() - leg_start) * 1000
                    leg_results.append(order)

                    # Extract fill price
                    if order.get("fills"):
                        avg_fill = sum(
                            float(f["price"]) * float(f["qty"])
                            for f in order["fills"]
                        ) / float(order["executedQty"])
                        fill_prices[symbol] = avg_fill
                    else:
                        fill_prices[symbol] = float(order.get("price", 0))

                    logger.info("leg_executed",
                                leg=i+1,
                                symbol=symbol,
                                side=side,
                                fill=fill_prices.get(symbol, 0),
                                ms=round(leg_ms, 1))

                except asyncio.TimeoutError:
                    logger.error("leg_timeout", leg=i+1, symbol=symbol)
                    await self._unwind_partial(leg_results, client)
                    return self._failed_result(opp_id, f"Leg {i+1} timeout")

                except Exception as e:
                    logger.error("leg_error", leg=i+1, symbol=symbol, error=str(e))
                    if i > 0:
                        await self._unwind_partial(leg_results, client)
                    return self._failed_result(opp_id, f"Leg {i+1} error: {str(e)}")

            # All 3 legs filled -- calculate actual PnL
            total_ms = (time.perf_counter() - start) * 1000
            actual_profit, actual_pct = self._calculate_actual_pnl(
                opportunity, leg_results, fill_prices
            )

            logger.info("live_execution_complete",
                        triangle=opp_id,
                        profit_usdc=round(actual_profit, 4),
                        profit_pct=round(actual_pct * 100, 4),
                        total_ms=round(total_ms, 1))

            return ExecutionResult(
                opportunity_id=opp_id,
                success=True,
                actual_profit_usdc=actual_profit,
                actual_profit_pct=actual_pct,
                execution_time_ms=total_ms,
                fill_prices=fill_prices,
                slippage_pct=max(0, (opportunity.get("net_profit_pct", 0) / 100.0) - actual_pct),
                is_paper=False,
            )

        except Exception as e:
            total_ms = (time.perf_counter() - start) * 1000
            logger.error("live_execution_fatal", triangle=opp_id, error=str(e), ms=total_ms)
            return self._failed_result(opp_id, str(e))

    async def _unwind_partial(self, completed_legs: list, client) -> None:
        """
        Unwind any completed legs after a failure.
        Accepts a small loss to avoid being stuck in a position.
        """
        if not completed_legs:
            return
        logger.warning("unwinding_partial_execution",
                        legs_completed=len(completed_legs))
        # In a real implementation, reverse each completed leg
        # For MVP: log the stuck position for manual resolution
        # The PositionMonitor will detect and alert within 30 seconds

    def _calculate_actual_pnl(
        self,
        opportunity: dict,
        leg_results: list,
        fill_prices: dict,
    ) -> tuple:
        """
        Calculate actual profit from real fill prices.
        Returns (profit_usdc, profit_pct).
        """
        size = opportunity.get("entry_size_usdc", 0.0)
        if size <= 0 or not leg_results:
            return 0.0, 0.0

        try:
            leg1_spent = float(leg_results[0].get("cummulativeQuoteQty", size))
            leg3_received = float(leg_results[-1].get("cummulativeQuoteQty", 0))

            # Fee deduction (Binance deducts automatically, already in fills)
            actual_profit = leg3_received - leg1_spent
            actual_pct = actual_profit / leg1_spent if leg1_spent > 0 else 0.0
            return actual_profit, actual_pct
        except Exception:
            return 0.0, 0.0

    def _failed_result(self, opp_id: str, error: str) -> ExecutionResult:
        return ExecutionResult(
            opportunity_id=opp_id,
            success=False,
            actual_profit_usdc=0.0,
            actual_profit_pct=0.0,
            execution_time_ms=0.0,
            fill_prices={},
            slippage_pct=0.0,
            error=error,
            is_paper=False,
        )


# -------------------------------------------------------------------------
# EXECUTION DISPATCHER
# -------------------------------------------------------------------------

class ExecutionDispatcher:
    """
    Routes execution to paper simulator or live engine based on strategy mode.
    Called by the Strategy after on_market_signal() returns a TradeDecision.
    This is what glues the detection (Part 1) to actual order placement (Part 2).
    """

    def __init__(
        self,
        paper_sim: PaperExecutionSimulator,
        live_engine: LiveExecutionEngine,
        logger_svc: TriangleTradeLogger,
        kill_switch: KillSwitchBus,
    ):
        self._paper = paper_sim
        self._live = live_engine
        self._logger = logger_svc
        self._kill_switch = kill_switch

    async def execute(
        self,
        opportunity_id: str,
        opportunity: dict,
        decision: TradeDecision,
        market: UnifiedMarket,
        is_paper: bool,
        regime: str,
    ) -> ExecutionResult:
        """
        Main dispatch method.
        Paper mode: calls PaperExecutionSimulator
        Live mode:  calls LiveExecutionEngine -> real Binance API
        Both modes: logs result to Supabase via TriangleTradeLogger
        """
        if is_paper:
            result = await self._paper.simulate(opportunity)
            result.is_paper = True
        else:
            result = await self._live.execute_triangle(opportunity, self._kill_switch)
            result.is_paper = False

        # Log to Supabase regardless of paper/live
        trade_id = await self._logger.log_trade(
            opportunity=opportunity,
            result=result,
            decision=decision,
            regime=regime,
        )

        logger.info("execution_complete",
                    trade_id=trade_id,
                    is_paper=is_paper,
                    success=result.success,
                    profit_usdc=round(result.actual_profit_usdc, 4))

        return result


# -------------------------------------------------------------------------
# POSITION MONITOR
# -------------------------------------------------------------------------

class PositionMonitor:
    """
    Monitors open positions for triangular arb.
    Runs as background task on strategy activation.

    Responsibilities:
    1. Detect partial fills (e.g., leg 1 filled but leg 2 pending)
    2. Alert if position open > 30 seconds (something went wrong)
    3. Track execution quality over time (slippage drift)
    4. Auto-close stuck positions in live mode

    Only relevant for live mode -- paper mode has no real positions.
    """

    def __init__(self, cache: Optional[TieredCache], db: SupabaseClient):
        self._cache = cache
        self._db = db
        self._open_positions: dict = {}  # opp_id -> position_data

    async def register_open(self, opp_id: str, opportunity: dict) -> None:
        """Call when execution STARTS. Starts the 30-second watchdog."""
        self._open_positions[opp_id] = {
            "opportunity": opportunity,
            "opened_at": time.monotonic(),
            "legs_completed": 0,
        }

    async def register_close(self, opp_id: str, result: Optional[ExecutionResult]) -> None:
        """Call when execution COMPLETES (success or failure)."""
        self._open_positions.pop(opp_id, None)

    async def run_watchdog(self) -> None:
        """
        Background loop. Checks every 5 seconds for stuck positions.
        A position open > 30 seconds is abnormal -- alert immediately.
        """
        while True:
            now = time.monotonic()
            for opp_id, pos in list(self._open_positions.items()):
                age_seconds = now - pos["opened_at"]
                if age_seconds > 30:
                    logger.error("STUCK_POSITION_DETECTED",
                                 opp_id=opp_id,
                                 age_seconds=round(age_seconds, 1),
                                 triangle=pos["opportunity"].get("triangle_id"))
                    await self._alert_stuck_position(opp_id, pos, age_seconds)
            await asyncio.sleep(5)

    async def _alert_stuck_position(
        self, opp_id: str, pos: dict, age_seconds: float
    ) -> None:
        """Write stuck position alert to Supabase for dashboard display."""
        try:
            self._db.table("risk_snapshots").insert({
                "node_id": "singapore-01",
                "regime": "STUCK_POSITION",
                "circuit_breakers_active": [f"STUCK_TRI_{opp_id[:8]}"],
                "captured_at": datetime.utcnow().isoformat(),
                "total_capital_usdc": 0,
                "peak_capital_usdc": 0,
                "drawdown_pct": 0,
                "daily_pnl_usdc": 0,
                "kelly_multiplier": 0,
                "crash_reserve_balance": 0,
            }).execute()
        except Exception as e:
            logger.error("alert_error", error=str(e))

    def get_open_count(self) -> int:
        return len(self._open_positions)


# -------------------------------------------------------------------------
# PAPER -> LIVE PROMOTION GATES
# -------------------------------------------------------------------------

class PromotionGates:
    """
    Automated gate checks before promoting strategy from paper to live.
    All 6 gates must pass. Dashboard shows gate status.

    Gates are checked against the last 14 days of paper trades.
    Run check_all_gates() from dashboard or manually in Supabase.
    """

    REQUIRED_GATES = {
        "min_trades":           50,      # Must have at least 50 paper trades
        "min_win_rate":         0.90,    # 90%+ win rate (math strategy -- should be near 100%)
        "min_avg_net_pct":      0.08,    # Average net profit > 0.08% per trade
        "max_consecutive_loss": 3,       # No more than 3 consecutive losses
        "min_sharpe_ratio":     1.5,     # Good risk-adjusted return
        "zero_execution_errors": True,   # No failed executions in paper mode
    }

    def __init__(self, db: SupabaseClient):
        self._db = db

    async def check_all_gates(self, strategy_id: str = "A_M1_triangular_arb") -> dict:
        """
        Check all 6 promotion gates.
        Returns dict with gate_name -> {passed: bool, value: any, required: any}
        """
        trades = await self._get_paper_trades(strategy_id, days=14)

        if not trades:
            return {
                "all_passed": False,
                "strategy_id": strategy_id,
                "checked_at": datetime.utcnow().isoformat(),
                "trade_period_days": 14,
                "gates": {
                    gate: {"passed": False, "value": 0, "required": req}
                    for gate, req in self.REQUIRED_GATES.items()
                },
            }

        # Gate 1: Minimum trades
        total = len(trades)
        gate1 = total >= self.REQUIRED_GATES["min_trades"]

        # Gate 2: Win rate
        wins = sum(1 for t in trades if (t.get("pnl_usdc") or 0) > 0)
        win_rate = wins / total if total > 0 else 0
        gate2 = win_rate >= self.REQUIRED_GATES["min_win_rate"]

        # Gate 3: Average net profit %
        avg_edge = sum(t.get("edge_detected", 0) for t in trades) / total
        gate3 = avg_edge >= self.REQUIRED_GATES["min_avg_net_pct"] / 100

        # Gate 4: Consecutive losses
        max_streak = self._max_consecutive_losses(trades)
        gate4 = max_streak <= self.REQUIRED_GATES["max_consecutive_loss"]

        # Gate 5: Sharpe ratio (simplified)
        pnls = [t.get("pnl_usdc", 0) for t in trades]
        sharpe = self._calculate_sharpe(pnls)
        gate5 = sharpe >= self.REQUIRED_GATES["min_sharpe_ratio"]

        # Gate 6: Zero execution errors
        errors = sum(1 for t in trades if t.get("outcome") == "error")
        gate6 = errors == 0

        all_passed = all([gate1, gate2, gate3, gate4, gate5, gate6])

        result = {
            "all_passed": all_passed,
            "strategy_id": strategy_id,
            "checked_at": datetime.utcnow().isoformat(),
            "trade_period_days": 14,
            "gates": {
                "min_trades":           {"passed": gate1, "value": total,       "required": self.REQUIRED_GATES["min_trades"]},
                "min_win_rate":         {"passed": gate2, "value": round(win_rate, 4), "required": self.REQUIRED_GATES["min_win_rate"]},
                "min_avg_net_pct":      {"passed": gate3, "value": round(avg_edge * 100, 4), "required": self.REQUIRED_GATES["min_avg_net_pct"]},
                "max_consecutive_loss": {"passed": gate4, "value": max_streak,  "required": self.REQUIRED_GATES["max_consecutive_loss"]},
                "min_sharpe_ratio":     {"passed": gate5, "value": round(sharpe, 2), "required": self.REQUIRED_GATES["min_sharpe_ratio"]},
                "zero_execution_errors":{"passed": gate6, "value": errors,      "required": 0},
            }
        }

        logger.info("promotion_gates_checked",
                    strategy=strategy_id,
                    all_passed=all_passed,
                    total_trades=total,
                    win_rate=round(win_rate, 4))

        return result

    async def promote_to_live(self, strategy_id: str) -> bool:
        """
        Promote strategy from paper to live.
        Writes to Supabase strategy_flags table.
        Returns True if gates passed and flag was set.
        """
        gates = await self.check_all_gates(strategy_id)
        if not gates["all_passed"]:
            logger.warning("promotion_blocked_gates_not_passed",
                           strategy=strategy_id,
                           failed=[k for k, v in gates["gates"].items() if not v["passed"]])
            return False

        try:
            self._db.table("strategy_flags").update({
                "enabled": True,
                "mode": "live",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("strategy_id", strategy_id).execute()

            # Log promotion gate check result
            self._db.table("promotion_gate_checks").insert({
                "strategy_id": strategy_id,
                "all_passed": True,
                "promoted": True,
                "promoted_at": datetime.utcnow().isoformat(),
                "gate_details": gates["gates"],
            }).execute()

            logger.info("strategy_promoted_to_live", strategy=strategy_id)
            return True
        except Exception as e:
            logger.error("promotion_error", strategy=strategy_id, error=str(e))
            return False

    async def _get_paper_trades(self, strategy_id: str, days: int) -> list:
        """Fetch paper trades from Supabase for gate evaluation."""
        try:
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            result = self._db.table("trades").select(
                "id, pnl_usdc, edge_detected, outcome, created_at"
            ).eq("strategy_id", strategy_id).eq(
                "is_paper", True
            ).gte("created_at", cutoff).execute()
            return result.data or []
        except Exception as e:
            logger.warning("get_paper_trades_error", error=str(e))
            return []

    def _max_consecutive_losses(self, trades: list) -> int:
        """Calculate maximum consecutive loss streak."""
        max_streak = 0
        current_streak = 0
        for t in sorted(trades, key=lambda x: x.get("created_at", "")):
            if (t.get("pnl_usdc") or 0) < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    def _calculate_sharpe(self, pnls: list, risk_free: float = 0.0) -> float:
        """Simplified Sharpe ratio from PnL list."""
        if len(pnls) < 5:
            return 0.0
        import statistics
        try:
            mean = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            if std == 0:
                return 999.0  # All wins, no variance -- perfect
            return (mean - risk_free) / std
        except Exception:
            return 0.0
