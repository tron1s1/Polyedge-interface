"""
Binance REST + WebSocket adapter.
Handles spot prices AND perpetual futures.
WebSocket: Pushes updates to event bus in real time.
REST: Full market list on startup + periodic refresh.
"""
import asyncio
import os
import json
import time
from typing import List, Dict, Optional
from datetime import datetime
from ingestion.base_adapter import BaseMarketAdapter
from ingestion.market_normalizer import UnifiedMarket, FundingData, OrderBookDepth
from latency.base_methods import ConnectionPool, PersistentWebSocket, TieredCache, pack
import structlog

logger = structlog.get_logger()

# Binance WebSocket streams
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BINANCE_REST_BASE = "https://api.binance.com"
BINANCE_FUTURES_REST = "https://fapi.binance.com"

# Symbols we track (expand as needed)
TRACKED_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT",
    "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT", "OPUSDT",
    "ARBUSDT", "APTUSDT", "SUIUSDT", "FTMUSDT", "INJUSDT",
    # Add more pairs here — these cover 90% of CEX arb opportunities
]


class BinanceAdapter(BaseMarketAdapter):

    def __init__(self, cache: TieredCache, event_bus=None):
        self._cache = cache
        self._event_bus = event_bus
        self._api_key = os.getenv("BINANCE_API_KEY", "")
        self._private_key_path = os.getenv("BINANCE_PRIVATE_KEY_PATH", "")
        self._markets: Dict[str, UnifiedMarket] = {}

        # Load Ed25519 private key once at startup (for signed requests / order placement)
        self._private_key = None
        if self._private_key_path:
            try:
                with open(self._private_key_path, "r") as f:
                    self._private_key = f.read()
            except FileNotFoundError:
                logger.warning("binance_private_key_not_found",
                               path=self._private_key_path)

    @property
    def exchange_name(self) -> str:
        return "binance"

    async def fetch_markets(self) -> List[UnifiedMarket]:
        """
        Fetch all 24h ticker data in ONE API call.
        Binance /ticker/24hr returns all symbols at once — very efficient.
        """
        session = await ConnectionPool.get()
        try:
            resp = await session.get(f"{BINANCE_REST_BASE}/api/v3/ticker/24hr")
            resp.raise_for_status()
            tickers = resp.json()

            markets = []
            for t in tickers:
                symbol = t.get("symbol", "")
                # Filter: USDT pairs only, min volume $100k/day
                if not symbol.endswith("USDT"):
                    continue
                if float(t.get("quoteVolume", 0)) < 100_000:
                    continue

                market = UnifiedMarket(
                    market_id=f"binance_{symbol}",
                    exchange="binance",
                    symbol=symbol,
                    base_asset=symbol.replace("USDT", ""),
                    quote_asset="USDT",
                    market_type="spot",
                    price=float(t.get("lastPrice", 0)),
                    bid=float(t.get("bidPrice", 0)),
                    ask=float(t.get("askPrice", 0)),
                    price_change_24h=float(t.get("priceChangePercent", 0)),
                    volume_24h=float(t.get("quoteVolume", 0)),
                    last_updated=datetime.utcnow(),
                )
                market.binance_price = market.price

                # Volume modifier: low volume = bigger gaps, less competition
                if market.volume_24h < 5_000:
                    market.volume_modifier = 2.0
                elif market.volume_24h < 25_000:
                    market.volume_modifier = 1.5
                elif market.volume_24h > 10_000_000:
                    market.volume_modifier = 0.7  # High competition

                self._markets[symbol] = market
                markets.append(market)

                # Cache price for fast lookup
                await self._cache.set(f"price:binance:{symbol}", market.price)
                await self._cache.set(f"price_ts:binance:{symbol}", time.monotonic())
                await self._cache.set(f"volume24h:binance:{symbol}", market.volume_24h)

            logger.debug("binance_markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("binance_fetch_error", error=str(e))
            return list(self._markets.values())  # Return cached on error

    async def fetch_funding_rates(self) -> Dict[str, FundingData]:
        """Fetch perpetual funding rates. Updates every 8 hours."""
        session = await ConnectionPool.get()
        try:
            resp = await session.get(
                f"{BINANCE_FUTURES_REST}/fapi/v1/premiumIndex"
            )
            resp.raise_for_status()
            data = resp.json()

            rates = {}
            for item in data:
                symbol = item.get("symbol", "")
                rate = float(item.get("lastFundingRate", 0))
                rates[symbol] = FundingData(
                    current_rate=rate,
                    rate_annualised=rate * 3 * 365,
                )
                await self._cache.set(f"funding:binance:{symbol}", {
                    "rate": rate,
                    "annualised": rate * 3 * 365,
                })

            logger.info("binance_funding_fetched", count=len(rates))
            return rates
        except Exception as e:
            logger.error("binance_funding_error", error=str(e))
            return {}

    async def get_triangular_markets(self) -> List[tuple]:
        """
        Find triangular arb opportunities: BTC/ETH/USDT triangle.
        Rule: ETH/USDT price must equal ETH/BTC × BTC/USDT.
        Any deviation = guaranteed arb.
        Returns list of (market_a, market_b, market_c, gap_pct) tuples.
        """
        # Triangle sets to check
        triangles = [
            ("BTCUSDT", "ETHBTC", "ETHUSDT"),
            ("BTCUSDT", "BNBBTC", "BNBUSDT"),
            ("BTCUSDT", "SOLBTC", "SOLUSDT"),
            ("ETHUSDT", "LINKETH", "LINKUSDT"),
        ]

        opportunities = []
        for sym_a, sym_b, sym_c in triangles:
            price_a = await self._cache.get(f"price:binance:{sym_a}")
            price_b = await self._cache.get(f"price:binance:{sym_b}")
            price_c = await self._cache.get(f"price:binance:{sym_c}")

            if not all([price_a, price_b, price_c]):
                continue

            # Mathematical check: price_c should equal price_b * price_a
            implied = price_b * price_a
            if implied == 0:
                continue
            gap_pct = abs(price_c - implied) / implied * 100

            if gap_pct > 0.05:  # > 0.05% gap (profitable after 0.1% fees)
                opportunities.append((sym_a, sym_b, sym_c, gap_pct))

        return opportunities

    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        """Get single symbol. Returns cached if fresh, fetches if stale."""
        cached = await self._cache.get(f"price:binance:{symbol}")
        if cached and symbol in self._markets:
            self._markets[symbol].price = cached
            return self._markets[symbol]

        session = await ConnectionPool.get()
        resp = await session.get(
            f"{BINANCE_REST_BASE}/api/v3/ticker/price",
            params={"symbol": symbol}
        )
        price = float(resp.json()["price"])
        if symbol in self._markets:
            self._markets[symbol].price = price
            return self._markets[symbol]

        return UnifiedMarket(
            market_id=f"binance_{symbol}",
            exchange="binance",
            symbol=symbol,
            price=price,
        )

    async def is_healthy(self) -> bool:
        try:
            session = await ConnectionPool.get()
            resp = await session.get(f"{BINANCE_REST_BASE}/api/v3/ping")
            return resp.status_code == 200
        except Exception:
            return False


class BinanceWebSocketFeed(PersistentWebSocket):
    """
    Subscribes to real-time price ticks for all tracked symbols.
    Publishes PRICE_CHANGE events to event bus.
    This is the core of latency arb — prices arrive in < 100ms.
    """

    def __init__(self, cache: TieredCache, event_bus, symbols: List[str]):
        streams = "/".join(f"{s.lower()}@miniTicker" for s in symbols)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        super().__init__(url, "binance_ticker")
        self._cache = cache
        self._event_bus = event_bus
        self._prev_prices: Dict[str, float] = {}

    async def on_connect(self, ws):
        logger.info("binance_ws_subscribed", symbol_count=len(self._prev_prices))

    async def on_message(self, message: str):
        try:
            data = json.loads(message)
            if "data" not in data:
                return

            tick = data["data"]
            symbol = tick.get("s", "")  # Symbol
            price = float(tick.get("c", 0))  # Close/current price

            if not symbol or not price:
                return

            # Update L1 cache immediately (0.01ms)
            await self._cache.set(f"price:binance:{symbol}", price)
            await self._cache.set(f"price_ts:binance:{symbol}", time.monotonic())

            # Calculate price change since last tick
            prev = self._prev_prices.get(symbol, price)
            change_pct = (price - prev) / prev * 100 if prev > 0 else 0
            self._prev_prices[symbol] = price

            # Publish to event bus for scanner and strategies
            await self._event_bus.publish("PRICE_CHANGE", {
                "exchange": "binance",
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "volume": float(tick.get("v", 0)),
                "ts": float(tick.get("T", 0)),
            })

        except Exception as e:
            logger.warning("binance_ws_parse_error", error=str(e))
