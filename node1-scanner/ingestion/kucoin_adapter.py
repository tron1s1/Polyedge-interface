"""
KuCoin adapter — spot price feed for CEX arb (A_CEX_cross_arb).
No auth required for market data. KuCoin uses BTC-USDT symbol format;
we normalise to BTCUSDT to match Binance/Bybit convention.
Public REST: https://api.kucoin.com/api/v1/market/allTickers
"""
from typing import List
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import ConnectionPool, TieredCache
import structlog

logger = structlog.get_logger()

KUCOIN_REST = "https://api.kucoin.com"


class KuCoinAdapter(BaseMarketAdapter):
    """
    Fetches all USDT spot tickers from KuCoin and caches prices under
    price:kucoin:{SYMBOL} — e.g. price:kucoin:BTCUSDT.
    """

    def __init__(self, cache: TieredCache):
        self._cache = cache

    @property
    def exchange_name(self) -> str:
        return "kucoin"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        """
        Fetch all USDT spot tickers from KuCoin allTickers endpoint.
        Normalises KuCoin's BTC-USDT format → BTCUSDT.
        """
        session = await ConnectionPool.get()
        markets = []

        try:
            resp = await session.get(
                f"{KUCOIN_REST}/api/v1/market/allTickers",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            tickers = data.get("data", {}).get("ticker", [])
            for item in tickers:
                raw_symbol = item.get("symbol", "")  # e.g. BTC-USDT
                if not raw_symbol.endswith("-USDT"):
                    continue

                # Normalise: BTC-USDT → BTCUSDT
                symbol = raw_symbol.replace("-", "")

                last_str = item.get("last") or item.get("lastPrice") or "0"
                try:
                    price = float(last_str)
                except (ValueError, TypeError):
                    continue
                if price <= 0:
                    continue

                vol_str = item.get("volValue") or item.get("vol") or "0"
                try:
                    volume_24h = float(vol_str)
                except (ValueError, TypeError):
                    volume_24h = 0.0

                market = UnifiedMarket(
                    market_id=f"kucoin_{symbol}",
                    exchange="kucoin",
                    symbol=symbol,
                    base_asset=symbol.replace("USDT", ""),
                    quote_asset="USDT",
                    market_type="spot",
                    is_perpetual=False,
                    price=price,
                    volume_24h=volume_24h,
                    last_updated=datetime.utcnow(),
                )
                market.kucoin_price = price

                # Cache price — used by A_CEX_cross_arb._check_pair("kucoin", ...)
                await self._cache.set(f"price:kucoin:{symbol}", price)

                markets.append(market)

            logger.info("kucoin_markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("kucoin_fetch_error", error=str(e))
            return []

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        """Fetch a single symbol ticker from KuCoin. symbol in BTCUSDT format."""
        session = await ConnectionPool.get()
        kucoin_symbol = symbol[:-4] + "-USDT" if symbol.endswith("USDT") else symbol
        try:
            resp = await session.get(
                f"{KUCOIN_REST}/api/v1/market/stats",
                params={"symbol": kucoin_symbol},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            price = float(data.get("last") or 0)
            await self._cache.set(f"price:kucoin:{symbol}", price)
            return UnifiedMarket(
                market_id=f"kucoin_{symbol}",
                exchange="kucoin",
                symbol=symbol,
                base_asset=symbol.replace("USDT", ""),
                quote_asset="USDT",
                market_type="spot",
                is_perpetual=False,
                price=price,
                last_updated=datetime.utcnow(),
            )
        except Exception as e:
            logger.error("kucoin_ticker_error", symbol=symbol, error=str(e))
            return UnifiedMarket(
                market_id=f"kucoin_{symbol}", exchange="kucoin", symbol=symbol,
                base_asset="", quote_asset="USDT", market_type="spot",
                is_perpetual=False, price=0.0, last_updated=datetime.utcnow(),
            )

    async def is_healthy(self) -> bool:
        session = await ConnectionPool.get()
        try:
            resp = await session.get(
                f"{KUCOIN_REST}/api/v1/timestamp", timeout=5.0
            )
            return resp.status_code == 200
        except Exception:
            return False
