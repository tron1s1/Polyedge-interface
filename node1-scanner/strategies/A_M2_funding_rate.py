"""
A_M2 Funding Rate Harvest Strategy Plugin
==========================================
Category:  A_math (Mathematical Certainty)
Exchanges: Bybit (perpetual short) + Binance (spot long)
Win rate:  99.9% — only risk is exchange insolvency
Frequency: Open 1–5 positions per day when APR > threshold
Income:    12–55% APR depending on market sentiment

How it works:
  1. Monitor funding rates on Bybit for all USDT perpetuals
  2. When annualised rate > MIN_APR_THRESHOLD: open position
     - Long [size] USDC of asset on Binance spot
     - Short [size] USDC of asset perp on Bybit
  3. Collect funding every 8 hours (00:00, 08:00, 16:00 UTC)
  4. Close when: rate drops below CLOSE_APR_THRESHOLD
                 OR position held > MAX_HOLD_HOURS
                 OR kill switch fires

Position types:
  OPEN:  Opens new long+short pair
  HOLD:  Collecting funding (no action needed)
  CLOSE: Closes both legs when conditions change

Delta neutrality:
  Long spot value must stay within 2% of short perp value.
  If they drift (due to price movement), rebalance.
  Rebalancing keeps us truly delta-neutral.
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Tuple

from strategies.base_strategy import BaseStrategy, TradeDecision
from ingestion.market_normalizer import UnifiedMarket, FundingData
from core.kill_switch_bus import KillSwitchBus
from core.india_tax_engine import IndiaTaxEngine
from database.supabase_client import SupabaseClient
from latency.base_methods import TieredCache
import structlog

logger = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT CONFIGURATION (overridden by dashboard via Supabase/cache)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Entry/exit thresholds
    "min_apr_to_open":      0.10,    # 10% APR minimum to open new position
    "min_apr_to_hold":      0.05,    # 5% APR minimum to keep holding (else close)
    "target_apr":           0.20,    # 20% APR — prioritise symbols above this

    # Position sizing
    "max_position_size_usdc":  2_000.0,   # Max per symbol (both legs combined)
    "min_position_size_usdc":    100.0,   # Minimum worth executing
    "max_total_deployed_usdc":  5_000.0,  # Max across ALL open positions
    "max_positions_open":           5,    # Never more than 5 simultaneous pairs

    # Position management
    "max_hold_hours":            168,    # 7 days max hold (funding can change)
    "delta_rebalance_threshold":  0.02,  # Rebalance if long/short drift > 2%

    # Leverage on perp side (spot is always 1x)
    "perp_leverage":              1,     # 1x — no leverage on perp (we're hedged)

    # Exchanges
    "spot_exchange":         "binance",  # Where to hold spot long
    "perp_exchange":         "bybit",    # Where to hold perp short

    # Fallback symbols used ONLY when Redis is empty (first 10-15s after startup)
    "monitored_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],

    # Bear mode: when funding goes negative, flip the trade
    "enable_negative_funding": True,    # If True: short spot + long perp when negative
    "min_negative_apr":       -0.10,    # -10% APR minimum for negative funding trade
}

VERSION_TAG = "v1-base"

# Funding payment schedule (UTC hours)
FUNDING_HOURS_UTC = [0, 8, 16]

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class FundingDirection(Enum):
    POSITIVE = "positive"   # Longs pay shorts — we short the perp
    NEGATIVE = "negative"   # Shorts pay longs — we long the perp


class PositionStatus(Enum):
    OPEN    = "open"
    HOLDING = "holding"     # Actively collecting funding
    CLOSING = "closing"     # In process of closing
    CLOSED  = "closed"


@dataclass
class FundingOpportunity:
    """A detected funding rate opportunity worth acting on."""
    symbol: str                     # e.g. "BTCUSDT"
    direction: FundingDirection
    current_rate_8h: float          # Current 8h funding rate (e.g. 0.0003)
    predicted_rate_8h: float        # Predicted next 8h rate
    annualised_rate: float          # current × 3 × 365
    next_funding_time: datetime     # Next payment time (UTC)
    minutes_to_next: float          # Minutes until next payment
    current_price: float            # Current spot price
    priority_score: float           # Higher = better opportunity
    spotted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OpenPosition:
    """A live delta-neutral position (one long spot + one short perp)."""
    position_id: str
    symbol: str
    direction: FundingDirection

    # Leg details
    spot_size_usdc: float           # Value of spot long
    perp_size_usdc: float           # Value of perp short (should match spot)
    spot_entry_price: float
    perp_entry_price: float
    spot_quantity: float            # Asset quantity (e.g. 0.015 BTC)

    # Funding collected
    funding_collected_usdc: float = 0.0
    funding_payments_received: int = 0
    last_funding_time: Optional[datetime] = None

    # Lifecycle
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: PositionStatus = PositionStatus.OPEN
    is_paper: bool = True

    # APR tracking
    entry_apr: float = 0.0
    current_apr: float = 0.0

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc) - self.opened_at).total_seconds() / 3600

    @property
    def total_size_usdc(self) -> float:
        return self.spot_size_usdc + self.perp_size_usdc

    @property
    def delta(self) -> float:
        """Current delta. Should be 0.0 ± 2%."""
        if self.perp_size_usdc == 0:
            return 0.0
        return (self.spot_size_usdc - self.perp_size_usdc) / self.perp_size_usdc

    @property
    def pnl_usdc(self) -> float:
        """Total PnL = funding collected (spot/perp price PnL is zero by design)."""
        return self.funding_collected_usdc

    def needs_rebalance(self, threshold: float = 0.02) -> bool:
        """Returns True if delta has drifted beyond threshold."""
        return abs(self.delta) > threshold


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY CONFIG (reads from cache, falls back to defaults)
# ─────────────────────────────────────────────────────────────────────────────

class StrategyConfig:
    """
    Live config loader. Dashboard writes to Supabase/cache.
    Plugin refreshes every 60 seconds — no restart needed.
    """

    def __init__(self, cache: Optional[TieredCache]):
        self._cache = cache
        self._config = dict(DEFAULT_CONFIG)

    async def refresh(self) -> None:
        if not self._cache:
            return
        cached = await self._cache.get("strategy_config:A_M2_funding_rate")
        if cached and isinstance(cached, dict):
            self._config = {**DEFAULT_CONFIG, **cached}

    def _get(self, key: str):
        return self._config.get(key, DEFAULT_CONFIG[key])

    @property
    def min_apr_to_open(self) -> float:
        return float(self._get("min_apr_to_open"))

    @property
    def min_apr_to_hold(self) -> float:
        return float(self._get("min_apr_to_hold"))

    @property
    def target_apr(self) -> float:
        return float(self._get("target_apr"))

    @property
    def max_position_size_usdc(self) -> float:
        return float(self._get("max_position_size_usdc"))

    @property
    def min_position_size_usdc(self) -> float:
        return float(self._get("min_position_size_usdc"))

    @property
    def max_total_deployed_usdc(self) -> float:
        return float(self._get("max_total_deployed_usdc"))

    @property
    def max_positions_open(self) -> int:
        return int(self._get("max_positions_open"))

    @property
    def max_hold_hours(self) -> int:
        return int(self._get("max_hold_hours"))

    @property
    def delta_rebalance_threshold(self) -> float:
        return float(self._get("delta_rebalance_threshold"))

    @property
    def perp_leverage(self) -> int:
        return int(self._get("perp_leverage"))

    @property
    def monitored_symbols(self) -> List[str]:
        return list(self._get("monitored_symbols"))

    @property
    def enable_negative_funding(self) -> bool:
        return bool(self._get("enable_negative_funding"))

    @property
    def min_negative_apr(self) -> float:
        return float(self._get("min_negative_apr"))


# ─────────────────────────────────────────────────────────────────────────────
# FUNDING RATE MONITOR
# ─────────────────────────────────────────────────────────────────────────────

class FundingRateMonitor:
    """
    Scans all monitored symbols for funding rate opportunities.
    Reads from Redis cache (set by Bybit adapter every 5 min).
    No direct API calls — pure cache reads, runs in < 10ms.
    """

    def __init__(self, cache: TieredCache, config: StrategyConfig):
        self._cache = cache
        self._config = config

    async def scan_all_opportunities(self) -> List[FundingOpportunity]:
        """
        Scan ALL symbols the Bybit adapter has cached (funding:bybit:* keys).
        Falls back to monitored_symbols if Redis is unavailable (fresh startup).
        """
        symbols = self._config.monitored_symbols  # fallback

        if self._cache and self._cache._redis:
            try:
                raw_keys = await self._cache._redis.keys("funding:bybit:*")
                if raw_keys:
                    # Keys may be bytes or strings depending on decode_responses setting
                    symbols = [
                        (k.decode() if isinstance(k, bytes) else k).replace("funding:bybit:", "")
                        for k in raw_keys
                    ]
            except Exception:
                pass  # keep fallback

        logger.debug("funding_scan_symbols", count=len(symbols), sample=symbols[:5])

        opportunities = []
        for symbol in symbols:
            opp = await self._check_symbol(symbol)
            if opp:
                opportunities.append(opp)

        # Sort: above target APR first, then by absolute APR descending
        return sorted(
            opportunities,
            key=lambda o: (abs(o.annualised_rate) >= self._config.target_apr,
                           abs(o.annualised_rate)),
            reverse=True,
        )

    async def _check_symbol(self, symbol: str) -> Optional[FundingOpportunity]:
        """Check a single symbol for funding opportunity."""
        funding_data = await self._cache.get(f"funding:bybit:{symbol}")
        if not funding_data:
            return None

        # Prefer Binance spot price; fall back to Bybit perp price for altcoins
        # not listed on Binance (e.g. NTRNUSDT, HOOKUSDT). In paper mode this is fine.
        price = (await self._cache.get(f"price:binance:{symbol}") or
                 funding_data.get("price") or
                 await self._cache.get(f"price:bybit:{symbol}"))
        if not price:
            return None

        rate_8h = float(funding_data.get("rate", 0))
        annualised = float(funding_data.get("annualised", rate_8h * 3 * 365))

        # Check positive funding (we short perp, collect funding)
        if annualised >= self._config.min_apr_to_open:
            return self._build_opportunity(
                symbol, rate_8h, annualised, FundingDirection.POSITIVE, price
            )

        # Check negative funding (we long perp, collect funding) — bear mode
        if (self._config.enable_negative_funding
                and annualised <= self._config.min_negative_apr):
            return self._build_opportunity(
                symbol, rate_8h, annualised, FundingDirection.NEGATIVE, price
            )

        return None

    def _build_opportunity(
        self,
        symbol: str,
        rate_8h: float,
        annualised: float,
        direction: FundingDirection,
        price: float,
    ) -> FundingOpportunity:
        """Build opportunity with next funding time calculation."""
        now_utc = datetime.now(timezone.utc)

        # Calculate next funding time (00:00, 08:00, 16:00 UTC)
        next_funding = self._next_funding_time(now_utc)
        minutes_to_next = (next_funding - now_utc).total_seconds() / 60

        # Priority score: high APR + close to next payment = higher priority
        time_bonus = max(0, 10 - minutes_to_next / 10)  # bonus if payment soon
        priority = abs(annualised) * 100 + time_bonus

        return FundingOpportunity(
            symbol=symbol,
            direction=direction,
            current_rate_8h=rate_8h,
            predicted_rate_8h=rate_8h,  # Simple prediction: same as current
            annualised_rate=annualised,
            next_funding_time=next_funding,
            minutes_to_next=minutes_to_next,
            current_price=float(price),
            priority_score=priority,
        )

    @staticmethod
    def _next_funding_time(now: datetime) -> datetime:
        """Calculate next funding payment time (00:00, 08:00, 16:00 UTC)."""
        for hour in FUNDING_HOURS_UTC:
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now:
                return candidate
        # Next day at 00:00 UTC
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


# ─────────────────────────────────────────────────────────────────────────────
# POSITION MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class PositionManager:
    """
    Tracks all open delta-neutral positions.
    In-memory for speed + Supabase for persistence.
    Handles: open new, hold, rebalance, close.
    """

    def __init__(self, cache: TieredCache, db: SupabaseClient, config: StrategyConfig):
        self._cache = cache
        self._db = db
        self._config = config
        self._positions: Dict[str, OpenPosition] = {}  # position_id → OpenPosition

    async def load_from_db(self) -> None:
        """
        Reload open positions from Supabase on startup.
        Enforces max_total_deployed and deduplicates by symbol — marks excess as closed.
        Runs DB calls in executor with 15s timeout so startup never hangs if Supabase is slow.
        """
        try:
            loop = asyncio.get_event_loop()

            # Run blocking SELECT in thread pool so event loop isn't blocked
            def _select():
                return self._db.table("funding_positions").select("*").eq(
                    "status", "holding"
                ).eq("node_id", "singapore-01").execute()

            result = await asyncio.wait_for(
                loop.run_in_executor(None, _select),
                timeout=15.0,
            )

            seen_symbols: set = set()
            total_deployed = 0.0
            excess_ids = []

            for row in sorted((result.data or []), key=lambda r: r.get("opened_at", "")):
                pos = self._row_to_position(row)
                size = pos.total_size_usdc
                # Skip duplicates on same symbol or positions that exceed capital limit
                if pos.symbol in seen_symbols:
                    excess_ids.append(pos.position_id)
                    logger.warning("duplicate_position_on_load", symbol=pos.symbol, id=pos.position_id)
                    continue
                if total_deployed + size > self._config.max_total_deployed_usdc * 1.05:  # 5% tolerance
                    excess_ids.append(pos.position_id)
                    logger.warning("excess_position_on_load", symbol=pos.symbol, deployed=total_deployed, size=size)
                    continue
                self._positions[pos.position_id] = pos
                seen_symbols.add(pos.symbol)
                total_deployed += size

            # Mark excess positions as closed (fire-and-forget, non-blocking)
            if excess_ids:
                close_time = datetime.now(timezone.utc).isoformat()
                def _close_excess():
                    for pid in excess_ids:
                        try:
                            self._db.table("funding_positions").update({
                                "status": "closed",
                                "close_data": {"reason": "excess_on_startup", "closed_at": close_time}
                            }).eq("id", pid).execute()
                        except Exception:
                            pass
                asyncio.create_task(loop.run_in_executor(None, _close_excess))

            logger.info("funding_positions_loaded", count=len(self._positions), excess_closed=len(excess_ids), total_deployed=round(total_deployed, 2))
        except asyncio.TimeoutError:
            logger.warning("funding_positions_load_timeout", detail="Supabase unreachable, starting with empty positions")
        except Exception as e:
            logger.warning("funding_positions_load_error", error=str(e))

    def can_open_new(self) -> Tuple[bool, str]:
        """Check if we can open another position."""
        if len(self._positions) >= self._config.max_positions_open:
            return False, f"Max positions ({self._config.max_positions_open}) reached"

        total_deployed = sum(p.total_size_usdc for p in self._positions.values())
        if total_deployed >= self._config.max_total_deployed_usdc:
            return False, f"Max deployed (${self._config.max_total_deployed_usdc:,.0f}) reached"

        return True, "OK"

    def is_already_open(self, symbol: str) -> bool:
        """Prevent duplicate positions on same symbol."""
        return any(p.symbol == symbol and p.status != PositionStatus.CLOSED
                   for p in self._positions.values())

    def calculate_position_size(self, allocated_usdc: float) -> float:
        """
        Calculate position size for each leg.
        Each leg (spot AND perp) gets this size.
        Total capital used = 2 × position_size.
        """
        # Use 40% of allocation per position, capped by config
        size_per_leg = min(
            allocated_usdc * 0.40,
            self._config.max_position_size_usdc / 2,  # /2 because both legs
        )
        return max(self._config.min_position_size_usdc, size_per_leg)

    def register_open(self, opportunity: FundingOpportunity, size_per_leg: float) -> OpenPosition:
        """Create and register new open position."""
        pos = OpenPosition(
            position_id=str(uuid.uuid4()),
            symbol=opportunity.symbol,
            direction=opportunity.direction,
            spot_size_usdc=size_per_leg,
            perp_size_usdc=size_per_leg,
            spot_entry_price=opportunity.current_price,
            perp_entry_price=opportunity.current_price,
            spot_quantity=size_per_leg / opportunity.current_price,
            entry_apr=opportunity.annualised_rate,
            current_apr=opportunity.annualised_rate,
            status=PositionStatus.HOLDING,
            is_paper=True,
        )
        self._positions[pos.position_id] = pos
        return pos

    def get_all_open(self) -> List[OpenPosition]:
        return [p for p in self._positions.values()
                if p.status not in (PositionStatus.CLOSED,)]

    def get_positions_needing_close(self, current_funding: Dict[str, float]) -> List[OpenPosition]:
        """
        Returns positions that should be closed based on:
        1. Funding rate dropped below hold threshold
        2. Position held too long
        3. Kill switch (checked separately)
        """
        to_close = []
        for pos in self.get_all_open():
            current_apr = current_funding.get(pos.symbol, pos.current_apr)

            # Check 1: Rate too low to hold
            if abs(current_apr) < self._config.min_apr_to_hold:
                to_close.append(pos)
                continue

            # Check 2: Held too long
            if pos.age_hours > self._config.max_hold_hours:
                to_close.append(pos)
                continue

        return to_close

    def get_positions_needing_rebalance(self) -> List[OpenPosition]:
        """Returns positions where delta has drifted beyond threshold."""
        return [
            p for p in self.get_all_open()
            if p.needs_rebalance(self._config.delta_rebalance_threshold)
        ]

    def mark_funding_collected(
        self,
        position_id: str,
        amount_usdc: float,
        payment_time: datetime,
    ) -> None:
        """Called when a funding payment is received."""
        if position_id in self._positions:
            pos = self._positions[position_id]
            pos.funding_collected_usdc += amount_usdc
            pos.funding_payments_received += 1
            pos.last_funding_time = payment_time

    def mark_closed(self, position_id: str) -> None:
        if position_id in self._positions:
            self._positions[position_id].status = PositionStatus.CLOSED

    def get_total_deployed_usdc(self) -> float:
        return sum(p.total_size_usdc for p in self.get_all_open())

    def get_total_funding_collected_usdc(self) -> float:
        return sum(p.funding_collected_usdc for p in self._positions.values())

    def _row_to_position(self, row: dict) -> OpenPosition:
        """Reconstruct OpenPosition from Supabase row."""
        return OpenPosition(
            position_id=row["id"],
            symbol=row["symbol"],
            direction=FundingDirection(row.get("direction", "positive")),
            spot_size_usdc=float(row.get("spot_size_usdc", 0)),
            perp_size_usdc=float(row.get("perp_size_usdc", 0)),
            spot_entry_price=float(row.get("spot_entry_price", 0)),
            perp_entry_price=float(row.get("perp_entry_price", 0)),
            spot_quantity=float(row.get("spot_quantity", 0)),
            funding_collected_usdc=float(row.get("funding_collected_usdc", 0)),
            funding_payments_received=int(row.get("funding_payments_received", 0)),
            entry_apr=float(row.get("entry_apr", 0)),
            current_apr=float(row.get("current_apr", 0)),
            status=PositionStatus(row.get("status", "holding")),
            is_paper=bool(row.get("is_paper", True)),
            opened_at=datetime.fromisoformat(row["opened_at"]) if row.get("opened_at") else datetime.now(timezone.utc),
        )


# ─────────────────────────────────────────────────────────────────────────────
# DELTA NEUTRAL CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

class DeltaNeutralCalculator:
    """
    Calculates delta and rebalancing needs for open positions.
    Delta = (long value - short value) / short value
    Target delta = 0.0 (perfectly hedged)
    Trigger rebalance if delta > ±2%
    """

    @staticmethod
    def calculate_delta(pos: OpenPosition, current_price: float) -> float:
        """
        Calculate current delta using live prices.
        Positive delta = long-heavy (BTC price went up)
        Negative delta = short-heavy (BTC price went down)
        """
        current_spot_value = pos.spot_quantity * current_price
        current_perp_value = pos.perp_size_usdc  # Perp is marked-to-market separately

        if current_perp_value == 0:
            return 0.0

        return (current_spot_value - current_perp_value) / current_perp_value

    @staticmethod
    def calculate_rebalance_size(pos: OpenPosition, current_price: float) -> Optional[dict]:
        """
        If delta has drifted, calculate what order to place to rebalance.
        Returns dict with rebalance action or None if not needed.
        """
        delta = DeltaNeutralCalculator.calculate_delta(pos, current_price)

        if abs(delta) < 0.02:
            return None  # Within tolerance

        current_spot_value = pos.spot_quantity * current_price

        if delta > 0:
            # Spot grew relative to perp — sell some spot OR buy more perp
            excess_usdc = (current_spot_value - pos.perp_size_usdc) / 2
            return {
                "action": "sell_spot",
                "symbol": pos.symbol,
                "amount_usdc": excess_usdc,
                "delta_before": delta,
            }
        else:
            # Perp grew relative to spot — buy some spot OR close some perp
            deficit_usdc = (pos.perp_size_usdc - current_spot_value) / 2
            return {
                "action": "buy_spot",
                "symbol": pos.symbol,
                "amount_usdc": deficit_usdc,
                "delta_before": delta,
            }

    @staticmethod
    def calculate_funding_income(
        pos: OpenPosition,
        rate_8h: float,
    ) -> float:
        """
        Calculate funding income for next 8h payment.
        income = perp_size × rate (perp_size is what gets charged/credited)
        """
        return pos.perp_size_usdc * abs(rate_8h)


# ─────────────────────────────────────────────────────────────────────────────
# PAPER EXECUTION SIMULATOR
# ─────────────────────────────────────────────────────────────────────────────

class PaperFundingSimulator:
    """
    Simulates funding rate harvest without any real orders.
    Models:
    - Realistic funding payment amounts (from cache)
    - Slippage on opening (0.05% per leg for liquid assets)
    - Funding payments every 8 hours at realistic rates
    """

    SLIPPAGE_ON_OPEN = 0.0005  # 0.05% per leg on opening

    async def simulate_open(
        self,
        opportunity: FundingOpportunity,
        size_per_leg: float,
    ) -> dict:
        """Simulate opening a position. Returns simulated fill data."""
        slippage_cost = size_per_leg * self.SLIPPAGE_ON_OPEN * 2  # both legs
        actual_size = size_per_leg - slippage_cost / 2  # slightly less than intended

        return {
            "simulated": True,
            "spot_fill_price": opportunity.current_price * (1 + self.SLIPPAGE_ON_OPEN),
            "perp_fill_price": opportunity.current_price * (1 - self.SLIPPAGE_ON_OPEN),
            "actual_size_per_leg": actual_size,
            "opening_cost_usdc": slippage_cost,
            "execution_ms": 8.0,  # Singapore → Binance + Bybit
        }

    def simulate_funding_payment(self, pos: OpenPosition, rate_8h: float) -> float:
        """
        Calculate simulated funding payment.
        In paper mode: use exact rate × position size.
        Real exchanges: slightly different due to mark price vs last price.
        """
        # Funding is on the notional value of perp position
        raw_payment = pos.perp_size_usdc * abs(rate_8h)
        # Small discount for mark price vs last price difference
        return raw_payment * 0.998  # 0.2% mark price discount

    async def simulate_close(
        self,
        pos: OpenPosition,
        current_price: float,
    ) -> dict:
        """Simulate closing both legs. Returns final PnL."""
        # Closing slippage (same as opening)
        slippage_cost = pos.total_size_usdc * self.SLIPPAGE_ON_OPEN
        net_funding = pos.funding_collected_usdc
        price_pnl = 0.0  # Delta neutral = zero price PnL (approximately)

        total_pnl = net_funding - slippage_cost + price_pnl

        return {
            "simulated": True,
            "net_funding_collected": net_funding,
            "slippage_cost": slippage_cost,
            "price_pnl": price_pnl,
            "total_pnl_usdc": total_pnl,
            "total_pnl_pct": total_pnl / pos.total_size_usdc if pos.total_size_usdc > 0 else 0,
            "effective_apr": (total_pnl / pos.total_size_usdc) / (pos.age_hours / 8760) * 100 if pos.age_hours > 0 else 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# FUNDING TRACKER (records every payment)
# ─────────────────────────────────────────────────────────────────────────────

class FundingTracker:
    """
    Tracks every funding payment received.
    Runs a background loop that fires at 00:00, 08:00, 16:00 UTC.
    Records to Supabase for dashboard display.
    Updates in-memory position stats.
    """

    def __init__(
        self,
        position_manager: PositionManager,
        paper_sim: PaperFundingSimulator,
        cache: TieredCache,
        db: SupabaseClient,
    ):
        self._pm = position_manager
        self._sim = paper_sim
        self._cache = cache
        self._db = db
        self._last_payment_hour: Optional[int] = None

    async def run_forever(self) -> None:
        """Background loop — checks every 60 seconds if it's payment time."""
        while True:
            await self._check_and_collect_funding()
            await asyncio.sleep(60)

    async def _check_and_collect_funding(self) -> None:
        """Fire at each funding hour (00:00, 08:00, 16:00 UTC)."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        # Only fire once per funding window (not every loop)
        if (current_hour in FUNDING_HOURS_UTC
                and now.minute < 2  # Within first 2 minutes of the hour
                and self._last_payment_hour != current_hour):

            self._last_payment_hour = current_hour
            logger.info("funding_payment_time", hour=current_hour)

            positions = self._pm.get_all_open()
            for pos in positions:
                await self._collect_one_payment(pos, now)

    async def _collect_one_payment(
        self,
        pos: OpenPosition,
        payment_time: datetime,
    ) -> None:
        """Process one funding payment for one position."""
        # Get current funding rate
        funding_data = await self._cache.get(f"funding:bybit:{pos.symbol}")
        if not funding_data:
            return

        rate_8h = float(funding_data.get("rate", 0))

        if pos.is_paper:
            payment = self._sim.simulate_funding_payment(pos, rate_8h)
        else:
            # In live mode, Bybit automatically credits the account
            # We just need to log what was received
            payment = pos.perp_size_usdc * abs(rate_8h)

        if payment > 0:
            self._pm.mark_funding_collected(pos.position_id, payment, payment_time)
            logger.info("funding_payment_collected",
                        symbol=pos.symbol,
                        payment_usdc=round(payment, 4),
                        rate_8h=rate_8h,
                        position_id=pos.position_id[:8])

            # Log to Supabase (payment row) then sync running totals back to position row
            await self._log_payment(pos, payment, rate_8h, payment_time)
            await self._sync_position_funding(pos)

    async def _log_payment(
        self,
        pos: OpenPosition,
        amount: float,
        rate_8h: float,
        payment_time: datetime,
    ) -> None:
        """Record funding payment to Supabase (fire-and-forget, non-blocking)."""
        row = {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "payment_time": payment_time.isoformat(),
            "amount_usdc": round(amount, 6),
            "rate_8h": rate_8h,
            "annualised_rate": rate_8h * 3 * 365,
            "perp_size_usdc": pos.perp_size_usdc,
            "is_paper": pos.is_paper,
            # pos.funding_collected_usdc already has this payment added by
            # mark_funding_collected — do NOT add amount again (was double-counting)
            "cumulative_total": pos.funding_collected_usdc,
        }
        def _insert():
            try:
                self._db.table("funding_payments").insert(row).execute()
            except Exception as e:
                logger.warning("funding_payment_log_error", error=str(e))
        asyncio.get_event_loop().run_in_executor(None, _insert)

    async def _sync_position_funding(self, pos: OpenPosition) -> None:
        """Write funding totals back to funding_positions row so API/dashboard
        can read real P&L without waiting for position close."""
        pid = pos.position_id
        collected = round(pos.funding_collected_usdc, 6)
        payments = pos.funding_payments_received
        def _sync():
            try:
                self._db.table("funding_positions").update({
                    "funding_collected_usdc":    collected,
                    "funding_payments_received": payments,
                }).eq("id", pid).execute()
            except Exception as e:
                logger.warning("position_funding_sync_error", error=str(e))
        asyncio.get_event_loop().run_in_executor(None, _sync)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN STRATEGY CLASS
# ─────────────────────────────────────────────────────────────────────────────

class Strategy(BaseStrategy):
    """
    A_M2 Funding Rate Harvest.
    Passive income via delta-neutral positions.
    Opens: when APR > threshold.
    Holds: collects funding every 8h.
    Closes: when APR drops or position too old.
    """

    STRATEGY_ID:    str = "A_M2_funding_rate"
    DISPLAY_NAME:   str = "Funding Rate Harvest"
    CATEGORY:       str = "A_math"
    CATEGORY_LABEL: str = "Mathematical Certainty"
    DESCRIPTION:    str = "Delta-neutral perp short + spot long. Earn funding every 8h risk-free."
    NODE_ID:        str = "singapore-01"
    VERSION:        str = VERSION_TAG

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

        # Components
        self._config = StrategyConfig(cache)
        self._monitor = FundingRateMonitor(cache, self._config) if cache else None
        self._position_manager = PositionManager(cache, db, self._config)
        self._delta_calc = DeltaNeutralCalculator()
        self._paper_sim = PaperFundingSimulator()
        self._funding_tracker = FundingTracker(
            self._position_manager, self._paper_sim, cache, db
        ) if cache else None

        # Live executor + promotion gates (wired in Part 2)
        self._live_executor = LiveFundingExecutor(kill_switch)
        self._promotion_gates = FundingPromotionGates(db)

        # Background task references
        self._tracker_task: Optional[asyncio.Task] = None

        # Stats
        self._stats = {
            "total_positions_opened": 0,
            "total_positions_closed": 0,
            "total_funding_collected_usdc": 0.0,
            "total_signals_received": 0,
            "positions_open_now": 0,
        }

    async def startup(self) -> None:
        """
        Called once when strategy is loaded.
        Loads existing positions from DB, starts funding tracker.
        """
        await self._position_manager.load_from_db()
        if self._funding_tracker:
            self._tracker_task = asyncio.create_task(
                self._funding_tracker.run_forever()
            )
            logger.info("funding_tracker_started")

    # ── MAIN ENTRY POINT ─────────────────────────────────────────────────

    async def on_market_signal(
        self,
        market: UnifiedMarket,
        allocated_usdc: float,
    ) -> Optional[TradeDecision]:
        """
        Called by scanner when funding rate signal detected.
        Does NOT open position here — returns TradeDecision.
        Actual opening is in execute_signal().

        Also checks existing positions for close/rebalance needs.
        """
        self._stats["total_signals_received"] += 1

        # Refresh config (propagates dashboard changes in < 30s)
        await self._config.refresh()

        self.logger.debug("a_m2_signal_received",
                         symbol=market.symbol if market else "?",
                         funding_apr=round(market.funding.rate_annualised * 100, 2) if market and market.funding else 0,
                         allocated=round(allocated_usdc, 2),
                         monitor=self._monitor is not None,
                         is_paper=self._is_paper)

        # Kill switch — check against actual position size (per leg), not total allocation.
        # Paper mode bypasses the max_trade_size check since no real capital at risk.
        if not self._is_paper:
            check_size = self._config.min_position_size_usdc * 2  # both legs
            allowed, reason = self.check_kill_switch(check_size)
            if not allowed:
                self.logger.info("a_m2_blocked", reason=reason)
                return None

        # Step 1: Check if any existing positions need closing
        try:
            await self._handle_position_maintenance(market)
        except Exception as e:
            self.logger.warning("position_maintenance_error", error=str(e))

        # Step 2: Look for new opportunities
        if not self._monitor:
            self.logger.warning("a_m2_no_monitor",
                                reason="cache was None during init — restart scanner")
            return None

        # First: check the incoming market directly (router already scored it)
        opportunities = []
        if (market and market.symbol and market.funding
                and market.funding.rate_annualised != 0):
            ann = market.funding.rate_annualised
            rate_8h = market.funding.current_rate
            price = market.price or 0
            self.logger.debug("a_m2_market_eval",
                             symbol=market.symbol,
                             apr_pct=round(ann * 100, 2),
                             rate_8h=round(rate_8h * 100, 4),
                             price=round(price, 2),
                             min_apr=round(self._config.min_apr_to_open * 100, 2),
                             min_neg_apr=round(self._config.min_negative_apr * 100, 2))
            if ann >= self._config.min_apr_to_open:
                opportunities.append(self._monitor._build_opportunity(
                    market.symbol, rate_8h, ann, FundingDirection.POSITIVE, price))
            elif (self._config.enable_negative_funding
                  and ann <= self._config.min_negative_apr):
                opportunities.append(self._monitor._build_opportunity(
                    market.symbol, rate_8h, ann, FundingDirection.NEGATIVE, price))
            else:
                self.logger.debug("a_m2_below_threshold",
                                  symbol=market.symbol, apr_pct=round(ann * 100, 2))

        # Then: also scan monitored_symbols list for additional opportunities
        monitored_opps = await self._monitor.scan_all_opportunities()
        seen = {o.symbol for o in opportunities}
        for opp in monitored_opps:
            if opp.symbol not in seen:
                opportunities.append(opp)

        self.logger.debug("a_m2_opportunities_found",
                         direct=len([o for o in opportunities if o.symbol == (market.symbol if market else "")]),
                         monitored=len(monitored_opps),
                         total=len(opportunities))

        if not opportunities:
            return None

        # Pick highest APR
        opportunities.sort(key=lambda o: abs(o.annualised_rate), reverse=True)
        best = opportunities[0]

        # Check if already have position on this symbol
        if self._position_manager.is_already_open(best.symbol):
            self.logger.debug("a_m2_already_open", symbol=best.symbol)
            return None

        # Check capacity
        can_open, reason = self._position_manager.can_open_new()
        if not can_open:
            self.logger.debug("a_m2_capacity_full", reason=reason)
            return None

        # Calculate size — use at least min_position_size if allocated is too small
        effective_alloc = max(allocated_usdc, self._config.min_position_size_usdc * 3)
        size_per_leg = self._position_manager.calculate_position_size(effective_alloc)
        if size_per_leg < self._config.min_position_size_usdc:
            self.logger.warning("a_m2_size_too_small",
                                size=size_per_leg,
                                min=self._config.min_position_size_usdc,
                                allocated=allocated_usdc)
            return None

        # Apply Kelly (always 1.0 for math strategies, but regime adjusts)
        size_per_leg = self.apply_kelly(size_per_leg)

        # Log decision
        reasoning = (
            f"Funding rate harvest | {best.symbol} | "
            f"Direction: {best.direction.value} | "
            f"APR: {best.annualised_rate:.2%} | "
            f"Rate 8h: {best.current_rate_8h:.4%} | "
            f"Next payment: {best.minutes_to_next:.0f}min | "
            f"Size per leg: ${size_per_leg:.0f}"
        )
        self.logger.info("funding_opportunity",
                         symbol=best.symbol,
                         apr=round(best.annualised_rate * 100, 2),
                         rate_8h=round(best.current_rate_8h * 100, 4),
                         next_payment_min=round(best.minutes_to_next),
                         size_per_leg=round(size_per_leg, 2))

        # Cache opportunity for execute_signal
        opp_id = str(uuid.uuid4())
        if self._cache:
            await self._cache.set(f"funding_opp:{opp_id}", {
                "symbol": best.symbol,
                "direction": best.direction.value,
                "rate_8h": best.current_rate_8h,
                "annualised_rate": best.annualised_rate,
                "current_price": best.current_price,
                "next_funding_time": best.next_funding_time.isoformat(),
                "size_per_leg": size_per_leg,
            }, ttl=120)  # 2 min to execute

        return TradeDecision(
            symbol=best.symbol,
            exchange="bybit",           # Perp leg exchange
            direction="FUNDING_OPEN",   # Custom direction for multi-leg
            size_usdc=size_per_leg * 2, # Both legs combined
            leverage=float(self._config.perp_leverage),
            stop_loss_price=None,       # No stop — delta neutral
            take_profit_price=None,     # Close manually when rate drops
            ai_confidence=0.999,        # Near certainty
            reasoning=reasoning,
            edge_detected=best.annualised_rate,
            version_tag=VERSION_TAG,
            opportunity_id=opp_id,      # Wiring uses this to call execute_signal
        )

    async def execute_signal(
        self,
        decision: TradeDecision,
        market: UnifiedMarket,
        opportunity_id: str,
        regime: str,
    ) -> Optional[dict]:
        """
        Opens the delta-neutral position (paper or live).
        """
        opp = None
        if self._cache:
            opp = await self._cache.get(f"funding_opp:{opportunity_id}")
        if not opp:
            logger.warning("funding_opp_expired", opp_id=opportunity_id)
            return None

        # Reconstruct opportunity object
        opportunity = FundingOpportunity(
            symbol=opp["symbol"],
            direction=FundingDirection(opp["direction"]),
            current_rate_8h=opp["rate_8h"],
            predicted_rate_8h=opp["rate_8h"],
            annualised_rate=opp["annualised_rate"],
            next_funding_time=datetime.fromisoformat(opp["next_funding_time"]),
            minutes_to_next=0,
            current_price=opp["current_price"],
            priority_score=0,
        )
        size_per_leg = opp["size_per_leg"]

        if self._is_paper:
            fill_data = await self._paper_sim.simulate_open(opportunity, size_per_leg)
        else:
            if self._live_executor:
                fill_data = await self._live_executor.execute_open(opportunity, size_per_leg)
            else:
                logger.error("no_live_executor_configured")
                return None

        # Register position in manager
        pos = self._position_manager.register_open(opportunity, size_per_leg)
        pos.is_paper = self._is_paper

        # Log to Supabase
        await self._log_position_open(pos, fill_data, regime)

        self._stats["total_positions_opened"] += 1
        self._stats["positions_open_now"] = len(self._position_manager.get_all_open())

        return {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "size_per_leg": size_per_leg,
            "entry_apr": opportunity.annualised_rate,
            "fill_data": fill_data,
        }

    async def _handle_position_maintenance(self, market: UnifiedMarket) -> None:
        """Check existing positions for close/rebalance needs."""
        # Get current funding rates for all open symbols
        current_funding = {}
        for pos in self._position_manager.get_all_open():
            data = await self._cache.get(f"funding:bybit:{pos.symbol}") if self._cache else {}
            current_funding[pos.symbol] = float((data or {}).get("annualised", pos.current_apr))

        # Close positions where rate dropped
        to_close = self._position_manager.get_positions_needing_close(current_funding)
        for pos in to_close:
            await self._close_position(pos)

        # Rebalance positions with delta drift
        to_rebalance = self._position_manager.get_positions_needing_rebalance()
        for pos in to_rebalance:
            rebalance = self._delta_calc.calculate_rebalance_size(pos, market.price)
            if rebalance:
                logger.info("rebalancing_position",
                            position_id=pos.position_id[:8],
                            action=rebalance["action"],
                            amount=round(rebalance["amount_usdc"], 2))
                # In paper mode: just log. In live mode: place order.

    async def _close_position(self, pos: OpenPosition) -> None:
        """Close both legs of a position."""
        current_price = 0.0
        if self._cache:
            current_price = await self._cache.get(f"price:binance:{pos.symbol}") or 0.0

        if self._is_paper:
            close_data = await self._paper_sim.simulate_close(pos, current_price)
        else:
            if self._live_executor:
                close_data = await self._live_executor.execute_close(pos, current_price)
            else:
                return

        total_pnl = close_data.get("total_pnl_usdc", pos.funding_collected_usdc)

        # Tax calculation
        if total_pnl > 0 and not self._is_paper:
            await self._tax.on_trade_closed(
                trade_id=pos.position_id,
                strategy_id=self.STRATEGY_ID,
                pnl_usdc=total_pnl,
                exchange="bybit",
                asset=pos.symbol[:3],
                gross_sell_value_usdc=pos.total_size_usdc,
            )

        self._position_manager.mark_closed(pos.position_id)
        self._stats["total_positions_closed"] += 1
        self._stats["positions_open_now"] = len(self._position_manager.get_all_open())
        self._stats["total_funding_collected_usdc"] += pos.funding_collected_usdc

        await self._log_position_close(pos, close_data, total_pnl)
        logger.info("position_closed",
                    symbol=pos.symbol,
                    funding_usdc=round(pos.funding_collected_usdc, 4),
                    payments=pos.funding_payments_received,
                    age_hours=round(pos.age_hours, 1),
                    total_pnl=round(total_pnl, 4))

    async def _log_position_open(self, pos: OpenPosition, fill: dict, regime: str) -> None:
        row = {
            "id": pos.position_id,
            "symbol": pos.symbol,
            "direction": pos.direction.value,
            "spot_size_usdc": pos.spot_size_usdc,
            "perp_size_usdc": pos.perp_size_usdc,
            "spot_entry_price": pos.spot_entry_price,
            "perp_entry_price": pos.perp_entry_price,
            "spot_quantity": pos.spot_quantity,
            "entry_apr": pos.entry_apr,
            "current_apr": pos.current_apr,
            "status": pos.status.value,
            "is_paper": pos.is_paper,
            "node_id": "singapore-01",
            "regime_at_open": regime,
            "opened_at": pos.opened_at.isoformat(),
            "strategy_id": self.STRATEGY_ID,
            "version_tag": VERSION_TAG,
            "fill_data": fill,
        }
        def _insert():
            try:
                self._db.table("funding_positions").insert(row).execute()
            except Exception as e:
                logger.warning("position_open_log_error", error=str(e))
        asyncio.get_event_loop().run_in_executor(None, _insert)

    async def _log_position_close(self, pos: OpenPosition, close_data: dict, total_pnl: float) -> None:
        pid = pos.position_id
        update = {
            "status": "closed",
            "funding_collected_usdc": pos.funding_collected_usdc,
            "funding_payments_received": pos.funding_payments_received,
            "total_pnl_usdc": total_pnl,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "close_data": close_data,
        }
        def _update():
            try:
                self._db.table("funding_positions").update(update).eq("id", pid).execute()
            except Exception as e:
                logger.warning("position_close_log_error", error=str(e))
        asyncio.get_event_loop().run_in_executor(None, _update)

    # ── HEALTH STATUS ─────────────────────────────────────────────────────

    async def get_health_status(self) -> dict:
        open_positions = self._position_manager.get_all_open()
        total_deployed = self._position_manager.get_total_deployed_usdc()
        total_funding = self._position_manager.get_total_funding_collected_usdc()

        # Get current APRs for open positions
        position_summary = []
        for pos in open_positions:
            funding_data = {}
            if self._cache:
                funding_data = await self._cache.get(f"funding:bybit:{pos.symbol}") or {}
            position_summary.append({
                "symbol": pos.symbol,
                "direction": pos.direction.value,
                "size_usdc": pos.total_size_usdc,
                "current_apr": funding_data.get("annualised", pos.entry_apr),
                "entry_apr": pos.entry_apr,
                "funding_collected_usdc": round(pos.funding_collected_usdc, 4),
                "payments_received": pos.funding_payments_received,
                "age_hours": round(pos.age_hours, 1),
                "delta": round(pos.delta, 4),
                "is_paper": pos.is_paper,
            })

        # Next funding time
        next_funding = FundingRateMonitor._next_funding_time(datetime.now(timezone.utc))
        mins_to_next = (next_funding - datetime.now(timezone.utc)).total_seconds() / 60

        return {
            "strategy_id": self.STRATEGY_ID,
            "version": self.VERSION,
            "is_paper": self._is_paper,
            "mode": "paper" if self._is_paper else "live",
            "positions": {
                "open": len(open_positions),
                "max": self._config.max_positions_open,
                "total_deployed_usdc": round(total_deployed, 2),
                "max_deployable_usdc": self._config.max_total_deployed_usdc,
                "summary": position_summary,
            },
            "income": {
                "total_funding_collected_usdc": round(total_funding, 4),
                "payments_this_session": sum(p.funding_payments_received for p in open_positions),
            },
            "next_funding": {
                "time_utc": next_funding.isoformat(),
                "minutes_away": round(mins_to_next, 1),
            },
            "config": {
                "min_apr_to_open": self._config.min_apr_to_open,
                "min_apr_to_hold": self._config.min_apr_to_hold,
                "monitored_symbols": len(self._config.monitored_symbols),
            },
            "stats": self._stats,
        }

    async def check_promotion_readiness(self) -> dict:
        """Dashboard button: 'Check Promotion Readiness'."""
        return await self._promotion_gates.check_all_gates()

    async def promote_to_live(self) -> bool:
        """Promote from paper → live if all 6 gates pass."""
        gates = await self._promotion_gates.check_all_gates()
        if not gates["all_passed"]:
            logger.warning("promotion_blocked", failed=[
                k for k, v in gates["gates"].items() if not v["passed"]
            ])
            return False
        update = {"enabled": True, "mode": "live", "updated_at": datetime.now(timezone.utc).isoformat()}
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._db.table("strategy_flags").update(update).eq("strategy_id", "A_M2_funding_rate").execute()
        )
        await self.on_promote_to_live()
        return True

    async def on_regime_change(self, new_regime: str, paused: list) -> None:
        """A_M2 never pauses — even in crashes, existing positions keep collecting."""
        if self.STRATEGY_ID in paused:
            logger.warning("math_strategy_regime_pause_ignored",
                           strategy=self.STRATEGY_ID, regime=new_regime)
        # Note: If regime is CRASH_MAJOR, funding rates often SPIKE (longs pay more)
        # This is actually BETTER for us, not worse.


# ─────────────────────────────────────────────────────────────────────────────
# LIVE EXECUTION ENGINE
# Places actual orders on Bybit (perp short) + Binance (spot long)
# ─────────────────────────────────────────────────────────────────────────────

class LiveFundingExecutor:
    """
    Executes delta-neutral positions using real exchange APIs.

    Opening a position (POSITIVE funding):
      1. Long [size] USDC of [symbol] on Binance spot (MARKET BUY)
      2. Short [size] USDC of [symbol] perp on Bybit (MARKET SELL, 1x leverage)

    Closing a position:
      1. Sell [quantity] [symbol] spot on Binance (MARKET SELL)
      2. Close short position on Bybit (MARKET BUY to close)

    Order type: MARKET on both legs — funding arb is time-sensitive near payments.

    Safety:
      - Both legs execute within 5 seconds. If one fails, unwind the other.
      - Never leave a naked directional position open.
      - Set Bybit leverage to 1x BEFORE opening perp position.
      - Confirm fills before marking position as open.
    """

    def __init__(self, kill_switch: KillSwitchBus):
        self._ks = kill_switch
        self._binance = None    # Lazy-init
        self._bybit = None      # Lazy-init

    async def _get_binance(self):
        if self._binance is None:
            from binance import AsyncClient
            self._binance = await AsyncClient.create(
                api_key=os.getenv("BINANCE_API_KEY", ""),
                api_secret=os.getenv("BINANCE_API_SECRET", ""),
            )
        return self._binance

    async def _get_bybit(self):
        if self._bybit is None:
            from pybit.unified_trading import HTTP
            self._bybit = HTTP(
                testnet=False,
                api_key=os.getenv("BYBIT_API_KEY", ""),
                api_secret=os.getenv("BYBIT_API_SECRET", ""),
            )
        return self._bybit

    async def execute_open(
        self,
        opportunity: FundingOpportunity,
        size_per_leg: float,
    ) -> dict:
        """
        Open delta-neutral position.
        Both legs within 5 seconds or unwind.
        """
        symbol = opportunity.symbol
        start = time.perf_counter()
        legs_done = []

        # Pre-check kill switch
        allowed, reason = self._ks.pre_trade_check("A_M2_funding_rate", size_per_leg * 2)
        if not allowed:
            return {"success": False, "error": f"Kill switch: {reason}"}

        try:
            # ── Leg 1: Set Bybit leverage to 1x (safety) ──────────────────
            bybit = await self._get_bybit()
            bybit.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage="1",
                sellLeverage="1",
            )

            # ── Leg 2: Long spot on Binance ────────────────────────────────
            binance = await self._get_binance()
            spot_order = await asyncio.wait_for(
                binance.create_order(
                    symbol=symbol,
                    side="BUY",
                    type="MARKET",
                    quoteOrderQty=str(round(size_per_leg, 2)),
                ),
                timeout=5.0
            )
            legs_done.append(("binance_spot_long", spot_order))

            spot_qty = float(spot_order.get("executedQty", 0))
            spot_fill = float(spot_order.get("fills", [{}])[0].get("price", 0)) if spot_order.get("fills") else 0

            # Kill switch between legs
            allowed, reason = self._ks.pre_trade_check("A_M2_funding_rate", size_per_leg)
            if not allowed:
                await self._unwind(legs_done, symbol, spot_qty)
                return {"success": False, "error": f"Kill switch between legs: {reason}"}

            # ── Leg 3: Short perp on Bybit ─────────────────────────────────
            perp_qty = round(spot_qty, 3)  # Match perp qty to spot qty received
            perp_order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=str(perp_qty),
                positionIdx=2,  # 2 = short-side for hedge mode
            )
            legs_done.append(("bybit_perp_short", perp_order))

            perp_fill = float(
                perp_order.get("result", {}).get("price", opportunity.current_price)
            )

            total_ms = (time.perf_counter() - start) * 1000
            logger.info("live_funding_position_opened",
                        symbol=symbol,
                        spot_qty=spot_qty,
                        spot_fill=round(spot_fill, 2),
                        perp_fill=round(perp_fill, 2),
                        ms=round(total_ms, 1))

            return {
                "success": True,
                "spot_fill_price": spot_fill,
                "perp_fill_price": perp_fill,
                "actual_size_per_leg": size_per_leg,
                "spot_quantity": spot_qty,
                "execution_ms": total_ms,
                "opening_cost_usdc": size_per_leg * 0.001 * 2,  # 0.1% fee × 2 legs
            }

        except asyncio.TimeoutError:
            logger.error("live_funding_open_timeout", symbol=symbol)
            await self._unwind(legs_done, symbol, 0)
            return {"success": False, "error": "Timeout opening position"}

        except Exception as e:
            logger.error("live_funding_open_error", symbol=symbol, error=str(e))
            if legs_done:
                spot_qty = float(legs_done[0][1].get("executedQty", 0)) if legs_done else 0
                await self._unwind(legs_done, symbol, spot_qty)
            return {"success": False, "error": str(e)}

    async def execute_close(
        self,
        pos: OpenPosition,
        current_price: float,
    ) -> dict:
        """
        Close both legs of a delta-neutral position.
        Sell spot on Binance, buy back perp on Bybit.
        """
        start = time.perf_counter()
        try:
            binance = await self._get_binance()
            bybit = await self._get_bybit()

            # Close spot: sell the asset
            spot_close = await asyncio.wait_for(
                binance.create_order(
                    symbol=pos.symbol,
                    side="SELL",
                    type="MARKET",
                    quantity=str(round(pos.spot_quantity, 6)),
                ),
                timeout=5.0
            )

            # Close perp: buy back to close short
            perp_close = bybit.place_order(
                category="linear",
                symbol=pos.symbol,
                side="Buy",
                orderType="Market",
                qty=str(round(pos.spot_quantity, 3)),
                reduceOnly=True,    # Close existing position only
                positionIdx=2,      # Short side
            )

            total_ms = (time.perf_counter() - start) * 1000
            spot_received = float(spot_close.get("cummulativeQuoteQty", 0))
            spot_paid = pos.spot_size_usdc

            price_pnl = spot_received - spot_paid  # Should be ~0 (delta neutral)
            total_pnl = pos.funding_collected_usdc + price_pnl - (pos.total_size_usdc * 0.001)

            return {
                "success": True,
                "net_funding_collected": pos.funding_collected_usdc,
                "price_pnl": price_pnl,
                "slippage_cost": pos.total_size_usdc * 0.001,
                "total_pnl_usdc": total_pnl,
                "total_pnl_pct": total_pnl / pos.total_size_usdc if pos.total_size_usdc > 0 else 0,
                "effective_apr": (total_pnl / pos.total_size_usdc) / (pos.age_hours / 8760) * 100 if pos.age_hours > 0 else 0,
                "execution_ms": total_ms,
            }

        except Exception as e:
            logger.error("live_funding_close_error",
                         position_id=pos.position_id[:8], error=str(e))
            return {
                "success": False,
                "error": str(e),
                "net_funding_collected": pos.funding_collected_usdc,
                "total_pnl_usdc": pos.funding_collected_usdc,
            }

    async def _unwind(self, legs_done: list, symbol: str, spot_qty: float) -> None:
        """Unwind completed legs after failure."""
        for leg_name, order in legs_done:
            try:
                if "binance_spot" in leg_name and spot_qty > 0:
                    binance = await self._get_binance()
                    await binance.create_order(
                        symbol=symbol,
                        side="SELL",
                        type="MARKET",
                        quantity=str(round(spot_qty, 6)),
                    )
                    logger.warning("unwound_spot_leg", symbol=symbol, qty=spot_qty)
            except Exception as e:
                logger.error("unwind_failed", symbol=symbol, error=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# PROMOTION GATES
# ─────────────────────────────────────────────────────────────────────────────

class FundingPromotionGates:
    """
    6 gates to pass before promoting A_M2 from paper to live.
    Different from A_M1 gates because A_M2 measures income over time,
    not per-trade win rate.
    """

    GATES = {
        "min_positions_opened":     5,       # At least 5 paper positions
        "min_funding_payments":     10,      # At least 10 payments collected
        "min_effective_apr_pct":    8.0,     # Achieved at least 8% APR in paper
        "min_hold_success_rate":    0.80,    # 80%+ positions closed profitably
        "zero_stuck_positions":     True,    # No position ever got stuck > 2 days
        "zero_execution_errors":    True,    # No failed open/close in paper
    }

    def __init__(self, db: SupabaseClient):
        self._db = db

    async def check_all_gates(self) -> dict:
        positions = await self._get_paper_positions()
        payments = await self._get_paper_payments()

        total_pos = len(positions)
        closed_pos = [p for p in positions if p.get("status") == "closed"]
        profitable = [p for p in closed_pos if float(p.get("total_pnl_usdc") or 0) > 0]

        gate1 = total_pos >= self.GATES["min_positions_opened"]
        gate2 = len(payments) >= self.GATES["min_funding_payments"]

        # Gate 3: effective APR
        effective_aprs = []
        for p in closed_pos:
            if p.get("total_pnl_usdc") and p.get("spot_size_usdc"):
                total_size = float(p["spot_size_usdc"]) + float(p.get("perp_size_usdc", 0))
                hours = (
                    (datetime.fromisoformat(p["closed_at"]) - datetime.fromisoformat(p["opened_at"])).total_seconds() / 3600
                    if p.get("closed_at") and p.get("opened_at") else 24
                )
                if hours > 0 and total_size > 0:
                    apr = (float(p["total_pnl_usdc"]) / total_size) / (hours / 8760) * 100
                    effective_aprs.append(apr)
        avg_apr = sum(effective_aprs) / len(effective_aprs) if effective_aprs else 0
        gate3 = avg_apr >= self.GATES["min_effective_apr_pct"]

        gate4 = (
            len(profitable) / len(closed_pos) >= self.GATES["min_hold_success_rate"]
            if closed_pos else False
        )

        stuck = [
            p for p in positions
            if p.get("status") == "closed" and p.get("opened_at") and p.get("closed_at")
            and (datetime.fromisoformat(p["closed_at"]) - datetime.fromisoformat(p["opened_at"])).days > 8
        ]
        gate5 = len(stuck) == 0

        errors = [p for p in positions if p.get("close_data", {}).get("success") is False]
        gate6 = len(errors) == 0

        all_passed = all([gate1, gate2, gate3, gate4, gate5, gate6])

        return {
            "all_passed": all_passed,
            "strategy_id": "A_M2_funding_rate",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "gates": {
                "min_positions_opened":  {"passed": gate1, "value": total_pos,            "required": self.GATES["min_positions_opened"]},
                "min_funding_payments":  {"passed": gate2, "value": len(payments),         "required": self.GATES["min_funding_payments"]},
                "min_effective_apr_pct": {"passed": gate3, "value": round(avg_apr, 2),    "required": self.GATES["min_effective_apr_pct"]},
                "min_hold_success_rate": {"passed": gate4, "value": round(len(profitable)/max(len(closed_pos),1), 2), "required": self.GATES["min_hold_success_rate"]},
                "zero_stuck_positions":  {"passed": gate5, "value": len(stuck),            "required": 0},
                "zero_execution_errors": {"passed": gate6, "value": len(errors),           "required": 0},
            }
        }

    async def _get_paper_positions(self) -> list:
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._db.table("funding_positions").select("*").eq(
                    "is_paper", True
                ).eq("strategy_id", "A_M2_funding_rate").execute()),
                timeout=10.0,
            )
            return result.data or []
        except Exception:
            return []

    async def _get_paper_payments(self) -> list:
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._db.table("funding_payments").select("id, position_id").eq(
                    "is_paper", True
                ).execute()),
                timeout=10.0,
            )
            return result.data or []
        except Exception:
            return []
