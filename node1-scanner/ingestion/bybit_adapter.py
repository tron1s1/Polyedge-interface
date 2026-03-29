"""
Bybit adapter. Focuses on perpetual futures and funding rates.
Funding rate harvest (A_M2) depends entirely on this adapter.
"""
import os
from typing import List, Dict
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket, FundingData
from latency.base_methods import ConnectionPool, TieredCache
import structlog

logger = structlog.get_logger()

BYBIT_REST = "https://api.bybit.com"


class BybitAdapter(BaseMarketAdapter):

    def __init__(self, cache: TieredCache):
        self._cache = cache
        self._api_key = os.getenv("BYBIT_API_KEY", "")
        self._private_key_path = os.getenv("BYBIT_PRIVATE_KEY_PATH", "")

        # Load RSA private key once at startup (for signed requests / order placement)
        self._private_key = None
        if self._private_key_path:
            try:
                with open(self._private_key_path, "r") as f:
                    self._private_key = f.read()
            except FileNotFoundError:
                logger.warning("bybit_private_key_not_found",
                               path=self._private_key_path)

    @property
    def exchange_name(self) -> str:
        return "bybit"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        """Fetch Bybit linear perpetual markets with funding rates."""
        session = await ConnectionPool.get()
        markets = []

        try:
            # Get tickers (includes funding rate)
            resp = await session.get(
                f"{BYBIT_REST}/v5/market/tickers",
                params={"category": "linear"}
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("result", {}).get("list", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue

                funding_rate = float(item.get("fundingRate", 0) or 0)
                price = float(item.get("lastPrice", 0))

                market = UnifiedMarket(
                    market_id=f"bybit_{symbol}",
                    exchange="bybit",
                    symbol=symbol,
                    base_asset=symbol.replace("USDT", ""),
                    quote_asset="USDT",
                    market_type="perpetual",
                    is_perpetual=True,
                    price=price,
                    volume_24h=float(item.get("volume24h", 0)) * price,
                    open_interest=float(item.get("openInterest", 0)),
                    funding=FundingData(
                        current_rate=funding_rate,
                        rate_annualised=funding_rate * 3 * 365,
                    ),
                    last_updated=datetime.utcnow(),
                )
                market.bybit_price = price

                # Cache funding rate — key for A_M2 strategy
                await self._cache.set(f"funding:bybit:{symbol}", {
                    "rate": funding_rate,
                    "annualised": funding_rate * 3 * 365,
                    "8h_payment": funding_rate,  # positive = longs pay shorts
                    "price": price,
                })
                # Cache price so A_M2 can trade symbols not listed on Binance
                await self._cache.set(f"price:bybit:{symbol}", price)

                markets.append(market)

            logger.info("bybit_markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("bybit_fetch_error", error=str(e))
            return []

    async def fetch_funding_rates(self) -> Dict[str, FundingData]:
        """Fetch funding rates separately for enrichment."""
        session = await ConnectionPool.get()
        try:
            resp = await session.get(
                f"{BYBIT_REST}/v5/market/tickers",
                params={"category": "linear"}
            )
            resp.raise_for_status()
            data = resp.json()

            rates = {}
            for item in data.get("result", {}).get("list", []):
                symbol = item.get("symbol", "")
                rate = float(item.get("fundingRate", 0) or 0)
                rates[symbol] = FundingData(
                    current_rate=rate,
                    rate_annualised=rate * 3 * 365,
                )
            return rates
        except Exception as e:
            logger.error("bybit_funding_error", error=str(e))
            return {}

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        session = await ConnectionPool.get()
        resp = await session.get(
            f"{BYBIT_REST}/v5/market/tickers",
            params={"category": "linear", "symbol": symbol}
        )
        items = resp.json().get("result", {}).get("list", [])
        if items:
            item = items[0]
            return UnifiedMarket(
                market_id=f"bybit_{symbol}",
                exchange="bybit",
                symbol=symbol,
                price=float(item.get("lastPrice", 0)),
                market_type="perpetual",
                is_perpetual=True,
                funding=FundingData(
                    current_rate=float(item.get("fundingRate", 0)),
                    rate_annualised=float(item.get("fundingRate", 0)) * 3 * 365,
                ),
            )
        return UnifiedMarket(market_id=f"bybit_{symbol}", exchange="bybit", symbol=symbol)

    async def is_healthy(self) -> bool:
        try:
            session = await ConnectionPool.get()
            resp = await session.get(f"{BYBIT_REST}/v5/market/time")
            return resp.status_code == 200
        except Exception:
            return False
