"""
Crypto.com Exchange adapter — spot price feed for CEX arb (A_CEX_cross_arb).
Public market data requires no auth.
Order signing (live mode) uses CRYPTOCOM_API_KEY / CRYPTOCOM_API_SECRET from .env.
Public REST: https://api.crypto.com/exchange/v1/public/get-tickers

Crypto.com uses BTC_USDT symbol format (underscore).
We normalise to BTCUSDT to match Binance/Bybit/KuCoin convention.
"""
import os
import hmac
import hashlib
import time
from typing import List
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import ConnectionPool, TieredCache
import structlog

logger = structlog.get_logger()

CRYPTOCOM_REST = "https://api.crypto.com/exchange/v1"


class CryptocomAdapter(BaseMarketAdapter):
    """
    Fetches all USDT spot tickers from Crypto.com and caches prices under
    price:cryptocom:{SYMBOL} — e.g. price:cryptocom:BTCUSDT.
    API credentials loaded for live order placement.
    """

    def __init__(self, cache: TieredCache):
        self._cache = cache
        self._api_key    = os.getenv("CRYPTOCOM_API_KEY", "")
        self._api_secret = os.getenv("CRYPTOCOM_API_SECRET", "")
        if self._api_key:
            logger.info("cryptocom_credentials_loaded",
                        key_prefix=self._api_key[:6] + "***")
        else:
            logger.warning("cryptocom_no_credentials",
                           note="public data only; set CRYPTOCOM_API_KEY for live trading")

    @property
    def exchange_name(self) -> str:
        return "cryptocom"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        """
        Fetch all tickers from Crypto.com public API.
        Normalises BTC_USDT → BTCUSDT. Filters to USDT pairs only.
        """
        session = await ConnectionPool.get()
        markets = []

        try:
            resp = await session.get(
                f"{CRYPTOCOM_REST}/public/get-tickers",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            tickers = data.get("result", {}).get("data", [])
            for item in tickers:
                raw_symbol = item.get("i", "")  # e.g. BTC_USDT or BTCUSDT-PERP
                if not raw_symbol.endswith("_USDT"):
                    continue

                # Normalise: BTC_USDT → BTCUSDT
                symbol = raw_symbol.replace("_USDT", "USDT")

                # last price: field 'a' (best ask) or 'k' (last traded price)
                price_str = item.get("a") or item.get("k") or "0"
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    continue
                if price <= 0:
                    continue

                # 24h volume in quote currency
                vol_str = item.get("vv") or item.get("v") or "0"
                try:
                    volume_24h = float(vol_str)
                except (ValueError, TypeError):
                    volume_24h = 0.0

                market = UnifiedMarket(
                    market_id=f"cryptocom_{symbol}",
                    exchange="cryptocom",
                    symbol=symbol,
                    base_asset=symbol.replace("USDT", ""),
                    quote_asset="USDT",
                    market_type="spot",
                    is_perpetual=False,
                    price=price,
                    volume_24h=volume_24h,
                    last_updated=datetime.utcnow(),
                )
                market.cryptocom_price = price

                # Cache price — used by A_CEX_cross_arb._check_pair("cryptocom", ...)
                await self._cache.set(f"price:cryptocom:{symbol}", price)

                markets.append(market)

            logger.info("cryptocom_markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("cryptocom_fetch_error", error=str(e))
            return []

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        """Fetch a single symbol ticker. symbol in BTCUSDT format."""
        session = await ConnectionPool.get()
        # Crypto.com format: BTC_USDT
        cc_symbol = symbol[:-4] + "_USDT" if symbol.endswith("USDT") else symbol
        try:
            resp = await session.get(
                f"{CRYPTOCOM_REST}/public/get-tickers",
                params={"instrument_name": cc_symbol},
                timeout=5.0,
            )
            resp.raise_for_status()
            items = resp.json().get("result", {}).get("data", [])
            price = float(items[0].get("a") or items[0].get("k") or 0) if items else 0.0
            await self._cache.set(f"price:cryptocom:{symbol}", price)
            return UnifiedMarket(
                market_id=f"cryptocom_{symbol}",
                exchange="cryptocom",
                symbol=symbol,
                base_asset=symbol.replace("USDT", ""),
                quote_asset="USDT",
                market_type="spot",
                is_perpetual=False,
                price=price,
                last_updated=datetime.utcnow(),
            )
        except Exception as e:
            logger.error("cryptocom_ticker_error", symbol=symbol, error=str(e))
            return UnifiedMarket(
                market_id=f"cryptocom_{symbol}", exchange="cryptocom", symbol=symbol,
                base_asset="", quote_asset="USDT", market_type="spot",
                is_perpetual=False, price=0.0, last_updated=datetime.utcnow(),
            )

    def _sign_request(self, method: str, params: dict) -> dict:
        """
        Build a signed private-API request payload.
        https://exchange-docs.crypto.com/exchange/v1/rest-ws/index.html#digital-signature
        """
        nonce = str(int(time.time() * 1000))
        request_id = nonce
        param_str = "".join(
            f"{k}{v}" for k, v in sorted(params.items())
        )
        sig_payload = method + request_id + self._api_key + param_str + nonce
        sig = hmac.new(
            self._api_secret.encode("utf-8"),
            sig_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "id": request_id,
            "method": method,
            "api_key": self._api_key,
            "params": params,
            "nonce": nonce,
            "sig": sig,
        }

    async def is_healthy(self) -> bool:
        session = await ConnectionPool.get()
        try:
            resp = await session.get(
                f"{CRYPTOCOM_REST}/public/get-instruments",
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception:
            return False
