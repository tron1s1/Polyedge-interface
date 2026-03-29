"""
UnifiedMarket — the single data schema used by ALL components.
Every exchange adapter outputs this exact structure.
Scanner, scorer, router, strategies all read from this.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class OrderBookDepth:
    """Snapshot of top-of-book liquidity."""
    best_bid: float = 0.0
    best_ask: float = 0.0
    bid_depth_10bps: float = 0.0   # Total USD within 0.1% of mid
    ask_depth_10bps: float = 0.0
    spread_pct: float = 0.0        # (ask - bid) / mid
    last_updated: Optional[datetime] = None


@dataclass
class FundingData:
    """Perpetual futures funding rate data."""
    current_rate: float = 0.0        # Per 8-hour period
    rate_annualised: float = 0.0     # = rate * 3 * 365
    next_funding_time: Optional[datetime] = None
    predicted_rate: float = 0.0


@dataclass
class UnifiedMarket:
    """
    Single market representation across all exchanges.
    All exchange adapters produce this. All downstream components consume it.
    """
    # ── Identity ──────────────────────────────────────────────
    market_id: str = ""               # Exchange-native ID
    exchange: str = ""                # 'binance' | 'bybit' | 'okx' | 'kucoin'
    symbol: str = ""                  # e.g. 'BTCUSDT', 'ETHUSDT'
    base_asset: str = ""              # e.g. 'BTC'
    quote_asset: str = ""             # e.g. 'USDT'
    market_type: str = "spot"         # 'spot' | 'perpetual' | 'futures' | 'options'

    # ── Pricing ───────────────────────────────────────────────
    price: float = 0.0                # Current mid price
    bid: float = 0.0
    ask: float = 0.0
    price_change_1h: float = 0.0      # % change vs 1h ago
    price_change_4h: float = 0.0
    price_change_24h: float = 0.0
    volume_24h: float = 0.0           # USD volume
    volume_1h: float = 0.0
    volume_ratio: float = 0.0         # 1h_vol / (24h_vol/24) — spike detector

    # ── Order book ────────────────────────────────────────────
    orderbook: OrderBookDepth = field(default_factory=OrderBookDepth)
    orderbook_imbalance: float = 0.0  # (bids - asks) / total, -1 to +1

    # ── Classification ────────────────────────────────────────
    category: str = "crypto"          # 'crypto' | 'defi' | 'options'
    is_crypto: bool = True
    is_perpetual: bool = False
    is_stablecoin: bool = False
    is_btc_ladder: bool = False        # Part of BTC price ladder
    ladder_strike: Optional[float] = None

    # ── Perpetual-specific ────────────────────────────────────
    funding: FundingData = field(default_factory=FundingData)
    open_interest: float = 0.0
    open_interest_change_24h: float = 0.0

    # ── Cross-exchange signals ────────────────────────────────
    # Set by enrichment pipeline
    binance_price: float = 0.0        # For cross-CEX arb
    bybit_price: float = 0.0
    okx_price: float = 0.0
    kucoin_price: float = 0.0
    max_exchange_gap_pct: float = 0.0 # Largest gap between any two exchanges

    # Triangular arb (Binance only)
    triangular_implied_price: float = 0.0  # What price SHOULD be via triangle
    triangular_gap_pct: float = 0.0        # Deviation from triangle parity

    # ── DeFi / on-chain signals ───────────────────────────────
    is_new_token: bool = False
    token_age_hours: float = 9999.0
    dev_wallet_sold_pct: float = 0.0  # Rug pull signal — skip if > 50%

    # ── News / sentiment signals ──────────────────────────────
    news_velocity: float = 0.0        # News mentions/hr in last 2h
    social_velocity: float = 0.0      # Reddit/Twitter posts/hr
    gdelt_tone_shift: float = 0.0     # GDELT sentiment change

    # ── Liquidation data (Coinglass) ──────────────────────────
    liquidation_clusters: List[Dict] = field(default_factory=list)
    nearest_cluster_distance_pct: float = 999.0

    # ── Fear/Greed ────────────────────────────────────────────
    fear_greed_index: int = 50
    fear_greed_classification: str = "Neutral"

    # ── Opportunity score (set by OpportunityScorer) ──────────
    opportunity_score: float = 0.0
    volume_modifier: float = 1.0      # 2.0 for < $5k vol markets
    suggested_strategies: List[str] = field(default_factory=list)

    # ── Metadata ──────────────────────────────────────────────
    last_updated: datetime = field(default_factory=datetime.utcnow)
    raw_data: Dict = field(default_factory=dict)  # Original exchange payload

    def to_dict(self) -> dict:
        """Convert to dict for cache storage and logging."""
        return {
            "market_id": self.market_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "price": self.price,
            "price_change_24h": self.price_change_24h,
            "volume_24h": self.volume_24h,
            "funding_rate": self.funding.current_rate,
            "funding_annualised": self.funding.rate_annualised,
            "max_exchange_gap_pct": self.max_exchange_gap_pct,
            "triangular_gap_pct": self.triangular_gap_pct,
            "opportunity_score": self.opportunity_score,
            "suggested_strategies": self.suggested_strategies,
            "last_updated": self.last_updated.isoformat(),
        }
