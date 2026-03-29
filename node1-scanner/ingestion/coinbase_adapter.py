"""
Coinbase Advanced Trade adapter — spot price feed for CEX arb (A_CEX_cross_arb).
No auth required for public market data.
Public REST: https://api.coinbase.com/api/v3/brokerage/market/products

Coinbase uses BTC-USDT product IDs. We normalise to BTCUSDT convention.
Note: Coinbase has fewer USDT pairs than Binance/Bybit/KuCoin; many assets
only have USD pairs. We filter to -USDT products only for apples-to-apples arb.
"""
from typing import List
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import ConnectionPool, TieredCache
import structlog

logger = structlog.get_logger()

COINBASE_REST = "https://api.coinbase.com"


class CoinbaseAdapter(BaseMarketAdapter):
    """
    Fetches USDT spot products from Coinbase and caches prices under
    price:coinbase:{SYMBOL} — e.g. price:coinbase:BTCUSDT.
    """

    def __init__(self, cache: TieredCache):
        self._cache = cache

    @property
    def exchange_name(self) -> str:
        return "coinbase"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        """
        Fetch all USDT spot products from Coinbase Advanced Trade API.
        Paginates if needed; Coinbase returns up to 250 products per call.
        """
        session = await ConnectionPool.get()
        markets = []
        cursor = None

        try:
            while True:
                params = {
                    "product_type": "SPOT",
                    "quote_currency_id": "USDT",
                    "limit": 250,
                }
                if cursor:
                    params["cursor"] = cursor

                resp = await session.get(
                    f"{COINBASE_REST}/api/v3/brokerage/market/products",
                    params=params,
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()

                products = data.get("products", [])
                for item in products:
                    product_id = item.get("product_id", "")  # e.g. BTC-USDT
                    if not product_id.endswith("-USDT"):
                        continue
                    if item.get("status", "") not in ("online", ""):
                        continue

                    # Normalise: BTC-USDT → BTCUSDT
                    symbol = product_id.replace("-", "")

                    price_str = item.get("price") or item.get("mid_market_price") or "0"
                    try:
                        price = float(price_str)
                    except (ValueError, TypeError):
                        continue
                    if price <= 0:
                        continue

                    vol_str = item.get("volume_24h") or "0"
                    try:
                        volume_24h = float(vol_str) * price
                    except (ValueError, TypeError):
                        volume_24h = 0.0

                    market = UnifiedMarket(
                        market_id=f"coinbase_{symbol}",
                        exchange="coinbase",
                        symbol=symbol,
                        base_asset=symbol.replace("USDT", ""),
                        quote_asset="USDT",
                        market_type="spot",
                        is_perpetual=False,
                        price=price,
                        volume_24h=volume_24h,
                        last_updated=datetime.utcnow(),
                    )
                    market.coinbase_price = price

                    # Cache price — used by A_CEX_cross_arb._check_pair("coinbase", ...)
                    await self._cache.set(f"price:coinbase:{symbol}", price)

                    markets.append(market)

                # Handle pagination
                has_next = data.get("has_next", False)
                cursor = data.get("cursor", None)
                if not has_next or not cursor:
                    break

            logger.info("coinbase_markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("coinbase_fetch_error", error=str(e))
            return []

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        """Fetch a single symbol ticker from Coinbase. symbol in BTCUSDT format."""
        session = await ConnectionPool.get()
        product_id = symbol[:-4] + "-USDT" if symbol.endswith("USDT") else symbol
        try:
            resp = await session.get(
                f"{COINBASE_REST}/api/v3/brokerage/market/products/{product_id}",
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            price = float(data.get("price") or data.get("mid_market_price") or 0)
            await self._cache.set(f"price:coinbase:{symbol}", price)
            return UnifiedMarket(
                market_id=f"coinbase_{symbol}",
                exchange="coinbase",
                symbol=symbol,
                base_asset=symbol.replace("USDT", ""),
                quote_asset="USDT",
                market_type="spot",
                is_perpetual=False,
                price=price,
                last_updated=datetime.utcnow(),
            )
        except Exception as e:
            logger.error("coinbase_ticker_error", symbol=symbol, error=str(e))
            return UnifiedMarket(
                market_id=f"coinbase_{symbol}", exchange="coinbase", symbol=symbol,
                base_asset="", quote_asset="USDT", market_type="spot",
                is_perpetual=False, price=0.0, last_updated=datetime.utcnow(),
            )

    async def is_healthy(self) -> bool:
        session = await ConnectionPool.get()
        try:
            resp = await session.get(
                f"{COINBASE_REST}/api/v3/brokerage/market/products",
                params={"product_type": "SPOT", "limit": 1},
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception:
            return False
