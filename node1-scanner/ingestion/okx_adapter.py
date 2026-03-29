"""
OKX adapter. Used as cross-exchange arb target vs Binance.
When OKX price differs from Binance by > 0.15%: A_CEX strategy fires.
"""
import os
from typing import List
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import ConnectionPool, TieredCache
import structlog

logger = structlog.get_logger()

OKX_REST = "https://www.okx.com"


class OKXAdapter(BaseMarketAdapter):

    def __init__(self, cache: TieredCache):
        self._cache = cache

    @property
    def exchange_name(self) -> str:
        return "okx"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        session = await ConnectionPool.get()
        markets = []
        try:
            resp = await session.get(f"{OKX_REST}/api/v5/market/tickers?instType=SPOT")
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("data", []):
                inst_id = item.get("instId", "")
                if not inst_id.endswith("-USDT"):
                    continue

                symbol = inst_id.replace("-", "")  # BTC-USDT → BTCUSDT
                price = float(item.get("last", 0))

                market = UnifiedMarket(
                    market_id=f"okx_{symbol}",
                    exchange="okx",
                    symbol=symbol,
                    price=price,
                    volume_24h=float(item.get("volCcy24h", 0)),
                    last_updated=datetime.utcnow(),
                )
                market.okx_price = price
                await self._cache.set(f"price:okx:{symbol}", price)
                markets.append(market)

            logger.info("okx_markets_fetched", count=len(markets))
            return markets
        except Exception as e:
            logger.error("okx_fetch_error", error=str(e))
            return []

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        inst_id = symbol[:3] + "-" + symbol[3:]  # BTCUSDT → BTC-USDT
        session = await ConnectionPool.get()
        resp = await session.get(f"{OKX_REST}/api/v5/market/ticker?instId={inst_id}")
        data = resp.json().get("data", [{}])
        price = float(data[0].get("last", 0)) if data else 0
        return UnifiedMarket(market_id=f"okx_{symbol}", exchange="okx", symbol=symbol, price=price)

    async def is_healthy(self) -> bool:
        try:
            session = await ConnectionPool.get()
            resp = await session.get(f"{OKX_REST}/api/v5/public/time")
            return resp.status_code == 200
        except Exception:
            return False
