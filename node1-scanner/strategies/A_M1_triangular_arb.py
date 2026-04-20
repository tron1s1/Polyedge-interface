"""
A_M1_triangular_arb.py - v2 Dynamic Triangular Arbitrage Strategy
==================================================================

v2 FEATURE OVERVIEW:
- Dynamically discovers ALL triangular arbitrage opportunities on Binance (2,000+ triangles)
- Fetches real-time bid/ask prices via Binance BookTicker WebSocket (!bookTicker stream)
- Paper trades (simulates) all discovered triangles with realistic latency & price drift
- Configuration driven from cache/Supabase (min_net_profit_pct, fee_per_leg_pct, etc.)
- Kelly criterion for position sizing
- Executes sequentially (BUY leg1 → SELL leg2 → BUY leg3 or similar) within <500ms

KEY DIFFERENCES FROM v1:
- No hardcoded TRIANGLE_SETS. Graph-based discovery enumerates all valid 3-hop cycles.
- No estimated bid/ask fallback. Real Binance BookTicker WebSocket only.
- No separate ingestion module. WebSocket runs inside strategy startup().
- Paper simulator models realistic latency (3–8ms per leg) + price drift.
- Pre-computed triangle list checked every price tick (~2k triangles in <100ms).

ARCHITECTURE:
1. startup() → builds pair graph → discovers triangles → starts BookTicker WebSocket
2. on_market_signal() → refreshes graph if stale → scans all triangles → sizes via Kelly
3. execute_signal() → simulates trade → logs to Supabase
4. Background loops handle WebSocket reconnects and cache TTL

ASSUMPTIONS:
- All 3 legs on Binance only (single-exchange atomic execution)
- Trading pair list refreshed every 6 hours (to catch new pairs and delisting)
- Paper simulator is 95% accurate for backtesting
- No slippage from unfilled orders (all Binance pairs are highly liquid)
- One TriangleScanner thread for all triangles (no sharding)

TODO (Part 2):
- LiveExecutionEngine: place 3-leg orders on actual Binance account
- Add execution gates (manual approval, regime-based, etc.)
- Dashboard UI for dynamic triangle selection
- Post-trade result analysis (fill price vs. expected, slippage metrics)
"""

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime, timezone
import structlog
import httpx

from latency.base_methods import TieredCache, AsyncEventBus
from database.supabase_client import SupabaseClient
from core.kill_switch_bus import KillSwitchBus
from strategies.base_strategy import BaseStrategy, TradeDecision
from ingestion.market_normalizer import UnifiedMarket
from core.india_tax_engine import IndiaTaxEngine

# Live execution subsystem — lazy-imported inside startup so paper-only runs
# don't pull the websockets dependency path just to scan.
try:
    from execution import (
        BinanceWSTrader,
        BoundedParallelExecutor,
        HedgeEngine,
        LatencyCircuitBreaker,
        LiveTestState,
    )
    _EXECUTION_AVAILABLE = True
except Exception as _exec_imp_err:  # pragma: no cover
    _EXECUTION_AVAILABLE = False

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "min_net_profit_pct": 0.02,           # Floor; per-triangle threshold usually overrides
    "min_gross_gap_pct": 0.25,            # Gross gap before fees; 3×0.075% + 0.02% net
    "fee_per_leg_pct": 0.075,             # Binance spot 0.10% × 0.75 BNB discount = 0.075%
    "min_volume_24h_usdc": 100_000,        # 20× raise: eliminates WAL/ARS/ZEC (<$20k/day) while keeping PLN/EUR/BRL
    "base_currencies": ["USDT", "USDC", "BTC", "ETH", "BNB", "FDUSD", "EUR", "BRL"],
    "max_triangles_to_check": 8_000,      # More triangles with USDC + BNB as full bases
    # ── Adaptive hot-set scanning (v2) ─────────────────────────────────────
    # Most scans check only the top-N triangles ranked by observed-edge score.
    # Every full_sweep_every scans, we re-check ALL triangles so new winners
    # surface and stale ones cool off. With 10 scans/sec and full_sweep_every=10,
    # every triangle is evaluated at least once per second — we cannot miss
    # opportunities that last longer than ~1s (and sub-second edges on cold
    # triangles will usually still be caught on the full sweep tick).
    "hot_top_n": 1_000,                    # Triangles scanned every tick
    "full_sweep_every": 10,                # Every Nth scan = full sweep of all
    "hot_score_decay": 0.995,              # Decay factor applied each full sweep

    # ── Approach D: bounded-tolerance execution (v3) ───────────────────────
    # Each leg is classified by pair stability. Worst-case per-leg slippage
    # (unfavorable side) combined with fees determines the required scanner
    # edge for a given triangle to be live-safe:
    #
    #   required_edge = sum(leg_tolerance) + safety_margin
    #
    # The scanner only signals triangles whose observed net edge exceeds
    # this triangle-specific threshold, not a global one. This is the core
    # of the "wins can be small, losses cannot exceed zero" promise.
    "use_per_triangle_threshold": True,
    "leg_tolerance_bps": {
        "stable": 1.5,     # USDT/USDC/FDUSD pairs — books are tight
        "major":  5.0,     # BTC/ETH/BNB/SOL/XRP/DOGE — liquid, small drift
        "midcap": 7.0,     # All other altcoins meeting min_volume
    },
    "safety_margin_bps": 0.5,              # Low buffer; dashboard can override to 0 for testing
    # Simulated-latency paper mode: re-read L1 cache at "fill moment" after
    # an injected delay, so paper slippage tracks what live would see.
    "paper_simulate_latency": True,
    "paper_leg_latency_ms": {
        "leg1": 4.0,
        "leg2": 4.5,
        "leg3": 4.0,
    },
    # ── Fix 3: stale-feed guard ────────────────────────────────────────────
    # BookTicker writes L1 entries with TTL=30s so an illiquid pair that only
    # ticks once every 5s still contributes. That's fine for price reference,
    # but when a triangle's edge depends on stale quotes we're scanning a
    # fantasy book — the 4.19% "edges" we saw were exactly this.
    # This guard rejects any signal where ANY leg's L1 entry was written more
    # than max_feed_age_ms ago. 500ms = one full scan cycle of slack.
    "max_feed_age_ms": 500,
    # ── Fix 2: synthetic slippage (paper sim realism) ──────────────────────
    # On top of L1 re-read at fill moment, paper sim adds a per-class random
    # penalty drawn from a truncated distribution to model the book-walk /
    # queue-position effects that won't show up in L1 top-of-book alone.
    # Units: basis points added to the UNFAVORABLE side of the fill.
    "synthetic_slippage_bps": {
        "stable": {"mean": 0.0, "stdev": 0.5, "max": 2.0},
        "major":  {"mean": 1.0, "stdev": 2.0, "max": 8.0},
        "midcap": {"mean": 3.0, "stdev": 5.0, "max": 20.0},
    },
    # Deterministic random seed for reproducible paper runs. Set to None for
    # real randomness in long-running paper mode.
    "synthetic_slippage_seed": None,
    # ── Fix 1: book-depth simulation ───────────────────────────────────────
    # Subscribe to <sym>@depth5@100ms for the hot-triangle symbol set and
    # compute paper fills as the VWAP across levels for the actual trade
    # size. Captures book-walk slippage that L1 alone cannot show.
    "enable_depth_feed": True,
    "paper_use_book_walk": True,
    "depth_max_symbols": 300,         # Cap on simultaneous depth subscriptions
    "depth_refresh_interval_s": 30.0, # How often the hot-symbol set is re-diffed
    # ── Latency circuit breaker ────────────────────────────────────────────
    # Trip: 30-sample p95 exceeds this → live/dry-run orders refused until
    # p95 drops back below reset threshold for N consecutive samples.
    "latency_breaker_trip_ms": 80.0,       # Raised: survives WS connection warmup (first few orders ~70-90ms)
    "latency_breaker_reset_ms": 50.0,      # Raised proportionally
    # ── Cross-margin (FUTURE, disabled) ────────────────────────────────────
    # Binance Spot supports 3x cross-margin. On a USDT→BTC→ETH→USDT triangle
    # this is effectively free leverage IF the triangle graph permits borrow
    # on all three symbols. Requires separate /margin/isolated endpoints and
    # borrow-rate accounting that exceeds the scope of the paper/live-test
    # layer. When enabled, the executor will treat this flag as "route to
    # margin API" with a hard-coded 3x cap. Kept off until the broader
    # portfolio layer supports per-asset margin position tracking.
    "enable_spot_cross_margin": False,
    "spot_cross_margin_max_leverage": 3.0,
    "max_trade_size_usdc": 5_000.0,       # Kelly: don't risk more than portfolio
    "min_trade_size_usdc": 50.0,          # Too small: fees kill profit
    "max_concurrent_trades": 3,           # Paper limit
    "graph_refresh_hours": 6,             # Rebuild pair list every N hours
    # Currencies excluded from the arb graph — either wide bid-ask spreads (fiat)
    # or deprecated/illiquid stablecoins whose mid-price creates false signals.
    # EUR/BRL/MXN/PLN have tighter spreads and are intentionally NOT excluded.
    "excluded_fiat_currencies": [
        # Not available on user's Binance
        "IDR", "VND", "NGN", "RON", "TRY", "GBP", "PKR", "EGP", "PEN",
        # Deprecated/illiquid stablecoins — off-peg pricing is a false signal
        "TUSD", "BUSD", "USDP", "USDD", "GUSD", "USDJ",
        # ARS: hyperinflationary, extreme bid-ask, never fills — excluded after analysis
        "ARS",
        # INCLUDED (available on user's Binance):
        # EUR, BRL, MXN, PLN, COP, ZAR, UAH, USD, EURI
    ],
}


# ─────────────────────────────────────────────────────────────────────────
# MODULE CONSTANTS
# ─────────────────────────────────────────────────────────────────────────

# Must match BookTickerFeed expiry (see _route_bookticker_message). If this
# changes, the stale-feed guard in DynamicTriangleScanner._scan_once will
# silently compute wrong ages.
BOOKTICKER_TTL_S: float = 30.0


# ─────────────────────────────────────────────────────────────────────────
# CURRENCY CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────

# Stability class drives per-leg slippage tolerance. The enum values are
# used to look up leg_tolerance_bps in config.
STABLE_CURRENCIES: Set[str] = {
    "USDT", "USDC", "FDUSD", "DAI", "USD",
    # EUR/BRL/etc are NOT "stable" — they're fiat with wide spreads.
    # They stay in midcap class (or are excluded via excluded_fiat).
}

MAJOR_CURRENCIES: Set[str] = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "TRX",
    "DOT", "LINK", "MATIC", "LTC", "BCH",
}

def classify_currency(sym: str) -> str:
    """Return one of: 'stable', 'major', 'midcap'."""
    if sym in STABLE_CURRENCIES:
        return "stable"
    if sym in MAJOR_CURRENCIES:
        return "major"
    return "midcap"

def classify_leg(base: str, quote: str) -> str:
    """The leg takes the LOWER-stability class of its two currencies.
    A USDT/BTC leg is 'major' (not 'stable') because BTC can move between
    scanner-see and order-fill. A BTC/CTK leg is 'midcap' because CTK drives
    the variance."""
    cb = classify_currency(base)
    cq = classify_currency(quote)
    order = {"stable": 0, "major": 1, "midcap": 2}
    return cb if order[cb] >= order[cq] else cq


# ─────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class BinancePair:
    """One trading pair from Binance exchangeInfo."""
    symbol: str                           # e.g. "SOLUSDT"
    base: str                             # e.g. "SOL"
    quote: str                            # e.g. "USDT"
    volume_24h: float                     # e.g. 1_200_000.0
    min_qty: float                        # Minimum order amount
    step_size: float                      # Lot size (e.g. 0.01 for BTC)

    def __hash__(self):
        return hash(self.symbol)

    def __eq__(self, other):
        return isinstance(other, BinancePair) and self.symbol == other.symbol


@dataclass
class Triangle:
    """One discovered triangular arbitrage cycle."""
    triangle_id: str                      # e.g. "USDT_SOL_ETH_USDT_0"
    start_currency: str                   # e.g. "USDT"
    currencies: Tuple[str, str, str]      # e.g. ("USDT", "SOL", "ETH")

    leg1_symbol: str                      # e.g. "SOLUSDT"
    leg1_side: str                        # "BUY" or "SELL"
    leg1_key: str                         # e.g. "ask:binance:SOLUSDT"

    leg2_symbol: str
    leg2_side: str
    leg2_key: str

    leg3_symbol: str
    leg3_side: str
    leg3_key: str

    min_volume_24h: float

    # ── Approach D: per-leg tolerance + per-triangle threshold (computed
    # once at discovery, cheap lookup in the hot path) ────────────────────
    leg1_class: str = "midcap"         # 'stable' | 'major' | 'midcap'
    leg2_class: str = "midcap"
    leg3_class: str = "midcap"
    leg1_tolerance_bps: float = 7.0    # Max unfavorable slippage we'll accept on leg 1
    leg2_tolerance_bps: float = 7.0
    leg3_tolerance_bps: float = 7.0
    required_edge_pct: float = 0.25    # Scanner threshold: observed net_pct must exceed this

    def description(self) -> str:
        """Human-readable: 'USDT→SOL→ETH→USDT'"""
        return f"{self.currencies[0]}→{self.currencies[1]}→{self.currencies[2]}→{self.currencies[0]}"


@dataclass
class TriangleOpportunity:
    """One detected profitable opportunity."""
    triangle: Triangle
    gross_profit_pct: float               # Gross gap %
    net_profit_pct: float                 # After fees
    fee_cost_pct: float                   # Total fee % (3 × fee_per_leg)

    trade_size_usdc: float                # Kelly-sized position
    expected_profit_usdc: float           # trade_size × net_profit_pct / 100

    leg1_price: float
    leg2_price: float
    leg3_price: float

    detected_at_ns: int = field(default_factory=lambda: time.monotonic_ns())

    @property
    def age_ms(self) -> float:
        """How old this opportunity is in milliseconds."""
        return (time.monotonic_ns() - self.detected_at_ns) / 1_000_000

    @property
    def is_stale(self) -> bool:
        """True if > 500ms old (likely filled by now)."""
        return self.age_ms > 500


@dataclass
class TradeResult:
    """Paper trade execution result."""
    triangle_id: str
    success: bool                         # Did all 3 legs execute?
    net_profit_usdc: float                # Realized profit or loss
    net_profit_pct: float

    execution_ms: float                   # Total time for 3 legs
    fill_prices: Dict[str, float]         # Leg symbol → ACTUAL fill price

    trade_size_usdc: float = 0.0          # Capital deployed for this trade
    is_paper: bool = True                 # Always True in v2 (Part 2 adds live)
    error: Optional[str] = None           # Error message if success=False

    # ── Approach D rich execution schema ────────────────────────────────
    # These fields are populated by the v3 paper/live executors. Consumers
    # (dashboard, promotion gates) should prefer actual_* over legacy
    # net_profit_*. Legacy fields are retained for backward compat.
    execution_mode: str = "paper_instant"            # paper_instant | paper_sim_latency | live_bounded_parallel
    scanner_prices: Dict[str, float] = field(default_factory=dict)
    actual_fill_prices: Dict[str, float] = field(default_factory=dict)
    per_leg_slippage_bps: Dict[str, float] = field(default_factory=dict)
    per_leg_latency_ms: Dict[str, float] = field(default_factory=dict)
    per_leg_status: Dict[str, str] = field(default_factory=dict)        # FILLED | CANCELED | REJECTED
    expected_net_pct: float = 0.0
    actual_net_pct: float = 0.0
    required_edge_pct: float = 0.0
    expected_pnl_usdc: float = 0.0
    fees_paid_usdc: float = 0.0
    edge_lost_to_slippage_pct: float = 0.0
    outcome_status: str = "UNKNOWN"                  # COMPLETE | PARTIAL_HEDGED | NO_FILL | ABORTED | FAILED
    latency_classification: str = "unknown"          # fast (<10ms) | normal (<20ms) | slow (<40ms) | timeout


# ─────────────────────────────────────────────────────────────────────────
# PAIR GRAPH BUILDER
# ─────────────────────────────────────────────────────────────────────────

class PairGraphBuilder:
    """
    Builds adjacency graph of all Binance trading pairs.
    Fetches from /api/v3/exchangeInfo + /api/v3/ticker/24hr.
    """

    def __init__(
        self,
        cache: TieredCache,
        min_volume_usdc: float = 100_000,
        excluded_fiat: set = None,
    ):
        self.cache = cache
        self.min_volume_usdc = min_volume_usdc
        # Wide-spread fiat currencies whose mid-price profits are illusory in live trading.
        # Can be overridden via config "excluded_fiat_currencies".
        self.excluded_fiat: set = excluded_fiat or {
            "IDR", "VND", "NGN", "RON", "TRY", "GBP", "PKR", "EGP", "PEN",
            "TUSD", "BUSD", "USDP", "USDD", "GUSD", "USDJ",
        }
        self._last_refresh_ns = 0
        self._refresh_interval_ns = 6 * 3600 * 1_000_000_000  # 6 hours

        # Adjacency list: adj[base][quote] = BinancePair
        # Both directions for each pair (quote→base as BUY, base→quote as SELL)
        self.adj: Dict[str, Dict[str, BinancePair]] = {}
        self.all_pairs: Dict[str, BinancePair] = {}

    def needs_refresh(self) -> bool:
        """True if graph is stale (older than 6 hours)."""
        return (time.monotonic_ns() - self._last_refresh_ns) > self._refresh_interval_ns

    async def build(self) -> int:
        """
        Fetch ALL Binance pairs, filter by volume, build adjacency.
        Returns: count of pairs added.
        """
        try:
            logger.info("pair_graph_building_start")

            # Fetch all trading pairs
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get exchange info (symbols, min_qty, step_size)
                info_resp = await client.get(
                    "https://api.binance.com/api/v3/exchangeInfo",
                    params={"permissions": "SPOT"}
                )
                info_resp.raise_for_status()
                info_data = info_resp.json()

                # Get 24h volume
                ticker_resp = await client.get(
                    "https://api.binance.com/api/v3/ticker/24hr"
                )
                ticker_resp.raise_for_status()
                ticker_data = ticker_resp.json()

            # Index 24h volumes and prices by symbol
            # quoteVolume = 24h volume in quote asset
            # lastPrice = current price
            volumes = {}
            prices = {}
            for t in ticker_data:
                volumes[t["symbol"]] = float(t.get("quoteVolume", 0))
                prices[t["symbol"]] = float(t.get("lastPrice", 0))

            # Build quote→USDT conversion rates for volume estimation
            # e.g. BTCUSDT price = 83000, so 1 BTC of volume = 83000 USDC
            quote_to_usdt = {"USDT": 1.0, "USDC": 1.0, "BUSD": 1.0, "USD": 1.0}
            for sym in ("BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "FDUSD",
                        "EUR", "BRL", "MXN", "ARS", "PLN", "COP", "ZAR", "UAH", "EURI"):
                usdt_pair = f"{sym}USDT"
                if usdt_pair in prices and prices[usdt_pair] > 0:
                    quote_to_usdt[sym] = prices[usdt_pair]
                else:
                    usdc_pair = f"{sym}USDC"
                    if usdc_pair in prices and prices[usdc_pair] > 0:
                        quote_to_usdt[sym] = prices[usdc_pair]

            # Build pair graph
            self.adj = {}
            self.all_pairs = {}

            for symbol_info in info_data.get("symbols", []):
                if symbol_info["status"] != "TRADING":
                    continue

                symbol = symbol_info["symbol"]
                base = symbol_info["baseAsset"]
                quote = symbol_info["quoteAsset"]

                # Get volume in quote asset and convert to USDC equivalent
                volume_quote = volumes.get(symbol, 0.0)
                usdt_rate = quote_to_usdt.get(quote, 0.0)
                if usdt_rate > 0:
                    volume_24h = volume_quote * usdt_rate
                else:
                    # Unknown quote — use raw volume as rough estimate
                    volume_24h = volume_quote

                # Skip if volume too low (now correctly in USDC terms)
                if volume_24h < self.min_volume_usdc:
                    continue

                # Skip pairs involving wide-spread fiat currencies.
                # These look profitable on mid-price but real bid-ask spreads
                # (often 1-5% on thin fiat pairs) eliminate any edge entirely.
                if base in self.excluded_fiat or quote in self.excluded_fiat:
                    continue

                # Extract min_qty and step_size from filters
                min_qty, step_size = 1.0, 1.0
                for filt in symbol_info.get("filters", []):
                    if filt["filterType"] == "LOT_SIZE":
                        min_qty = float(filt.get("minQty", 1))
                        step_size = float(filt.get("stepSize", 1))
                        break

                pair = BinancePair(
                    symbol=symbol,
                    base=base,
                    quote=quote,
                    volume_24h=volume_24h,
                    min_qty=min_qty,
                    step_size=step_size,
                )

                self.all_pairs[symbol] = pair

                # Add both directions to adjacency
                if quote not in self.adj:
                    self.adj[quote] = {}
                if base not in self.adj:
                    self.adj[base] = {}

                self.adj[quote][base] = pair         # SELL base for quote
                self.adj[base][quote] = pair         # BUY quote with base

            self._last_refresh_ns = time.monotonic_ns()
            pair_count = len(self.all_pairs)
            logger.info("pair_graph_built", pairs=pair_count, edges=len(self.adj))
            return pair_count

        except Exception as e:
            logger.error("pair_graph_build_error", error=str(e))
            raise


# ─────────────────────────────────────────────────────────────────────────
# TRIANGLE DISCOVERER
# ─────────────────────────────────────────────────────────────────────────

class TriangleDiscoverer:
    """
    Enumerates all valid 3-hop cycles in pair graph.
    Uses DFS from base currencies to find triangles.
    """

    def __init__(self, graph_builder: PairGraphBuilder, base_currencies: List[str], config: Optional[Dict] = None):
        self.graph = graph_builder
        self.base_currencies = base_currencies
        self.triangles: List[Triangle] = []
        self.config = config or {}
        # Pre-compute tolerance lookup + fee/safety so _build_triangle is cheap
        tol = self.config.get("leg_tolerance_bps", {"stable": 1.5, "major": 5.0, "midcap": 7.0})
        self._tol_bps = {
            "stable": float(tol.get("stable", 1.5)),
            "major":  float(tol.get("major", 5.0)),
            "midcap": float(tol.get("midcap", 7.0)),
        }
        self._safety_bps = float(self.config.get("safety_margin_bps", 3.0))
        # Note: fees are ALREADY deducted inside _check_triangle's amount math,
        # so required_edge_pct is purely slippage budget + safety margin.
        # It does NOT need to include fees on top.

    def discover_all(self) -> List[Triangle]:
        """
        Find all triangles starting from each base currency in BOTH directions.

        For a 3-currency set {A, B, C}, there are 6 ordered walks:
            A->B->C->A   A->C->B->A
            B->A->C->B   B->C->A->B
            C->A->B->C   C->B->A->C
        These are NOT equivalent: each direction has different BUY/SELL legs
        and therefore different net edge after fees/slippage (one direction
        can be profitable while the reverse is negative). We MUST evaluate
        all of them.

        Dedup is done only on the exact ordered walk (start, mid_a, mid_b)
        so we never insert the identical walk twice (which cannot happen
        from a single start in a simple graph, but we keep the guard for safety).
        """
        seen = set()  # Track by ordered (start, mid_a, mid_b) — direction-preserving
        triangles = []

        for start_curr in self.base_currencies:
            if start_curr not in self.graph.adj:
                continue

            # DFS: start_curr → mid_a → mid_b → start_curr
            for mid_a, pair_1 in self.graph.adj[start_curr].items():
                if mid_a == start_curr:
                    continue
                if mid_a not in self.graph.adj:
                    continue

                for mid_b, pair_2 in self.graph.adj[mid_a].items():
                    if mid_b not in self.graph.adj or mid_b == start_curr or mid_b == mid_a:
                        continue

                    # Check if mid_b can reach back to start_curr
                    if start_curr not in self.graph.adj.get(mid_b, {}):
                        continue

                    pair_3 = self.graph.adj[mid_b][start_curr]

                    # Direction-preserving dedup: keep both A->B->C and A->C->B,
                    # and keep same triple from different starts (B->A->C etc.)
                    sig = (start_curr, mid_a, mid_b)
                    if sig in seen:
                        continue
                    seen.add(sig)

                    # Build triangle with correct BUY/SELL for each leg
                    triangle = self._build_triangle(start_curr, mid_a, mid_b, pair_1, pair_2, pair_3)
                    triangles.append(triangle)

        self.triangles = triangles
        logger.info("triangles_discovered", count=len(triangles))
        return triangles

    def _build_triangle(
        self,
        start: str,
        mid_a: str,
        mid_b: str,
        pair_1: BinancePair,
        pair_2: BinancePair,
        pair_3: BinancePair,
    ) -> Triangle:
        """
        Determine BUY/SELL direction for each leg.
        start → mid_a: BUY mid_a with start (spend start, receive mid_a)
        mid_a → mid_b: SELL mid_a for mid_b (spend mid_a, receive mid_b)
        mid_b → start: SELL mid_b for start (spend mid_b, receive start)
        """
        # Leg 1: start → mid_a (BUY mid_a)
        if pair_1.base == mid_a:
            # Pair is mid_a/start, BUY side
            leg1_symbol = pair_1.symbol
            leg1_side = "BUY"
            leg1_key = f"ask:binance:{leg1_symbol}"
        else:
            # Pair is start/mid_a, SELL side (confusing—shouldn't happen)
            leg1_symbol = pair_1.symbol
            leg1_side = "SELL"
            leg1_key = f"bid:binance:{leg1_symbol}"

        # Leg 2: mid_a → mid_b (we have mid_a, want mid_b)
        if pair_2.quote == mid_a:
            # Pair is mid_b/mid_a (e.g. ETHBTC: base=ETH=mid_b, quote=BTC=mid_a)
            # We spend mid_a (quote) to BUY mid_b (base) → pay ask
            leg2_symbol = pair_2.symbol
            leg2_side = "BUY"
            leg2_key = f"ask:binance:{leg2_symbol}"
        else:
            # Pair is mid_a/mid_b (e.g. BTCETH: base=BTC=mid_a, quote=ETH=mid_b)
            # We SELL mid_a (base) to get mid_b (quote) → receive bid
            leg2_symbol = pair_2.symbol
            leg2_side = "SELL"
            leg2_key = f"bid:binance:{leg2_symbol}"

        # Leg 3: mid_b → start (we have mid_b, want start)
        if pair_3.quote == mid_b:
            # Pair is start/mid_b (e.g. USDTETH: base=USDT=start, quote=ETH=mid_b)
            # We spend mid_b (quote) to BUY start (base) → pay ask
            leg3_symbol = pair_3.symbol
            leg3_side = "BUY"
            leg3_key = f"ask:binance:{leg3_symbol}"
        else:
            # Pair is mid_b/start (e.g. ETHUSDT: base=ETH=mid_b, quote=USDT=start)
            # We SELL mid_b (base) to get start (quote) → receive bid
            leg3_symbol = pair_3.symbol
            leg3_side = "SELL"
            leg3_key = f"bid:binance:{leg3_symbol}"

        triangle_id = f"{start}_{mid_a}_{mid_b}_{start}_{len(self.triangles)}"

        # ── Per-leg stability class & tolerance (Approach D) ────────────
        # Leg 1 bridges (start, mid_a). Leg 2 bridges (mid_a, mid_b).
        # Leg 3 bridges (mid_b, start). The leg class = LOWER stability of
        # its two endpoints.
        leg1_class = classify_leg(start, mid_a)
        leg2_class = classify_leg(mid_a, mid_b)
        leg3_class = classify_leg(mid_b, start)
        tol1 = self._tol_bps[leg1_class]
        tol2 = self._tol_bps[leg2_class]
        tol3 = self._tol_bps[leg3_class]
        # Required edge (in %) = combined per-leg tolerance + safety margin.
        # 1 bps = 0.01%, so divide bps by 100 to get percent.
        required_edge_pct = (tol1 + tol2 + tol3 + self._safety_bps) / 100.0

        return Triangle(
            triangle_id=triangle_id,
            start_currency=start,
            currencies=(start, mid_a, mid_b),
            leg1_symbol=leg1_symbol,
            leg1_side=leg1_side,
            leg1_key=leg1_key,
            leg2_symbol=leg2_symbol,
            leg2_side=leg2_side,
            leg2_key=leg2_key,
            leg3_symbol=leg3_symbol,
            leg3_side=leg3_side,
            leg3_key=leg3_key,
            min_volume_24h=min(pair_1.volume_24h, pair_2.volume_24h, pair_3.volume_24h),
            leg1_class=leg1_class,
            leg2_class=leg2_class,
            leg3_class=leg3_class,
            leg1_tolerance_bps=tol1,
            leg2_tolerance_bps=tol2,
            leg3_tolerance_bps=tol3,
            required_edge_pct=required_edge_pct,
        )


# ─────────────────────────────────────────────────────────────────────────
# DYNAMIC TRIANGLE SCANNER
# ─────────────────────────────────────────────────────────────────────────

class DynamicTriangleScanner:
    """
    Checks pre-computed list of triangles against real-time prices.
    Runs in parallel via asyncio.gather for speed.
    """

    def __init__(self, triangles: List[Triangle], cache: TieredCache, config: Dict):
        self.triangles = triangles
        self.cache = cache
        self.config = config
        # Diagnostic: track best profit seen across ALL triangles (even negative)
        self._last_scan_best_pct: float = -999.0
        self._last_scan_best_tri: str = ""
        self._last_scan_checked: int = 0
        # Fix 3: stale-feed rejections per scan — telemetry for tuning
        # max_feed_age_ms. If this counter balloons, either feeds are slow or
        # the guard is too strict.
        self._last_scan_stale_rejected: int = 0
        self._total_stale_rejected: int = 0

        # ── Adaptive hot-set state ────────────────────────────────────────
        # Per-triangle "edge score" = EMA of observed |net_pct|. Triangles that
        # repeatedly show large edges (positive OR large negative — large-spread
        # triangles tend to flip sign) get ranked highest.
        self._triangle_score: Dict[str, float] = {}
        self._hot_cache: List[Triangle] = []  # Rebuilt on each full sweep
        self._scan_counter: int = 0
        # Last full-sweep "best triangle across ALL" for the diagnostic heartbeat.
        # Hot-only scans don't update this to avoid misleading the dashboard.
        self._last_full_sweep_best_pct: float = -999.0
        self._last_full_sweep_best_tri: str = ""

    async def find_best_opportunity(self) -> Optional[TriangleOpportunity]:
        """Find single best opportunity. Delegates to the sync fast path —
        _check_triangle contains zero awaits, so running 4000+ coroutines
        through asyncio.gather was pure scheduling overhead. This sync loop
        completes in <1ms for the hot-set and ~3-5ms for a full sweep."""
        return self._find_best_sync(min_profit_pct=0.0)

    async def find_all_opportunities(self, min_profit_pct: float = 0.08) -> List[TriangleOpportunity]:
        """Return all profitable opportunities (sorted desc). Still supported
        for callers that need the full list (e.g. logging/diagnostics); uses
        the same sync inner loop, no asyncio.gather."""
        return self._find_all_sync(min_profit_pct=min_profit_pct)

    # ── sync fast path ──────────────────────────────────────────────────

    def _select_candidates(self) -> Tuple[List[Triangle], bool]:
        """Pick which triangles to scan this tick.
        Returns (candidates, is_full_sweep)."""
        full_every = max(1, int(self.config.get("full_sweep_every", 10)))
        hot_n = int(self.config.get("hot_top_n", 1_000))
        cap = self.config.get("max_triangles_to_check", 8_000)
        all_tris = self.triangles[:cap]

        self._scan_counter += 1
        # Full sweep on first scan, on scan_counter % N == 0, or whenever hot cache is empty
        is_full = (
            not self._hot_cache
            or (self._scan_counter % full_every) == 0
            or hot_n >= len(all_tris)   # hot set covers everything → no point pruning
        )
        if is_full:
            return all_tris, True
        return self._hot_cache, False

    def _rebuild_hot_cache(self, hot_n: int) -> None:
        """Rank triangles by edge score, take top-N as the hot set."""
        decay = float(self.config.get("hot_score_decay", 0.995))
        # Decay all scores on full sweep so a triangle that was hot once
        # but never fires again eventually falls out of the hot set.
        if decay < 1.0 and self._triangle_score:
            for k in list(self._triangle_score.keys()):
                self._triangle_score[k] *= decay
        ranked = sorted(
            self.triangles,
            key=lambda t: self._triangle_score.get(t.triangle_id, 0.0),
            reverse=True,
        )
        self._hot_cache = ranked[:hot_n]

    def _scan_once(self, candidates: List[Triangle], is_full: bool) -> List[TriangleOpportunity]:
        """Single synchronous pass over the chosen candidates.
        Writes observed edges into self._triangle_score so the hot-set learns
        over time — this happens on BOTH hot and full sweeps, so a triangle
        that shows unexpected edge on a full sweep gets promoted to hot
        immediately on the next rebuild.
        """
        now = time.monotonic()
        l1 = self.cache._L1
        fee_per_leg = self.config.get("fee_per_leg_pct", 0.10) / 100.0
        fee_mult = 1.0 - fee_per_leg
        fee_cost_pct = 3 * self.config.get("fee_per_leg_pct", 0.10)
        global_min_profit = self.config.get("min_net_profit_pct", 0.08)
        use_per_tri = self.config.get("use_per_triangle_threshold", True)

        # ── Fix 3: stale-feed guard ─────────────────────────────────────────
        # L1 entries are (value, expiry_monotonic) with expiry = write_ts + TTL.
        # Age now = TTL - (expiry - now). Reject the triangle if ANY leg's entry
        # is older than max_feed_age_ms. We precompute the cutoff so the hot
        # path does one subtraction per leg instead of two.
        # stale_cutoff = TTL - max_age_s : if (expiry - now) < stale_cutoff,
        # the entry age exceeds max_age_s.
        max_feed_age_s = max(0.0, self.config.get("max_feed_age_ms", 500) / 1000.0)
        stale_cutoff = BOOKTICKER_TTL_S - max_feed_age_s  # e.g., 30 - 0.5 = 29.5

        opportunities: List[TriangleOpportunity] = []
        checked = 0
        stale_rejected = 0
        best_pct = -999.0
        best_tri_id = ""
        score = self._triangle_score

        for tri in candidates:
            e1 = l1.get(tri.leg1_key)
            if not e1: continue
            e2 = l1.get(tri.leg2_key)
            if not e2: continue
            e3 = l1.get(tri.leg3_key)
            if not e3: continue
            # Expiry check (cache lifetime guard — catches >TTL old)
            if e1[1] < now or e2[1] < now or e3[1] < now:
                continue
            # Stale-feed guard (Fix 3) — any leg older than max_feed_age_ms
            # means we're pricing against a feed that's no longer reflective
            # of the live book. Reject before scoring.
            e1_remaining = e1[1] - now
            e2_remaining = e2[1] - now
            e3_remaining = e3[1] - now
            if (e1_remaining < stale_cutoff
                    or e2_remaining < stale_cutoff
                    or e3_remaining < stale_cutoff):
                stale_rejected += 1
                continue

            p1 = e1[0]; p2 = e2[0]; p3 = e3[0]
            if not (p1 and p2 and p3):
                continue

            amount = 1.0
            if tri.leg1_side == "BUY": amount = amount / p1 * fee_mult
            else:                      amount = amount * p1 * fee_mult
            if tri.leg2_side == "BUY": amount = amount / p2 * fee_mult
            else:                      amount = amount * p2 * fee_mult
            if tri.leg3_side == "BUY": amount = amount / p3 * fee_mult
            else:                      amount = amount * p3 * fee_mult

            net_pct = (amount - 1.0) * 100.0
            checked += 1

            # Update edge score — EMA of absolute edge (captures both profitable
            # and "close to profitable" triangles so they stay in the hot set).
            abs_edge = net_pct if net_pct >= 0 else -net_pct
            prev = score.get(tri.triangle_id)
            if prev is None:
                score[tri.triangle_id] = abs_edge
            elif abs_edge > prev:
                # New peak → jump to it immediately
                score[tri.triangle_id] = abs_edge
            else:
                # Slow EMA toward the new value so scores decay on quiet triangles
                score[tri.triangle_id] = prev * 0.9 + abs_edge * 0.1

            if net_pct > best_pct:
                best_pct = net_pct
                best_tri_id = tri.triangle_id

            # Per-triangle threshold: the triangle carries its own
            # required_edge_pct derived from per-leg slippage tolerance.
            # A USDT→USDC→BTC triangle needs ~0.095%; a midcap-heavy triangle
            # needs ~0.22%+. Floor at global min_net_profit_pct for safety.
            if use_per_tri:
                required = tri.required_edge_pct
                if global_min_profit > required:
                    required = global_min_profit
            else:
                required = global_min_profit

            if net_pct >= required:
                size = self._kelly_size(net_pct)
                opportunities.append(TriangleOpportunity(
                    triangle=tri,
                    gross_profit_pct=net_pct + fee_cost_pct,
                    net_profit_pct=net_pct,
                    fee_cost_pct=fee_cost_pct,
                    trade_size_usdc=size,
                    expected_profit_usdc=size * (net_pct / 100.0),
                    leg1_price=p1, leg2_price=p2, leg3_price=p3,
                ))

        # Diagnostics — rolling "best across whatever was checked this scan"
        self._last_scan_checked = checked
        self._last_scan_stale_rejected = stale_rejected
        self._total_stale_rejected += stale_rejected
        if best_pct > self._last_scan_best_pct:
            self._last_scan_best_pct = best_pct
            self._last_scan_best_tri = best_tri_id
        if is_full:
            self._last_full_sweep_best_pct = best_pct
            self._last_full_sweep_best_tri = best_tri_id

        return opportunities

    def _find_best_sync(self, min_profit_pct: float = 0.0) -> Optional[TriangleOpportunity]:
        candidates, is_full = self._select_candidates()
        opps = self._scan_once(candidates, is_full)
        if is_full:
            hot_n = int(self.config.get("hot_top_n", 1_000))
            self._rebuild_hot_cache(hot_n)
        if not opps:
            return None
        # Return best — faster than sorting whole list for a single pick
        best = opps[0]
        for o in opps[1:]:
            if o.net_profit_pct > best.net_profit_pct:
                best = o
        if best.net_profit_pct < min_profit_pct:
            return None
        return best

    def _find_all_sync(self, min_profit_pct: float = 0.08) -> List[TriangleOpportunity]:
        candidates, is_full = self._select_candidates()
        opps = self._scan_once(candidates, is_full)
        if is_full:
            hot_n = int(self.config.get("hot_top_n", 1_000))
            self._rebuild_hot_cache(hot_n)
        filtered = [o for o in opps if o.net_profit_pct >= min_profit_pct]
        filtered.sort(key=lambda x: x.net_profit_pct, reverse=True)
        return filtered

    async def _check_triangle(self, triangle: Triangle) -> Optional[TriangleOpportunity]:
        """
        Check one triangle for profitability.
        Reads 3 prices from L1 cache only (bid/ask keys written directly by BookTickerFeed).
        NEVER falls through to Redis — direct dict access eliminates all connection pressure.
        If a price is not in L1 (not yet received from BookTicker), skip this triangle.
        """
        try:
            # Direct L1 dict access — synchronous, zero Redis traffic.
            # BookTicker writes ask:binance:* and bid:binance:* directly into cache._L1.
            # Any key not in L1 means we have no fresh price for that leg → skip triangle.
            now = time.monotonic()
            l1 = self.cache._L1

            entry_1 = l1.get(triangle.leg1_key)
            entry_2 = l1.get(triangle.leg2_key)
            entry_3 = l1.get(triangle.leg3_key)

            # All three prices must be present AND not expired (TTL = 3s from BookTicker)
            if not entry_1 or not entry_2 or not entry_3:
                return None
            if entry_1[1] < now or entry_2[1] < now or entry_3[1] < now:
                return None

            price_1 = entry_1[0]
            price_2 = entry_2[0]
            price_3 = entry_3[0]

            if not all([price_1, price_2, price_3]):
                return None

            # L1 values are already floats (written as float by BookTicker)
            # Simulate execution: 1 unit of start_currency through 3 legs.
            #
            # For each leg the direction determines the math:
            #   BUY  side → key is ask price. We spend quote to get base:
            #       received_base  = amount_quote / ask_price
            #   SELL side → key is bid price. We spend base to get quote:
            #       received_quote = amount_base  * bid_price
            #
            # The _build_triangle already set the correct key (ask vs bid)
            # for each leg. We just need to apply the right operation.
            fee_per_leg = self.config.get("fee_per_leg_pct", 0.10) / 100.0
            fee_mult = 1.0 - fee_per_leg

            amount = 1.0  # Start with 1 unit of start_currency

            # Leg 1: start → mid_a
            if triangle.leg1_side == "BUY":
                amount = amount / price_1 * fee_mult   # spend quote, get base
            else:
                amount = amount * price_1 * fee_mult   # spend base, get quote

            # Leg 2: mid_a → mid_b
            if triangle.leg2_side == "BUY":
                amount = amount / price_2 * fee_mult
            else:
                amount = amount * price_2 * fee_mult

            # Leg 3: mid_b → start
            if triangle.leg3_side == "BUY":
                amount = amount / price_3 * fee_mult
            else:
                amount = amount * price_3 * fee_mult

            # Net profit after fees (fees already deducted per leg above)
            net_profit_pct = (amount - 1.0) * 100
            gross_gap_pct = net_profit_pct + 3 * self.config.get("fee_per_leg_pct", 0.10)
            fee_cost_pct = 3 * self.config.get("fee_per_leg_pct", 0.10)

            # Track best profit across all triangles for diagnostics
            self._last_scan_checked += 1
            if net_profit_pct > self._last_scan_best_pct:
                self._last_scan_best_pct = net_profit_pct
                self._last_scan_best_tri = triangle.triangle_id

            # Check if profitable
            min_profit = self.config.get("min_net_profit_pct", 0.08)
            if net_profit_pct < min_profit:
                return None

            # Size position via Kelly
            trade_size_usdc = self._kelly_size(net_profit_pct)
            expected_profit_usdc = trade_size_usdc * (net_profit_pct / 100.0)

            return TriangleOpportunity(
                triangle=triangle,
                gross_profit_pct=gross_gap_pct,
                net_profit_pct=net_profit_pct,
                fee_cost_pct=fee_cost_pct,
                trade_size_usdc=trade_size_usdc,
                expected_profit_usdc=expected_profit_usdc,
                leg1_price=price_1,
                leg2_price=price_2,
                leg3_price=price_3,
            )

        except Exception:
            return None

    def _kelly_size(self, profit_pct: float) -> float:
        """
        Kelly criterion: f* = (p * b - q) / b
        where p = win probability (assume 1.0 for arb), b = profit ratio, q = 1 - p
        Simplified: f = profit_pct / 100 if win probability = 1.0
        Fractional Kelly (0.25) for safety.
        """
        kelly_fraction = 0.25  # Conservative: 1/4 Kelly
        max_size = self.config.get("max_trade_size_usdc", 5_000.0)
        min_size = self.config.get("min_trade_size_usdc", 50.0)

        size = max_size * (profit_pct / 100.0) * kelly_fraction
        return max(min_size, min(max_size, size))


# ─────────────────────────────────────────────────────────────────────────
# BINANCE BOOK TICKER FEED
# ─────────────────────────────────────────────────────────────────────────

class BinanceBookTickerFeed:
    """
    Real-time WebSocket feed: wss://stream.binance.com:9443/ws/!bookTicker
    Subscribes to best bid/ask for ALL trading pairs.
    Populates cache with:
      bid:binance:SOLUSDT = 145.3
      ask:binance:SOLUSDT = 145.35
      price:binance:SOLUSDT = 145.325 (mid)
    """

    def __init__(self, cache: TieredCache, all_pairs: Dict[str, BinancePair]):
        self.cache = cache
        self.all_pairs = all_pairs
        self._running = False
        self._reconnect_delay_s = 1.0

    async def run(self) -> None:
        """Launch multiple WebSocket connections in parallel, each handling ≤200 streams.
        Binance allows 5 WS connections and 1024 streams per connection, but rate-limits
        SUBSCRIBE to ~5 messages/second. Splitting across connections avoids 1008-policy-violation."""
        import json as _json

        all_symbols = list(self.all_pairs.keys())
        # Split into chunks of 200 streams per connection (Binance comfortable limit)
        CHUNK = 200
        chunks = [all_symbols[i:i + CHUNK] for i in range(0, len(all_symbols), CHUNK)]
        logger.info("book_ticker_feed_connected", total_streams=len(all_symbols), connections=len(chunks))

        tasks = [self._run_single_connection(chunk, idx) for idx, chunk in enumerate(chunks)]
        await asyncio.gather(*tasks)

    async def _run_single_connection(self, symbols: list, conn_id: int) -> None:
        """Maintain one WebSocket connection for a subset of symbols."""
        import websockets
        import json

        # Stagger connection starts to avoid thundering herd
        await asyncio.sleep(conn_id * 1.5)
        delay = 1.0

        while True:
            try:
                await self._connect_and_stream_chunk(symbols, conn_id)
                delay = 1.0
            except Exception as e:
                logger.warning("book_ticker_feed_error", error=str(e)[:120],
                               exc_type=type(e).__name__, conn=conn_id)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _connect_and_stream_chunk(self, symbols: list, conn_id: int) -> None:
        """Connect to Binance and subscribe to a chunk of bookTicker streams."""
        import websockets
        import json

        # Build stream names and connect via combined stream URL
        streams = [f"{sym.lower()}@bookTicker" for sym in symbols]
        uri = "wss://stream.binance.com:9443/stream"

        async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
            # Subscribe in small batches with generous delays to avoid rate limits
            BATCH = 50
            for i in range(0, len(streams), BATCH):
                batch = streams[i:i + BATCH]
                sub_msg = json.dumps({"method": "SUBSCRIBE", "params": batch, "id": conn_id * 100 + i + 1})
                await ws.send(sub_msg)
                await asyncio.sleep(0.5)  # 2 subscribes/sec — well within limits

            while True:
                msg = await ws.recv()
                try:
                    envelope = json.loads(msg)
                except Exception:
                    continue

                # Combined stream wraps data: {"stream": "btcusdt@bookTicker", "data": {...}}
                data = envelope.get("data", envelope)

                symbol = data.get("s")
                bid_str = data.get("b", "0")
                ask_str = data.get("a", "0")

                if not symbol or not bid_str or not ask_str:
                    continue

                bid = float(bid_str)
                ask = float(ask_str)

                if bid > 0 and ask > 0:
                    # Write directly to L1 (bypass Redis to avoid connection pool pressure)
                    # TTL=30s: illiquid pairs may not tick every 3s, but price is still valid
                    expiry = time.monotonic() + 30
                    self.cache._L1[f"bid:binance:{symbol}"] = (bid, expiry)
                    self.cache._L1[f"ask:binance:{symbol}"] = (ask, expiry)
                    self.cache._L1[f"price:binance:{symbol}"] = ((bid + ask) / 2, expiry)


# ─────────────────────────────────────────────────────────────────────────
# DEPTH FEED (Fix 1: book-walk simulation)
# ─────────────────────────────────────────────────────────────────────────

class BinanceDepthFeed:
    """
    Real-time 5-level depth: wss://.../<sym>@depth5@100ms
    Populates cache with:
      depth_bids:binance:SOLUSDT = [(price, qty), ...] level 1 → 5, descending
      depth_asks:binance:SOLUSDT = [(price, qty), ...] level 1 → 5, ascending

    Subscribed to a BOUNDED set of "hot" symbols (default max=300), refreshed
    periodically from a provider callable. Full-book subscriptions for all
    ~2000 pairs would flood bandwidth and bring nothing new for triangles
    that never fire. The hot set is exactly those pairs whose triangles
    actually trigger signals.

    Depth entries share the same L1 TTL=30s as bookTicker so the scanner's
    stale-feed guard applies uniformly. Feed reconnects on error.
    """

    DEPTH_TTL_S: float = 30.0

    def __init__(self, cache: TieredCache, symbols_provider, config: Dict):
        self.cache = cache
        # symbols_provider: callable () -> List[str]; refreshed every cycle
        self._symbols_provider = symbols_provider
        self.config = config
        self._current_subs: Set[str] = set()
        self._refresh_interval_s = float(config.get("depth_refresh_interval_s", 30.0))
        self._max_symbols = int(config.get("depth_max_symbols", 300))

    async def run(self) -> None:
        """Main loop: maintain a single WS connection, periodically adjust
        subscriptions to match what the strategy requests as its hot set."""
        import websockets
        import json

        uri = "wss://stream.binance.com:9443/stream"

        while True:
            try:
                async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                    await self._sync_subscriptions(ws)
                    refresh_task = asyncio.create_task(self._refresh_loop(ws))
                    try:
                        async for msg in ws:
                            self._handle_message(msg)
                    finally:
                        refresh_task.cancel()
                        try: await refresh_task
                        except asyncio.CancelledError: pass
            except Exception as e:
                logger.warning("depth_feed_error", error=str(e)[:120],
                               exc_type=type(e).__name__)
                self._current_subs.clear()  # force full resubscribe on reconnect
                await asyncio.sleep(2.0)

    async def _refresh_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval_s)
            try:
                await self._sync_subscriptions(ws)
            except Exception as e:
                logger.warning("depth_feed_refresh_error", error=str(e)[:120])

    async def _sync_subscriptions(self, ws) -> None:
        """Diff current vs. desired subscription set, send SUBSCRIBE / UNSUBSCRIBE."""
        import json
        desired = set(self._symbols_provider()[:self._max_symbols])
        to_add = desired - self._current_subs
        to_remove = self._current_subs - desired

        if to_add:
            streams = [f"{s.lower()}@depth5@100ms" for s in to_add]
            # Batch to stay well under 5 msg/s rate limit
            BATCH = 50
            for i in range(0, len(streams), BATCH):
                msg = {"method": "SUBSCRIBE", "params": streams[i:i+BATCH],
                       "id": 9000 + i}
                await ws.send(json.dumps(msg))
                await asyncio.sleep(0.4)

        if to_remove:
            streams = [f"{s.lower()}@depth5@100ms" for s in to_remove]
            BATCH = 50
            for i in range(0, len(streams), BATCH):
                msg = {"method": "UNSUBSCRIBE", "params": streams[i:i+BATCH],
                       "id": 9500 + i}
                await ws.send(json.dumps(msg))
                await asyncio.sleep(0.4)

        self._current_subs = desired
        logger.debug("depth_feed_synced",
                     subscribed=len(desired),
                     added=len(to_add),
                     removed=len(to_remove))

    def _handle_message(self, msg: str) -> None:
        import json
        try:
            envelope = json.loads(msg)
        except Exception:
            return
        data = envelope.get("data", envelope)
        stream = envelope.get("stream", "")
        # Binance partial book has no 's' in payload; recover from stream name
        sym = None
        if "@" in stream:
            sym = stream.split("@", 1)[0].upper()
        if not sym:
            return

        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids and not asks:
            return

        expiry = time.monotonic() + self.DEPTH_TTL_S
        try:
            bid_levels = [(float(p), float(q)) for p, q in bids[:5] if float(q) > 0]
            ask_levels = [(float(p), float(q)) for p, q in asks[:5] if float(q) > 0]
        except (ValueError, TypeError):
            return

        if bid_levels:
            self.cache._L1[f"depth_bids:binance:{sym}"] = (bid_levels, expiry)
        if ask_levels:
            self.cache._L1[f"depth_asks:binance:{sym}"] = (ask_levels, expiry)


def walk_book(levels: List[Tuple[float, float]], base_qty: float) -> Optional[float]:
    """Compute VWAP fill price to consume base_qty units of the base asset.
    levels is an ordered list (price, qty) — best-to-worst direction.
    Returns None if total depth < base_qty (we'd have to walk beyond level 5
    and we don't know the rest of the book).
    Used for both BUY asks and SELL bids — pass the correct side in.
    """
    if base_qty <= 0 or not levels:
        return None
    remaining = base_qty
    cost = 0.0
    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        take = remaining if remaining <= qty else qty
        cost += take * price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        # Not enough depth in 5 levels to fill — caller decides what to do
        return None
    return cost / base_qty


# ─────────────────────────────────────────────────────────────────────────
# PAPER TRADE SIMULATOR
# ─────────────────────────────────────────────────────────────────────────

class PaperTriangleSimulator:
    """
    Simulates 3-leg execution with realistic Binance effects:
    - Latency: 3–8ms per leg, sequential = 9–24ms total
    - Price drift during execution
    - Fee deduction per leg
    """

    def __init__(self, cache: TieredCache, config: Dict):
        self.cache = cache
        self.config = config
        # Fix 2: synthetic slippage RNG. Deterministic seed (if set) makes
        # repeat paper runs identical, useful for A/B comparisons. In normal
        # operation seed=None so every process run samples fresh.
        seed = config.get("synthetic_slippage_seed")
        self._slip_rng = random.Random(seed) if seed is not None else random.Random()

    def _sample_slippage_bps(self, leg_class: str) -> float:
        """Draw a per-leg synthetic slippage in bps.
        The distribution is truncated normal: N(mean, stdev) clipped to [0, max].
        Always non-negative — slippage is ALWAYS unfavorable, never positive
        price improvement, because L1 already captures the favorable tick.
        This models book-walk + queue position + tiny adverse ticks between
        our send and Binance's match engine decision.
        """
        params = self.config.get("synthetic_slippage_bps", {}).get(leg_class)
        if not params:
            return 0.0
        mean = float(params.get("mean", 0.0))
        stdev = float(params.get("stdev", 0.0))
        max_bps = float(params.get("max", 0.0))
        if stdev <= 0.0 and mean <= 0.0:
            return 0.0
        raw = self._slip_rng.gauss(mean, stdev)
        # Truncate to [0, max]: slippage can't be negative (would be a gift),
        # and capped so a 5-sigma outlier doesn't turn a stable-pair into a
        # 50 bps disaster.
        if raw < 0.0:
            return 0.0
        if raw > max_bps:
            return max_bps
        return raw

    async def simulate_execution(
        self,
        opportunity: TriangleOpportunity,
    ) -> TradeResult:
        """
        Realistic paper simulation (Approach D).

        Instead of using scanner prices as fill prices (which guaranteed 100%
        winrate but lied about live behavior), we:
          1. Sleep the configured per-leg latency (default 4–5ms each).
          2. At each leg's "fill moment," re-read the L1 book cache and use
             the CURRENT ask (for BUY) or bid (for SELL) as the actual fill
             price. This captures real book movement during execution.
          3. Enforce the per-leg tolerance limit: if the re-read price moved
             beyond the limit we'd have sent, mark leg as CANCELED_NO_FILL.
          4. Apply fees per leg the same way live will.

        Outcome classification mirrors what the live executor will produce,
        so paper stats become directly comparable to future live stats.
        """
        start_time = time.perf_counter()
        triangle = opportunity.triangle
        fee_per_leg = self.config.get("fee_per_leg_pct", 0.10) / 100.0
        fee_mult = 1.0 - fee_per_leg
        size_usdc = opportunity.trade_size_usdc
        fee_cost_pct = 3 * self.config.get("fee_per_leg_pct", 0.10)

        # Latency config (per-leg)
        lat_cfg = self.config.get("paper_leg_latency_ms", {"leg1": 4.0, "leg2": 4.5, "leg3": 4.0})
        leg_latency_ms = (
            float(lat_cfg.get("leg1", 4.0)),
            float(lat_cfg.get("leg2", 4.5)),
            float(lat_cfg.get("leg3", 4.0)),
        )

        # Scanner prices (what we SAW at signal time)
        scanner_prices = {
            triangle.leg1_symbol: opportunity.leg1_price,
            triangle.leg2_symbol: opportunity.leg2_price,
            triangle.leg3_symbol: opportunity.leg3_price,
        }

        # Fix 1: book-walk config. When depth feeds are live we use the true
        # VWAP for the requested size; when they aren't we fall back to L1.
        use_book_walk = self.config.get("paper_use_book_walk", True)

        # Per-leg BUY/SELL meta used for both tolerance math and fill read.
        # 7th element = leg class, used by Fix 2 to draw synthetic slippage.
        legs = [
            (triangle.leg1_symbol, triangle.leg1_side, triangle.leg1_key, opportunity.leg1_price, triangle.leg1_tolerance_bps, leg_latency_ms[0], triangle.leg1_class),
            (triangle.leg2_symbol, triangle.leg2_side, triangle.leg2_key, opportunity.leg2_price, triangle.leg2_tolerance_bps, leg_latency_ms[1], triangle.leg2_class),
            (triangle.leg3_symbol, triangle.leg3_side, triangle.leg3_key, opportunity.leg3_price, triangle.leg3_tolerance_bps, leg_latency_ms[2], triangle.leg3_class),
        ]

        simulate_latency = self.config.get("paper_simulate_latency", True)
        execution_mode = "paper_sim_latency" if simulate_latency else "paper_instant"

        try:
            # Expected (signal-time) net pct — what scanner promised
            expected_net_pct = opportunity.net_profit_pct
            expected_pnl_usdc = size_usdc * (expected_net_pct / 100.0)

            per_leg_status: Dict[str, str] = {}
            actual_fills: Dict[str, float] = {}
            per_leg_slip_bps: Dict[str, float] = {}
            per_leg_latency: Dict[str, float] = {}

            amount = 1.0  # Start with 1 unit of start_currency
            all_filled = True
            abort_reason = ""

            for idx, (sym, side, key, scanner_px, tol_bps, lat_ms, leg_class) in enumerate(legs, start=1):
                leg_label = f"leg{idx}"
                leg_start = time.perf_counter()

                # Simulate execution latency (Singapore VPS ~4ms per leg WS API)
                if simulate_latency and lat_ms > 0:
                    await asyncio.sleep(lat_ms / 1000.0)

                # Compute tolerance-bound limit price in the unfavorable direction.
                tol_frac = tol_bps / 10_000.0  # bps → fraction
                if side == "BUY":
                    limit_px = scanner_px * (1.0 + tol_frac)   # willing to pay up to scanner × (1+tol)
                else:
                    limit_px = scanner_px * (1.0 - tol_frac)   # willing to receive down to scanner × (1-tol)

                # Re-read L1 cache at fill moment — this is the key realism fix.
                # L1 entries are (value, expiry_monotonic). We use fresh values only.
                fill_px: Optional[float] = None
                entry = self.cache._L1.get(key)
                now_mono = time.monotonic()
                if entry and entry[1] >= now_mono:
                    fill_px = float(entry[0])

                # Fix 1: walk the book depth for the actual trade size.
                # Convert our USDC size into base-asset quantity and compute
                # VWAP across available levels. If depth is subscribed and
                # sufficient, use VWAP. Otherwise fall back to L1 top-of-book.
                depth_vwap: Optional[float] = None
                depth_exhausted = False
                if use_book_walk and fill_px is not None:
                    depth_key = (f"depth_asks:binance:{sym}" if side == "BUY"
                                 else f"depth_bids:binance:{sym}")
                    depth_entry = self.cache._L1.get(depth_key)
                    if depth_entry and depth_entry[1] >= now_mono:
                        levels = depth_entry[0]
                        # Base-asset quantity required for this leg. At L1
                        # fill_px, a USDC-sized trade needs size_usdc/fill_px
                        # units of base. For intermediate legs, we scale by
                        # the `amount` accumulator (which is in units of the
                        # leg's incoming currency).
                        # Conservative approximation: use size_usdc / fill_px
                        # — overstates slightly for SELL legs after a BUY
                        # (the incoming qty may be slightly less) but that
                        # only makes paper look harsher, which is fine.
                        base_qty = size_usdc / fill_px if fill_px > 0 else 0.0
                        vwap = walk_book(levels, base_qty)
                        if vwap is not None:
                            depth_vwap = vwap
                        else:
                            # Depth insufficient: our order would walk past
                            # level 5. That's already a bad sign — treat it
                            # as if the worst level we saw sets the fill,
                            # plus a penalty to simulate the unknown tail.
                            if levels:
                                worst_px = levels[-1][0]
                                # 3x the gap from top to worst level as tail penalty
                                top_px = levels[0][0]
                                gap = abs(worst_px - top_px)
                                if side == "BUY":
                                    depth_vwap = worst_px + 3 * gap
                                else:
                                    depth_vwap = max(0.0, worst_px - 3 * gap)
                                depth_exhausted = True

                if depth_vwap is not None:
                    fill_px = depth_vwap

                # Fix 2: synthetic slippage on top of L1 re-read + book walk.
                # L1 only shows top-of-book; it can't show book-walk when our
                # size exceeds top-level depth, and it misses the queue/timing
                # penalty that hits every real taker. Add a per-class draw.
                synth_bps = self._sample_slippage_bps(leg_class) if fill_px else 0.0
                if fill_px and synth_bps > 0.0:
                    synth_frac = synth_bps / 10_000.0
                    if side == "BUY":
                        # We pay MORE than L1 ask
                        fill_px = fill_px * (1.0 + synth_frac)
                    else:
                        # We receive LESS than L1 bid
                        fill_px = fill_px * (1.0 - synth_frac)

                per_leg_latency[leg_label] = round((time.perf_counter() - leg_start) * 1000, 2)

                if fill_px is None or fill_px <= 0:
                    # No fresh L1 price at fill time → treat as no-fill.
                    per_leg_status[leg_label] = "CANCELED_NO_FILL"
                    all_filled = False
                    abort_reason = f"no L1 price at fill moment for {sym}"
                    break

                # Enforce limit: if the book moved past our tolerance, this leg
                # would not have filled in a live IOC LIMIT scenario.
                if side == "BUY" and fill_px > limit_px:
                    per_leg_status[leg_label] = "CANCELED_NO_FILL"
                    actual_fills[sym] = fill_px
                    # slippage relative to scanner on the unfavorable side
                    per_leg_slip_bps[leg_label] = round((fill_px - scanner_px) / scanner_px * 10_000, 2)
                    all_filled = False
                    abort_reason = f"{sym} ask {fill_px:.6f} > limit {limit_px:.6f} (tol {tol_bps}bps)"
                    break
                if side == "SELL" and fill_px < limit_px:
                    per_leg_status[leg_label] = "CANCELED_NO_FILL"
                    actual_fills[sym] = fill_px
                    per_leg_slip_bps[leg_label] = round((scanner_px - fill_px) / scanner_px * 10_000, 2)
                    all_filled = False
                    abort_reason = f"{sym} bid {fill_px:.6f} < limit {limit_px:.6f} (tol {tol_bps}bps)"
                    break

                # Fill accepted. Record slippage relative to scanner.
                if side == "BUY":
                    slip_bps = (fill_px - scanner_px) / scanner_px * 10_000  # positive = worse
                    amount = amount / fill_px * fee_mult
                else:
                    slip_bps = (scanner_px - fill_px) / scanner_px * 10_000  # positive = worse
                    amount = amount * fill_px * fee_mult

                per_leg_status[leg_label] = "FILLED"
                per_leg_slip_bps[leg_label] = round(slip_bps, 2)
                actual_fills[sym] = fill_px

            execution_ms = (time.perf_counter() - start_time) * 1000
            latency_class = (
                "fast"    if execution_ms < 10 else
                "normal"  if execution_ms < 20 else
                "slow"    if execution_ms < 40 else
                "timeout"
            )

            # ── Outcome classification ────────────────────────────────────
            if all_filled:
                actual_net_pct = (amount - 1.0) * 100.0
                actual_net_usdc = size_usdc * (actual_net_pct / 100.0)
                fees_usdc = size_usdc * (fee_cost_pct / 100.0)
                edge_lost_pct = expected_net_pct - actual_net_pct  # positive = slippage ate edge
                outcome_status = "COMPLETE"
                # "Success" = trade was actually profitable, not just that it filled.
                success = actual_net_pct > 0.0
                error = None if success else f"completed but net negative: {actual_net_pct:.4f}%"
            else:
                # Partial fill: we accumulate spread-cost to hedge what filled.
                # Bounded-loss model: assume hedging costs 1 leg's fee + 1 leg's
                # full tolerance band as slippage on the unwind.
                filled_legs = sum(1 for s in per_leg_status.values() if s == "FILLED")
                if filled_legs == 0:
                    outcome_status = "NO_FILL"
                    actual_net_pct = 0.0
                    actual_net_usdc = 0.0
                    fees_usdc = 0.0
                    edge_lost_pct = expected_net_pct  # all edge lost
                    success = False
                    error = f"No legs filled — {abort_reason}"
                else:
                    outcome_status = "PARTIAL_HEDGED"
                    # Worst-case hedge cost: filled_legs × (fee + tolerance)
                    hedge_cost_pct = filled_legs * (
                        self.config.get("fee_per_leg_pct", 0.075)
                        + max(
                            triangle.leg1_tolerance_bps,
                            triangle.leg2_tolerance_bps,
                            triangle.leg3_tolerance_bps,
                        ) / 100.0
                    )
                    actual_net_pct = -hedge_cost_pct
                    actual_net_usdc = size_usdc * (actual_net_pct / 100.0)
                    fees_usdc = size_usdc * (filled_legs * self.config.get("fee_per_leg_pct", 0.075) / 100.0)
                    edge_lost_pct = expected_net_pct - actual_net_pct
                    success = False
                    error = f"Partial fill hedged: {abort_reason}"

            return TradeResult(
                triangle_id=triangle.triangle_id,
                success=success,
                net_profit_usdc=round(actual_net_usdc, 6),
                net_profit_pct=round(actual_net_pct, 6),
                execution_ms=round(execution_ms, 2),
                fill_prices=dict(actual_fills),
                trade_size_usdc=size_usdc,
                is_paper=True,
                error=error,
                # Rich Approach D schema ─────────────────────────────────
                execution_mode=execution_mode,
                scanner_prices=scanner_prices,
                actual_fill_prices=dict(actual_fills),
                per_leg_slippage_bps=per_leg_slip_bps,
                per_leg_latency_ms=per_leg_latency,
                per_leg_status=per_leg_status,
                expected_net_pct=round(expected_net_pct, 6),
                actual_net_pct=round(actual_net_pct, 6),
                required_edge_pct=round(triangle.required_edge_pct, 6),
                expected_pnl_usdc=round(expected_pnl_usdc, 6),
                fees_paid_usdc=round(fees_usdc, 6),
                edge_lost_to_slippage_pct=round(edge_lost_pct, 6),
                outcome_status=outcome_status,
                latency_classification=latency_class,
            )

        except Exception as e:
            execution_ms = (time.perf_counter() - start_time) * 1000
            return TradeResult(
                triangle_id=opportunity.triangle.triangle_id,
                success=False,
                net_profit_usdc=0.0,
                net_profit_pct=0.0,
                execution_ms=execution_ms,
                fill_prices={},
                is_paper=True,
                error=str(e),
                execution_mode=execution_mode,
                scanner_prices=scanner_prices,
                expected_net_pct=opportunity.net_profit_pct,
                required_edge_pct=triangle.required_edge_pct,
                outcome_status="FAILED",
                latency_classification="unknown",
            )


# ─────────────────────────────────────────────────────────────────────────
# LIVE EXECUTION ENGINE
# ─────────────────────────────────────────────────────────────────────────

class LiveTriangleExecutor:
    """
    Executes all 3 legs of a triangle on Binance sequentially.

    Why sequential (not parallel like A_CEX):
      Leg 2 quantity depends on exactly how much Leg 1 gave you.
      You can't know Leg 2's input quantity until Leg 1 fills.
      Leg 3 depends on Leg 2's output.
      This is inherent to triangular arb — each leg feeds the next.

    Total execution time: 3 legs × 5–15ms each = 15–45ms total.
    During those 45ms, the gap may narrow but rarely disappears completely
    because you're on a single exchange and the mispricing is structural.

    Order types:
      All MARKET orders — triangular arb requires immediate fills.
      LIMIT orders risk partial fills leaving you exposed mid-triangle.

    Failure handling:
      Leg 1 fails: abort. Nothing done. Zero exposure.
      Leg 2 fails after Leg 1 filled: you hold the Leg 1 asset.
        → Immediately sell it back at market. Accept small loss.
      Leg 3 fails after Legs 1+2 filled: you hold the Leg 2 asset.
        → Immediately sell it back to start currency at market.

    Safety:
      Hard 5-second timeout for all 3 legs combined.
      Kill switch checked before each leg.
      All errors logged to Supabase for review.
    """

    def __init__(self):
        self._client = None

    async def _get_client(self):
        """Lazy-load Binance AsyncClient."""
        if self._client is None:
            try:
                from binance import AsyncClient
                self._client = await AsyncClient.create(
                    api_key=os.getenv("BINANCE_API_KEY", ""),
                    api_secret=os.getenv("BINANCE_API_SECRET", ""),
                )
            except Exception as e:
                logger.error("binance_client_init_error", error=str(e))
                raise
        return self._client

    async def execute(
        self,
        opp_data: dict,
        kill_switch: KillSwitchBus,
    ) -> TradeResult:
        """Execute 3 sequential Binance market orders."""
        start = time.perf_counter()
        fills = {}
        holdings = []  # Track what we've acquired in case of failure

        try:
            client = await self._get_client()
            size = float(opp_data.get("size_usdc", 0))

            # ── LEG 1 ────────────────────────────────────────────────────
            leg1_fill = await asyncio.wait_for(
                self._place_order(
                    client=client,
                    symbol=opp_data["leg1_symbol"],
                    side=opp_data["leg1_side"],
                    size_usdc=size,
                    ref_price=opp_data["leg1_price"],
                    is_first=True,
                ),
                timeout=2.0,
            )
            fills[opp_data["leg1_symbol"]] = leg1_fill["fill_price"]
            holdings.append(("leg1", leg1_fill))
            qty_after_1 = leg1_fill["received_qty"]

            # ── LEG 2 ────────────────────────────────────────────────────
            leg2_fill = await asyncio.wait_for(
                self._place_order(
                    client=client,
                    symbol=opp_data["leg2_symbol"],
                    side=opp_data["leg2_side"],
                    qty_in=qty_after_1,
                    ref_price=opp_data["leg2_price"],
                    is_first=False,
                ),
                timeout=2.0,
            )
            fills[opp_data["leg2_symbol"]] = leg2_fill["fill_price"]
            holdings.append(("leg2", leg2_fill))
            qty_after_2 = leg2_fill["received_qty"]

            # ── LEG 3 ────────────────────────────────────────────────────
            leg3_fill = await asyncio.wait_for(
                self._place_order(
                    client=client,
                    symbol=opp_data["leg3_symbol"],
                    side=opp_data["leg3_side"],
                    qty_in=qty_after_2,
                    ref_price=opp_data["leg3_price"],
                    is_first=False,
                ),
                timeout=2.0,
            )
            fills[opp_data["leg3_symbol"]] = leg3_fill["fill_price"]
            qty_final = leg3_fill["received_qty"]

            # ── Calculate actual PnL ──────────────────────────────────────
            net_profit_usdc = qty_final - size
            net_profit_pct = (net_profit_usdc / size * 100) if size > 0 else 0
            execution_ms = (time.perf_counter() - start) * 1000

            logger.info(
                "live_triangle_complete",
                triangle=opp_data.get("triangle_id", "unknown"),
                profit_usdc=round(net_profit_usdc, 4),
                profit_pct=round(net_profit_pct, 4),
                ms=round(execution_ms, 1),
            )

            return TradeResult(
                triangle_id=opp_data["triangle_id"],
                success=net_profit_usdc > 0,
                net_profit_usdc=round(net_profit_usdc, 6),
                net_profit_pct=round(net_profit_pct, 6),
                execution_ms=round(execution_ms, 2),
                fill_prices=fills,
                is_paper=False,
            )

        except asyncio.TimeoutError:
            logger.error("live_triangle_timeout", triangle=opp_data.get("triangle_id", "unknown"))
            if holdings:
                try:
                    client = await self._get_client()
                    await self._emergency_reverse(client, holdings, opp_data)
                except Exception as e:
                    logger.error("reverse_failed_after_timeout", error=str(e))
            return self._failed(opp_data, "Timeout — position reversed")

        except Exception as e:
            logger.error("live_triangle_error", triangle=opp_data.get("triangle_id", "unknown"), error=str(e))
            if holdings:
                try:
                    client = await self._get_client()
                    await self._emergency_reverse(client, holdings, opp_data)
                except Exception as e2:
                    logger.error("reverse_failed", error=str(e2))
            return self._failed(opp_data, str(e))

    async def _place_order(
        self,
        client: any,
        symbol: str,
        side: str,
        ref_price: float,
        is_first: bool,
        size_usdc: float = 0.0,
        qty_in: float = 0.0,
    ) -> dict:
        """Place one market order. Returns fill info."""
        try:
            if is_first:
                # First leg: we know how much USDC to spend
                order = await client.create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quoteOrderQty=str(round(size_usdc, 2)),
                )
            else:
                # Subsequent legs: we know the input quantity
                precision = 6  # default — ideally lookup from pair filter
                qty = round(qty_in, precision)

                order = await client.create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=str(qty),
                )

            # Extract fill data
            fills = order.get("fills", [{}])
            avg_fill = float(order.get("price", ref_price))
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_fill = total_cost / total_qty if total_qty > 0 else ref_price

            exec_qty = float(order.get("executedQty", 0))
            quote_qty = float(order.get("cummulativeQuoteQty", 0))

            # Determine what we received
            if side == "BUY":
                # BUY: spent quote, received base
                received_qty = exec_qty  # base asset quantity received
            else:
                # SELL: spent base, received quote
                received_qty = quote_qty  # quote asset amount received

            return {
                "order_id": order.get("orderId", ""),
                "symbol": symbol,
                "side": side,
                "fill_price": round(avg_fill, 8),
                "exec_qty": exec_qty,
                "quote_qty": quote_qty,
                "received_qty": received_qty,
            }
        except Exception as e:
            logger.error("place_order_error", symbol=symbol, side=side, error=str(e))
            raise

    async def _emergency_reverse(
        self,
        client: any,
        holdings: list,
        opp_data: dict,
    ) -> None:
        """
        Reverse any filled legs to avoid being stuck in a partial position.
        Called when a mid-execution failure occurs.
        """
        logger.warning("emergency_reverse_triggered", legs=len(holdings))

        for leg_name, fill in reversed(holdings):
            try:
                symbol = fill["symbol"]
                qty_held = fill["received_qty"]

                if qty_held <= 0:
                    continue

                # Reverse: if we bought, sell back; if we sold, buy back
                reverse_side = "SELL" if fill["side"] == "BUY" else "BUY"

                if reverse_side == "SELL":
                    await client.create_order(
                        symbol=symbol,
                        side="SELL",
                        type="MARKET",
                        quantity=str(round(qty_held, 6)),
                    )
                else:
                    await client.create_order(
                        symbol=symbol,
                        side="BUY",
                        type="MARKET",
                        quoteOrderQty=str(round(qty_held, 2)),
                    )
                logger.info("leg_reversed", leg=leg_name, symbol=symbol)

            except Exception as e:
                logger.error("reverse_failed", leg=leg_name, symbol=fill.get("symbol"), error=str(e))

    def _failed(self, opp_data: dict, error: str) -> TradeResult:
        """Return a failed trade result."""
        return TradeResult(
            triangle_id=opp_data.get("triangle_id", "unknown"),
            success=False,
            net_profit_usdc=0.0,
            net_profit_pct=0.0,
            execution_ms=0.0,
            fill_prices={},
            is_paper=False,
            error=error,
        )


# ─────────────────────────────────────────────────────────────────────────
# PROMOTION GATES
# ─────────────────────────────────────────────────────────────────────────

class TrianglePromotionGates:
    """
    6 gates before paper → live for dynamic triangular arb.
    """

    GATES = {
        "min_trades": 50,
        "min_win_rate": 0.90,
        "min_unique_triangles_used": 10,
        "min_avg_net_pct": 0.05,
        "max_consecutive_losses": 3,
        "zero_reversal_events": True,
    }

    def __init__(self, db: SupabaseClient):
        self._db = db

    async def check_all_gates(self) -> dict:
        """Check all 6 promotion gates."""
        trades = await self._get_paper_trades()
        if not trades:
            return self._all_failed()

        total = len(trades)
        wins = [t for t in trades if float(t.get("net_profit_usdc") or 0) > 0]
        win_rate = len(wins) / total if total > 0 else 0

        gate1 = total >= self.GATES["min_trades"]
        gate2 = win_rate >= self.GATES["min_win_rate"]

        # Gate 3: unique triangles used
        unique_tris = len(
            set(
                t.get("triangle_id", "").split("_")[0]
                for t in trades
                if t.get("triangle_id")
            )
        )
        gate3 = unique_tris >= self.GATES["min_unique_triangles_used"]

        # Gate 4: avg net profit
        avg_profit = sum(float(t.get("net_profit_pct") or 0) for t in trades) / total if total > 0 else 0
        gate4 = avg_profit >= self.GATES["min_avg_net_pct"]

        # Gate 5: consecutive losses
        gate5 = self._max_streak(trades) < self.GATES["max_consecutive_losses"]

        # Gate 6: no reversal events
        reversals = sum(1 for t in trades if "reversed" in (t.get("error") or "").lower())
        gate6 = reversals == 0

        all_passed = all([gate1, gate2, gate3, gate4, gate5, gate6])
        return {
            "all_passed": all_passed,
            "strategy_id": "A_M1_triangular_arb",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "gates": {
                "min_trades": {
                    "passed": gate1,
                    "value": total,
                    "required": self.GATES["min_trades"],
                },
                "min_win_rate": {
                    "passed": gate2,
                    "value": round(win_rate, 4),
                    "required": self.GATES["min_win_rate"],
                },
                "min_unique_triangles_used": {
                    "passed": gate3,
                    "value": unique_tris,
                    "required": self.GATES["min_unique_triangles_used"],
                },
                "min_avg_net_pct": {
                    "passed": gate4,
                    "value": round(avg_profit, 4),
                    "required": self.GATES["min_avg_net_pct"],
                },
                "max_consecutive_losses": {
                    "passed": gate5,
                    "value": self._max_streak(trades),
                    "required": self.GATES["max_consecutive_losses"],
                },
                "zero_reversal_events": {
                    "passed": gate6,
                    "value": reversals,
                    "required": 0,
                },
            },
        }

    async def promote_to_live(self) -> bool:
        """Promote strategy to live if all gates pass."""
        gates = await self.check_all_gates()
        if not gates["all_passed"]:
            failed = [k for k, v in gates["gates"].items() if not v["passed"]]
            logger.warning("promotion_blocked", failed_gates=failed)
            return False

        try:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._db.table("strategy_flags")
                    .update(
                        {
                            "enabled": True,
                            "mode": "live",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    .eq("strategy_id", "A_M1_triangular_arb")
                    .execute(),
                ),
                timeout=5.0,
            )
            logger.info("A_M1_promoted_to_live")
            return True
        except Exception as e:
            logger.error("promotion_db_error", error=str(e))
            return False

    async def _get_paper_trades(self) -> list:
        """Fetch paper trades from Supabase."""
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._db.table("strategy_executions")
                    .select("triangle_id, net_profit_usdc, net_profit_pct, error, created_at")
                    .eq("strategy_id", "A_M1_triangular_arb")
                    .eq("is_paper", True)
                    .order("created_at", desc=True)
                    .limit(100)
                    .execute(),
                ),
                timeout=5.0,
            )
            return result.data or []
        except Exception as e:
            logger.warning("get_paper_trades_error", error=str(e))
            return []

    def _max_streak(self, trades: list) -> int:
        """Calculate max consecutive losses."""
        streak = max_s = 0
        for t in sorted(trades, key=lambda x: x.get("created_at", "")):
            if float(t.get("net_profit_usdc") or 0) < 0:
                streak += 1
                max_s = max(max_s, streak)
            else:
                streak = 0
        return max_s

    def _all_failed(self) -> dict:
        """Return gates-all-failed response."""
        return {
            "all_passed": False,
            "strategy_id": "A_M1_triangular_arb",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "gates": {
                k: {"passed": False, "value": 0, "required": v}
                for k, v in self.GATES.items()
            },
        }


# ─────────────────────────────────────────────────────────────────────────
# STRATEGY CLASS
# ─────────────────────────────────────────────────────────────────────────

class Strategy(BaseStrategy):
    """
    A_M1_triangular_arb v2: Dynamic discovery + real-time paper trading.
    """

    STRATEGY_ID = "A_M1_triangular_arb"
    DISPLAY_NAME = "Triangular Arbitrage (Dynamic)"
    CATEGORY = "A_math"
    CATEGORY_LABEL = "Mathematical Certainty"
    DESCRIPTION = "All Binance triangles, dynamic discovery, real-time pricing"
    VERSION = "v2-dynamic"
    RUNS_OWN_LOOP = True  # Enable independent scanning loop

    def __init__(
        self,
        kill_switch: KillSwitchBus,
        db: SupabaseClient,
        tax_engine,
        allocated_usdc: float = 0.0,
        cache: Optional[TieredCache] = None,
        event_bus: Optional[AsyncEventBus] = None,
    ):
        super().__init__(kill_switch, db, tax_engine, allocated_usdc)
        self.cache = cache
        self.event_bus = event_bus

        self._graph: Optional[PairGraphBuilder] = None
        self._discoverer: Optional[TriangleDiscoverer] = None
        self._scanner: Optional[DynamicTriangleScanner] = None
        self._paper_sim: Optional[PaperTriangleSimulator] = None
        self._book_feed_task: Optional[asyncio.Task] = None
        self._depth_feed_task: Optional[asyncio.Task] = None

        # Part 2: Live execution and promotion
        self._live_executor = LiveTriangleExecutor()
        self._promotion_gates = TrianglePromotionGates(db)

        # Part 3: Bounded-parallel live executor + test-mode state machine.
        # These are created during startup() after config is loaded so the
        # WS trader starts in the correct dry-run / allow-real-money posture.
        self._ws_trader = None            # type: Optional[BinanceWSTrader]
        self._live_exec = None            # type: Optional[BoundedParallelExecutor]
        self._latency_breaker = None      # type: Optional[LatencyCircuitBreaker]
        self._live_test_state = None      # type: Optional[LiveTestState]

        self._last_execution_time = 0.0
        self._paper_trades: List[TradeResult] = []
        self._config = DEFAULT_CONFIG.copy()

        # Capital allocation cache (refresh every 5 seconds)
        self._cached_capital = 1000.0
        self._last_capital_refresh_ns = 0

    async def startup(self) -> None:
        """
        Initialize strategy:
        1. Load config from cache/Supabase
        2. Build pair graph (fetch all Binance pairs)
        3. Discover all triangles
        4. Start BookTicker WebSocket feed
        """
        logger.info("a_m1_strategy_startup")

        try:
            # Load config (non-blocking: continue if cache unavailable)
            try:
                cached_cfg = await asyncio.wait_for(
                    self.cache.get(f"strategy_config:{self.STRATEGY_ID}"),
                    timeout=3.0
                )
                if cached_cfg and isinstance(cached_cfg, dict):
                    self._config.update(cached_cfg)
                logger.info("a_m1_config_loaded", config=self._config)
            except asyncio.TimeoutError:
                logger.warning("a_m1_config_load_timeout")
                logger.info("a_m1_using_default_config")
            except Exception as e:
                logger.warning("a_m1_config_load_failed", error=str(e))
                logger.info("a_m1_using_default_config")

            # Build pair graph
            _excluded_fiat = set(self._config.get("excluded_fiat_currencies", [
                "IDR", "VND", "NGN", "RON", "TRY", "GBP", "PKR", "EGP", "ARS",
                "TUSD", "BUSD", "USDP", "USDD", "GUSD", "USDJ",
            ]))
            self._graph = PairGraphBuilder(
                self.cache,
                min_volume_usdc=self._config.get("min_volume_24h_usdc", 100_000),
                excluded_fiat=_excluded_fiat,
            )
            await self._graph.build()

            # Discover triangles — pass config so per-triangle tolerance/threshold
            # is computed at discovery time (Approach D).
            self._discoverer = TriangleDiscoverer(
                self._graph,
                base_currencies=self._config.get("base_currencies", ["USDT", "BTC", "ETH"]),
                config=self._config,
            )
            triangles = self._discoverer.discover_all()
            # Summary stats: how many triangles fall into each class combination.
            _class_buckets: Dict[str, int] = {}
            for t in triangles:
                k = f"{t.leg1_class}-{t.leg2_class}-{t.leg3_class}"
                _class_buckets[k] = _class_buckets.get(k, 0) + 1
            logger.info(
                "a_m1_triangles_discovered",
                count=len(triangles),
                class_distribution=_class_buckets,
                avg_required_edge_pct=round(
                    sum(t.required_edge_pct for t in triangles) / max(1, len(triangles)), 4
                ),
            )

            # Update cache with graph stats for dashboard (non-blocking)
            try:
                await asyncio.wait_for(
                    self.cache.set(
                        "a_m1:graph:stats",
                        {
                            "total_pairs": len(self._graph.all_pairs),
                            "total_currencies": len(self._graph.adj),
                            "total_triangles": len(triangles),
                            "graph_built_at": datetime.utcnow().isoformat(),
                            "feed_connected": True,
                            "fee_per_leg_pct": self._config.get("fee_per_leg_pct", 0.075),
                            "min_net_profit_pct": self._config.get("min_net_profit_pct", 0.02),
                        },
                        ttl=3600,
                    ),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning("a_m1_cache_stats_write_timeout")
            except Exception as e:
                logger.warning("a_m1_cache_stats_write_failed", error=str(e))

            # Create scanner
            self._scanner = DynamicTriangleScanner(triangles, self.cache, self._config)

            # Create paper simulator
            self._paper_sim = PaperTriangleSimulator(self.cache, self._config)

            # Start BookTicker WebSocket feed (background task)
            self._book_feed_task = asyncio.create_task(
                BinanceBookTickerFeed(self.cache, self._graph.all_pairs).run()
            )
            logger.info("a_m1_book_feed_started")

            # Fix 1: start depth feed for hot-triangle symbols. The provider
            # returns the union of all symbols used by the scanner's hot
            # cache (rebuilt every full sweep). Bounded to depth_max_symbols.
            if self._config.get("enable_depth_feed", True):
                self._depth_feed_task = asyncio.create_task(
                    BinanceDepthFeed(
                        self.cache,
                        self._hot_symbols_for_depth,
                        self._config,
                    ).run()
                )
                logger.info("a_m1_depth_feed_started",
                            max_symbols=self._config.get("depth_max_symbols", 300))

            # ── Live execution subsystem ─────────────────────────────────
            # The WS trader starts with allow_real_money=False. Any attempt
            # to place a real order will be refused until the /trading/toggle
            # endpoint explicitly flips it. Dry-run orders are always allowed.
            if _EXECUTION_AVAILABLE:
                try:
                    self._live_test_state = LiveTestState(self.cache, self.STRATEGY_ID)
                    await self._live_test_state.load()

                    self._latency_breaker = LatencyCircuitBreaker(
                        trip_p95_ms=float(self._config.get("latency_breaker_trip_ms", 40)),
                        reset_p95_ms=float(self._config.get("latency_breaker_reset_ms", 25)),
                    )

                    self._ws_trader = BinanceWSTrader(
                        allow_real_money=False,   # hard off at boot; API toggles
                    )
                    await self._ws_trader.start()

                    # Cross-process state sync: API writes to cache, we poll.
                    self._live_test_reload_task = asyncio.create_task(
                        self._live_test_state.reload_loop(interval_s=2.0)
                    )

                    hedge = HedgeEngine(self._ws_trader, kill_switch=self._ks)
                    self._live_exec = BoundedParallelExecutor(
                        ws_trader=self._ws_trader,
                        cache=self.cache,
                        hedge_engine=hedge,
                        breaker=self._latency_breaker,
                        kill_switch=self._ks,
                        fee_per_leg_pct=self._config.get("fee_per_leg_pct", 0.075),
                    )
                    logger.info("a_m1_live_exec_ready",
                                master=self._live_test_state.master_enabled(),
                                dry_run=self._live_test_state.dry_run_enabled(),
                                armed=self._live_test_state.armed_count())
                except Exception as e:
                    logger.warning("a_m1_live_exec_init_failed", error=str(e))

        except Exception as e:
            logger.error("a_m1_startup_error", error=str(e))
            raise

    def _hot_symbols_for_depth(self) -> List[str]:
        """Return symbols the depth feed should currently subscribe to.
        Union of leg symbols across the scanner's hot cache (if built) or
        the full triangle list otherwise. Duplicate-free, order stable."""
        scanner = getattr(self, "_scanner", None)
        if scanner is None:
            return []
        tris = scanner._hot_cache or scanner.triangles
        seen: Set[str] = set()
        out: List[str] = []
        for t in tris:
            for s in (t.leg1_symbol, t.leg2_symbol, t.leg3_symbol):
                if s not in seen:
                    seen.add(s)
                    out.append(s)
        return out

    async def on_market_signal(
        self,
        market: UnifiedMarket,
        allocated_usdc: float,
    ) -> Optional[TradeDecision]:
        """
        Called by router when a market opportunity is detected.
        For A_M1, we scan all triangles independently.
        Returns TradeDecision if a profitable triangle is found, else None.
        """
        try:
            # Check kill switch
            if self._ks and await self._ks.should_trade(self.STRATEGY_ID):
                return None

            # Throttle: don't scan more than every 100ms
            now = time.perf_counter()
            if now - self._last_execution_time < 0.1:
                return None
            self._last_execution_time = now

            # Need scanner to be initialized
            if not self._scanner:
                return None

            # Refresh graph if stale
            if self._graph and self._graph.needs_refresh():
                logger.info("a_m1_graph_stale_refreshing")
                await self._graph.build()
                triangles = self._discoverer.discover_all()
                self._scanner = DynamicTriangleScanner(triangles, self.cache, self._config)

            # Scan all triangles for best opportunity
            opportunity = await self._scanner.find_best_opportunity()

            # Update cache with recent evaluations for dashboard (non-blocking with timeout)
            if opportunity:
                try:
                    # Track top opportunities
                    top_opps = await asyncio.wait_for(self.cache.get("a_m1:opportunities:top"), timeout=1.0) or []
                    top_opps.append({
                        "triangle_id": opportunity.triangle.description(),
                        "net_profit_pct": opportunity.net_profit_pct,
                        "gross_profit_usdc": opportunity.expected_profit_usdc,
                        "last_check_ms": int(time.time() * 1000),
                    })
                    # Keep only top 20
                    top_opps = sorted(top_opps, key=lambda x: x["net_profit_pct"], reverse=True)[:20]
                    await asyncio.wait_for(self.cache.set("a_m1:opportunities:top", top_opps, ttl=60), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass  # Cache update failed, continue anyway

            if not opportunity:
                return None

            if opportunity.net_profit_pct <= self._config.get("min_net_profit_pct", 0.08):
                return None

            # Size position via Kelly criterion
            trade_size = min(
                allocated_usdc * 0.25,
                self._config.get("max_trade_size_usdc", 5_000.0),
            )
            trade_size = max(trade_size, self._config.get("min_trade_size_usdc", 50.0))

            # Execute the paper trade (background)
            asyncio.create_task(self.execute_signal({
                "opportunity": opportunity,
                "trigger": "MARKET_SIGNAL",
            }))

            # Return decision for logging
            return TradeDecision(
                symbol=opportunity.triangle.leg1_symbol,
                exchange="binance",
                direction="ARB",
                size_usdc=trade_size,
                leverage=1.0,
                ai_confidence=0.99,
                reasoning=f"Triangle: {opportunity.triangle.description()} | "
                          f"Gap: {opportunity.net_profit_pct:.2f}% | "
                          f"Expected: ${opportunity.expected_profit_usdc:.2f}",
                edge_detected=opportunity.net_profit_pct / 100.0,
                version_tag=self.VERSION,
            )

        except Exception as e:
            logger.error("a_m1_signal_error", error=str(e))
            return None

    async def execute_signal(self, signal: dict) -> None:
        """Route a triangle signal to the right executor.

        Priority order:
          1. If LiveTestState says "fire live next" (master on + armed > 0 +
             not in cooldown) → route to BoundedParallelExecutor. Mode is
             'live_dry_run' or 'live_test' depending on dry_run toggle.
          2. Otherwise → paper simulator (always safe, no money).

        The dashboard can arm single or multi-shot fires via the API. Each
        fire decrements armed_count; when 0, we fall back to paper even if
        master is still on. This is the "Test Latency" button."""
        try:
            opportunity = signal.get("opportunity")
            if not opportunity:
                return

            route_live = (
                self._live_exec is not None
                and self._live_test_state is not None
                and self._live_test_state.should_fire_live()
            )

            if route_live:
                await self._execute_live_test(opportunity)
                return

            # ── Paper path (default) ─────────────────────────────────────
            result = await self._paper_sim.simulate_execution(opportunity)
            self._paper_trades.append(result)
            asyncio.create_task(self._log_trade_result(result, opportunity))

            logger.info(
                "a_m1_trade_executed",
                mode="paper",
                triangle=opportunity.triangle.description(),
                expected_pct=round(result.expected_net_pct, 4),
                actual_pct=round(result.actual_net_pct, 4),
                required_pct=round(result.required_edge_pct, 4),
                profit_usdc=round(result.net_profit_usdc, 4),
                slip_bps=result.per_leg_slippage_bps,
                latency_ms=round(result.execution_ms, 2),
                lat_class=result.latency_classification,
                outcome=result.outcome_status,
            )

        except Exception as e:
            logger.error("a_m1_execute_error", error=str(e))

    async def _execute_live_test(self, opportunity: "TriangleOpportunity") -> None:
        """Route one armed opportunity through the bounded-parallel live
        executor. After completion, record_fire() decrements armed_count."""
        state = self._live_test_state
        is_dry = state.dry_run_enabled()
        exec_mode = "live_dry_run" if is_dry else "live_test"
        size_usdc = state.test_size_usdc()

        try:
            if not is_dry:
                # Hard sanity check: size must be ≤ $100 in live-test mode.
                # Real-live (not test) routing bypasses this via a future
                # production entry point, not this function.
                size_usdc = min(size_usdc, 100.0)

            # Propagate real-money gate to the WS trader. Only flipped True
            # when the user has explicitly disabled dry-run via the API.
            self._ws_trader.set_allow_real_money(not is_dry)

            logger.info("a_m1_live_fire_start",
                        mode=exec_mode,
                        size_usdc=size_usdc,
                        triangle=opportunity.triangle.description(),
                        armed_before=state.armed_count())

            report = await self._live_exec.execute(
                opportunity,
                trade_size_usdc=size_usdc,
                execution_mode=exec_mode,
            )

            # Translate ExecutionReport → TradeResult (reuse existing logger path)
            result = self._report_to_trade_result(report, opportunity)
            self._paper_trades.append(result)  # also appended for unified stats
            asyncio.create_task(self._log_trade_result(result, opportunity))

            # Decrement armed_count + persist
            await state.record_fire({
                "outcome": report.outcome_status,
                "mode": exec_mode,
                "pnl_usdc": report.net_pnl_usdc,
                "pnl_pct": report.net_pnl_pct,
                "latency_ms": report.total_latency_ms,
                "triangle": opportunity.triangle.description(),
                "ts": time.time(),
            })

            logger.info("a_m1_live_fire_done",
                        mode=exec_mode,
                        outcome=report.outcome_status,
                        pnl_usdc=round(report.net_pnl_usdc, 4),
                        latency_ms=round(report.total_latency_ms, 2),
                        armed_after=state.armed_count())
        except Exception as e:
            logger.error("a_m1_live_fire_error", error=str(e),
                         mode=exec_mode)
            # Even on failure, decrement — don't loop on a broken opportunity
            try: await state.record_fire({"outcome": "FAILED", "error": str(e),
                                           "ts": time.time()})
            except Exception: pass

    def _report_to_trade_result(self, report, opportunity) -> "TradeResult":
        """Bridge ExecutionReport → existing TradeResult row so the logger
        and dashboard schema remain a single format."""
        # Success = COMPLETE + positive PnL
        success = (report.outcome_status == "COMPLETE"
                   and report.net_pnl_usdc > 0)
        lat = report.total_latency_ms
        latency_class = (
            "fast"    if lat < 10  else
            "normal"  if lat < 20  else
            "slow"    if lat < 40  else
            "timeout"
        )
        return TradeResult(
            triangle_id=report.triangle_id,
            success=success,
            net_profit_usdc=report.net_pnl_usdc,
            net_profit_pct=report.net_pnl_pct,
            execution_ms=report.total_latency_ms,
            fill_prices=dict(report.actual_fill_prices),
            trade_size_usdc=report.trade_size_usdc,
            is_paper=(report.execution_mode == "live_dry_run"),  # dry-run doesn't move money
            error=report.error,
            execution_mode=report.execution_mode,
            scanner_prices=dict(report.scanner_prices),
            actual_fill_prices=dict(report.actual_fill_prices),
            per_leg_slippage_bps=dict(report.per_leg_slippage_bps),
            per_leg_latency_ms=dict(report.per_leg_latency_ms),
            per_leg_status=dict(report.per_leg_status),
            expected_net_pct=report.expected_pnl_pct,
            actual_net_pct=report.net_pnl_pct,
            required_edge_pct=opportunity.triangle.required_edge_pct,
            expected_pnl_usdc=report.expected_pnl_usdc,
            fees_paid_usdc=report.fees_paid_usdc,
            edge_lost_to_slippage_pct=report.expected_pnl_pct - report.net_pnl_pct,
            outcome_status=report.outcome_status,
            latency_classification=latency_class,
        )

    async def _log_trade_result(self, result: TradeResult, opportunity: TriangleOpportunity) -> None:
        """Write trade result to Supabase and update strategy_plugins overview counters."""
        loop = asyncio.get_event_loop()

        # 1. Insert into strategy_executions (trade history, Approach D schema)
        # Historic fields retained for dashboard backward-compat; new fields
        # capture full execution reality (scanner vs actual, per-leg slippage,
        # latency, outcome status, edge-loss attribution).
        try:
            row = {
                # Legacy fields (kept so old dashboard queries still work)
                "strategy_id":      self.STRATEGY_ID,
                "triangle_id":      result.triangle_id,
                "is_paper":         result.is_paper,
                "net_profit_pct":   result.net_profit_pct,
                "net_profit_usdc":  result.net_profit_usdc,
                "trade_size_usdc":  result.trade_size_usdc,
                "execution_ms":     result.execution_ms,
                "status":           "success" if result.success else "failed",
                "error":            result.error,

                # Approach D rich schema — actual execution reality
                "execution_mode":       result.execution_mode,
                "outcome_status":       result.outcome_status,
                "latency_classification": result.latency_classification,
                "expected_net_pct":     result.expected_net_pct,
                "actual_net_pct":       result.actual_net_pct,
                "required_edge_pct":    result.required_edge_pct,
                "expected_pnl_usdc":    result.expected_pnl_usdc,
                "fees_paid_usdc":       result.fees_paid_usdc,
                "edge_lost_to_slippage_pct": result.edge_lost_to_slippage_pct,
                # Dicts serialize as JSON; consumer (dashboard) parses.
                "scanner_prices":       result.scanner_prices,
                "actual_fill_prices":   result.actual_fill_prices,
                "per_leg_slippage_bps": result.per_leg_slippage_bps,
                "per_leg_latency_ms":   result.per_leg_latency_ms,
                "per_leg_status":       result.per_leg_status,
            }
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._db.table("strategy_executions").insert(row).execute()),
                timeout=5.0,
            )
        except Exception as e:
            logger.warning("a_m1_trade_log_error", error=str(e))

        # 2. Update strategy_plugins overview counters (what the dashboard overview reads)
        try:
            def _update_plugin_stats():
                # Read current counters
                row = self._db.table("strategy_plugins").select(
                    "paper_trades_count, live_trades_count, total_pnl_usdc, win_rate"
                ).eq("strategy_id", self.STRATEGY_ID).single().execute()

                if not row.data:
                    return

                paper = int(row.data.get("paper_trades_count") or 0)
                live  = int(row.data.get("live_trades_count") or 0)
                pnl   = float(row.data.get("total_pnl_usdc") or 0.0)
                wr    = float(row.data.get("win_rate") or 0.0)

                # Increment the right counter
                if result.is_paper:
                    total_before = paper
                    paper += 1
                    total_after = paper
                else:
                    total_before = live
                    live += 1
                    total_after = live

                # Recalculate win_rate incrementally.
                # Winner = trade that completed AND was net positive. Trades
                # that never filled (outcome=NO_FILL) don't count either way;
                # they're neither wins nor losses — no capital at risk.
                wins_before = round(wr * total_before)
                # Trades that had no capital outcome don't change win rate.
                if result.outcome_status == "NO_FILL":
                    total_after -= 1  # undo the increment; no-fills don't count
                    paper -= 1 if result.is_paper else 0
                    live -= 0 if result.is_paper else 1
                elif result.success and result.net_profit_usdc > 0:
                    wins_before += 1
                new_wr = round(wins_before / total_after, 4) if total_after > 0 else 0.0

                self._db.table("strategy_plugins").update({
                    "paper_trades_count": paper,
                    "live_trades_count":  live,
                    "total_pnl_usdc":     round(pnl + result.net_profit_usdc, 4),
                    "win_rate":           new_wr,
                }).eq("strategy_id", self.STRATEGY_ID).execute()

            await asyncio.wait_for(
                loop.run_in_executor(None, _update_plugin_stats),
                timeout=5.0,
            )
        except Exception as e:
            logger.warning("a_m1_plugin_stats_error", error=str(e))

    async def get_health_status(self) -> dict:
        """Return health status for dashboard."""
        return {
            "strategy_id": self.STRATEGY_ID,
            "status": "running",
            "pairs_discovered": len(self._graph.all_pairs) if self._graph else 0,
            "currencies": len(self._graph.adj) if self._graph else 0,
            "triangles_discovered": len(self._scanner.triangles) if self._scanner else 0,
            "paper_trades_total": len(self._paper_trades),
            "config": self._config,
            "last_best_profit_pct": max(
                (t.net_profit_pct for t in self._paper_trades if t.success),
                default=0.0,
            ),
        }

    async def check_promotion_readiness(self) -> dict:
        """Check if strategy is ready to promote from paper to live."""
        return await self._promotion_gates.check_all_gates()

    async def promote_to_live(self) -> bool:
        """Attempt to promote strategy from paper to live trading."""
        promoted = await self._promotion_gates.promote_to_live()
        if promoted:
            self._is_paper = False
            logger.info("a_m1_promoted_to_live")
        return promoted

    async def run_forever(self) -> None:
        """
        Independent scanning loop for A_M1.
        Continuously scans all triangles without waiting for market signals.
        """
        logger.info("a_m1_own_loop_started")
        _last_diagnostic_ns = time.monotonic_ns()  # Skip first beat — wait 3s so BookTicker can populate L1
        _last_config_refresh_ns = time.monotonic_ns()
        _scan_count = 0
        _best_profit_seen = 0.0
        _prices_found = 0
        # Per-triangle cooldown: triangle_id → monotonic timestamp of last execution
        # Prevents the same triangle from firing multiple times before the first trade settles
        _triangle_last_executed: dict = {}
        _TRIANGLE_COOLDOWN_S = 5.0  # Seconds to block a triangle after execution
        while True:
            try:
                # Throttle scanning to avoid hammering the system
                await asyncio.sleep(0.1)  # 100ms between scans

                # Check kill switch
                if self._ks:
                    can_trade, reason = self._ks.pre_trade_check(self.STRATEGY_ID, 100.0)
                    if not can_trade:
                        await asyncio.sleep(1)
                        continue

                # Need scanner to be initialized
                if not self._scanner:
                    continue

                # Refresh capital allocation every 5 seconds (not every 100ms)
                now_ns = time.monotonic_ns()
                if now_ns - self._last_capital_refresh_ns > 5_000_000_000:  # 5 seconds
                    self._cached_capital = await self._get_capital_allocation()
                    self._last_capital_refresh_ns = now_ns

                if self._cached_capital <= 0:
                    continue

                # Scan all triangles for best opportunity
                opportunity = await self._scanner.find_best_opportunity()
                _scan_count += 1

                # Diagnostic log every 3 seconds — shows scanner is alive + market state
                if now_ns - _last_diagnostic_ns > 3_000_000_000:
                    # Check L1 cache DIRECTLY (no await, no Redis) for instant accurate read
                    sample_tri = self._scanner.triangles[0] if self._scanner.triangles else None
                    has_prices_l1 = False
                    if sample_tri and hasattr(self.cache, '_L1'):
                        l1_key = sample_tri.leg1_key
                        l1_entry = self.cache._L1.get(l1_key)
                        if l1_entry:
                            val, expiry = l1_entry
                            has_prices_l1 = time.monotonic() < expiry
                    # Count priced triangles — sample 200 for speed, also log total discovered
                    total_triangles = len(self._scanner.triangles) if self._scanner else 0
                    priced_count = 0
                    sample_size = min(200, total_triangles)
                    if hasattr(self.cache, '_L1') and total_triangles:
                        now_mono = time.monotonic()
                        for tri in self._scanner.triangles[:sample_size]:
                            e1 = self.cache._L1.get(tri.leg1_key)
                            e2 = self.cache._L1.get(tri.leg2_key)
                            e3 = self.cache._L1.get(tri.leg3_key)
                            if (e1 and now_mono < e1[1] and
                                e2 and now_mono < e2[1] and
                                e3 and now_mono < e3[1]):
                                priced_count += 1
                    # Read scanner diagnostics: best profit across ALL checked triangles (even negative)
                    scan_best = round(self._scanner._last_scan_best_pct, 4) if self._scanner._last_scan_best_pct > -999 else None
                    scan_best_tri = self._scanner._last_scan_best_tri or "n/a"
                    scan_checked = self._scanner._last_scan_checked
                    logger.info(
                        "a_m1_scanner_heartbeat",
                        scans=_scan_count,
                        best_profit_pct=round(_best_profit_seen, 4),
                        best_all_pct=scan_best,
                        best_all_tri=scan_best_tri,
                        checked=scan_checked,
                        capital_usdc=round(self._cached_capital, 2),
                        total_triangles=total_triangles,
                        priced_of_sample=f"{priced_count}/{sample_size}",
                        l1_total_keys=len(self.cache._L1) if hasattr(self.cache, '_L1') else -1,
                    )
                    # Write best profit to cache for dashboard (non-blocking, best-effort)
                    try:
                        self.cache._L1["a_m1:best_profit"] = (
                            {"best_profit_pct": scan_best, "best_triangle": scan_best_tri, "checked_count": scan_checked},
                            time.monotonic() + 60,
                        )
                    except Exception:
                        pass

                    _scan_count = 0
                    _best_profit_seen = 0.0
                    # Reset scanner diagnostics for next interval
                    self._scanner._last_scan_best_pct = -999.0
                    self._scanner._last_scan_best_tri = ""
                    self._scanner._last_scan_checked = 0
                    _last_diagnostic_ns = now_ns

                    # Refresh config from cache every 60s (scanner.py syncs Supabase→cache every 30s)
                    if now_ns - _last_config_refresh_ns > 60_000_000_000:
                        try:
                            cached_cfg = await asyncio.wait_for(
                                self.cache.get(f"strategy_config:{self.STRATEGY_ID}"),
                                timeout=2.0
                            )
                            if cached_cfg and isinstance(cached_cfg, dict) and cached_cfg:
                                self._config.update(cached_cfg)
                                logger.info("a_m1_config_refreshed", config=self._config)
                        except Exception:
                            pass
                        _last_config_refresh_ns = now_ns

                if not opportunity:
                    continue

                _best_profit_seen = max(_best_profit_seen, opportunity.net_profit_pct)

                # Check minimum profit threshold
                if opportunity.net_profit_pct <= self._config.get("min_net_profit_pct", 0.02):
                    continue

                # Per-triangle cooldown — prevent re-entry before the previous trade settles
                tri_id = opportunity.triangle.description()
                now_s = time.monotonic()
                last_exec = _triangle_last_executed.get(tri_id, 0.0)
                if now_s - last_exec < _TRIANGLE_COOLDOWN_S:
                    continue  # Same triangle already fired recently — skip

                _triangle_last_executed[tri_id] = now_s

                # Prune stale cooldown entries (keep dict small)
                if len(_triangle_last_executed) > 100:
                    cutoff = now_s - _TRIANGLE_COOLDOWN_S
                    _triangle_last_executed = {k: v for k, v in _triangle_last_executed.items() if v > cutoff}

                # Log the scan
                logger.info(
                    "a_m1_opportunity_found",
                    triangle=tri_id,
                    profit_pct=opportunity.net_profit_pct,
                )

                # Size position via Kelly
                trade_size = min(
                    self._cached_capital * 0.25,
                    self._config.get("max_trade_size_usdc", 5_000.0),
                )
                trade_size = max(trade_size, self._config.get("min_trade_size_usdc", 50.0))

                # Execute paper trade
                asyncio.create_task(self.execute_signal({
                    "opportunity": opportunity,
                    "trigger": "CONTINUOUS_SCAN",
                }))

            except Exception as e:
                logger.error("a_m1_loop_error", error=str(e))
                await asyncio.sleep(1)

    async def _get_capital_allocation(self) -> float:
        """Get allocated capital for this strategy."""
        if not self.cache:
            return 1000.0  # Safe default for paper trading

        try:
            # Try to get total capital first (set by scanner)
            total_capital = await asyncio.wait_for(
                self.cache.get("capital:current_usdc"),
                timeout=1.0
            )
            if total_capital and isinstance(total_capital, (int, float)):
                # Use a conservative allocation: 25% of total capital per strategy
                return float(total_capital) * 0.25
        except asyncio.TimeoutError:
            pass  # Fall through to default
        except Exception:
            pass  # Fall through to default

        # Fallback: reasonable default for paper trading
        return 1000.0
