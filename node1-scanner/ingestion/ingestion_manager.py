"""
MarketIngester — runs all adapters in parallel, returns merged UnifiedMarket list.
This is what the scanner calls to get all markets across all exchanges.
Performance target: complete in < 500ms for all exchanges combined.

Exchanges:
  Binance   — primary, spot + futures, triangular arb source
  Bybit     — perpetuals + spot, funding rates for A_M2
  KuCoin    — spot, price:kucoin:* cache for A_CEX arb
  Coinbase  — spot, price:coinbase:* cache for A_CEX arb
  OKX       — disabled (geo-blocked in SG/IN; kept for future re-enable)
"""
import asyncio
from typing import List, Dict
from datetime import datetime
from ingestion.market_normalizer import UnifiedMarket
from ingestion.binance_adapter import BinanceAdapter
from ingestion.bybit_adapter import BybitAdapter
from ingestion.kucoin_adapter import KuCoinAdapter
from ingestion.coinbase_adapter import CoinbaseAdapter
from ingestion.cryptocom_adapter import CryptocomAdapter
from latency.base_methods import TieredCache, process_all_parallel
import structlog

logger = structlog.get_logger()

# All active exchanges in ingestion order
ACTIVE_EXCHANGES = ["binance", "bybit", "kucoin", "coinbase", "cryptocom"]


class MarketIngester:
    """
    Runs all exchange adapters in parallel.
    Merges results into a unified market list.
    Enriches with cross-exchange price gaps (key for A_CEX strategy).
    """

    def __init__(self, cache: TieredCache, event_bus=None):
        self.binance   = BinanceAdapter(cache, event_bus)
        self.bybit     = BybitAdapter(cache)
        self.kucoin    = KuCoinAdapter(cache)
        self.coinbase  = CoinbaseAdapter(cache)
        self.cryptocom = CryptocomAdapter(cache)
        self._cache = cache
        self._last_full_fetch: Dict[str, datetime] = {}
        self._market_cache: List[UnifiedMarket] = []

    async def get_all_markets(self) -> List[UnifiedMarket]:
        """
        Fetch from all exchanges in parallel.
        Returns merged, enriched UnifiedMarket list.
        B1: asyncio.gather() — all exchanges simultaneously.
        """
        results = await asyncio.gather(
            self.binance.fetch_markets(),
            self.bybit.fetch_markets(),
            self.kucoin.fetch_markets(),
            self.coinbase.fetch_markets(),
            self.cryptocom.fetch_markets(),
            return_exceptions=True,
        )

        all_markets = []
        exchange_markets: Dict[str, Dict[str, UnifiedMarket]] = {}

        for exchange, result in zip(ACTIVE_EXCHANGES, results):
            if isinstance(result, Exception):
                logger.warning("exchange_fetch_failed", exchange=exchange, error=str(result))
                continue
            if not isinstance(result, list):
                continue
            exchange_markets[exchange] = {m.symbol: m for m in result}
            all_markets.extend(result)

        # Enrich: cross-exchange price gaps
        all_markets = await self._enrich_cross_exchange_gaps(all_markets, exchange_markets)

        # Enrich: triangular arb signals (Binance only)
        tri_opps = await self.binance.get_triangular_markets()
        for sym_a, sym_b, sym_c, gap_pct in tri_opps:
            for m in all_markets:
                if m.exchange == "binance" and m.symbol in [sym_a, sym_b, sym_c]:
                    m.triangular_gap_pct = gap_pct

        # Fetch funding rates (if Bybit data available)
        funding_rates = await self.bybit.fetch_funding_rates() if exchange_markets.get("bybit") else {}
        for m in all_markets:
            if m.is_perpetual and m.symbol in funding_rates:
                m.funding = funding_rates[m.symbol]

        self._market_cache = all_markets
        logger.info("ingestion_complete",
                    total_markets=len(all_markets),
                    exchanges=list(exchange_markets.keys()))
        return all_markets

    async def _enrich_cross_exchange_gaps(
        self,
        markets: List[UnifiedMarket],
        exchange_markets: Dict[str, Dict[str, UnifiedMarket]]
    ) -> List[UnifiedMarket]:
        """
        For each symbol: find max price gap across all exchanges.
        Gap > 0.15% = A_CEX cross-exchange arb opportunity.
        Sets market.max_exchange_gap_pct and per-exchange price attributes.
        """
        symbol_prices: Dict[str, Dict[str, float]] = {}

        for exchange, mkt_dict in exchange_markets.items():
            for symbol, market in mkt_dict.items():
                if symbol not in symbol_prices:
                    symbol_prices[symbol] = {}
                symbol_prices[symbol][exchange] = market.price

        # Calculate gaps and stamp per-exchange prices on each market object
        for market in markets:
            prices = symbol_prices.get(market.symbol, {})
            if len(prices) < 2:
                continue

            price_values = list(prices.values())
            max_price = max(price_values)
            min_price = min(price_values)

            if min_price > 0:
                gap_pct = (max_price - min_price) / min_price * 100
                market.max_exchange_gap_pct = gap_pct

                # Stamp all exchange prices onto the market object
                market.binance_price   = prices.get("binance", 0)
                market.bybit_price     = prices.get("bybit", 0)
                market.kucoin_price    = prices.get("kucoin", 0)
                market.coinbase_price  = prices.get("coinbase", 0)
                market.cryptocom_price = prices.get("cryptocom", 0)

        return markets

    async def check_all_healthy(self) -> Dict[str, bool]:
        """Health check all adapters in parallel."""
        results = await asyncio.gather(
            self.binance.is_healthy(),
            self.bybit.is_healthy(),
            self.kucoin.is_healthy(),
            self.coinbase.is_healthy(),
            self.cryptocom.is_healthy(),
            return_exceptions=True,
        )
        return {
            ex: (r if not isinstance(r, Exception) else False)
            for ex, r in zip(ACTIVE_EXCHANGES, results)
        }
