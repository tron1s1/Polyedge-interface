"""
Enrichment pipeline — adds intelligence to raw UnifiedMarket data.
Runs before scoring. Populates: news_velocity, fear_greed, funding rates.
Runs every 30–60 seconds in background (not in hot path).
"""
import asyncio
import os
from typing import List, Dict
from datetime import datetime
from ingestion.market_normalizer import UnifiedMarket
from latency.base_methods import ConnectionPool, TieredCache, extractive_summarize
import structlog

logger = structlog.get_logger()

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class EnrichmentPipeline:
    """
    Runs background enrichment tasks.
    Results stored in cache — consumed by scorer in real-time.
    Never blocks the main scan cycle.
    """

    def __init__(self, cache: TieredCache):
        self._cache = cache
        self._newsapi_key = os.getenv("NEWSAPI_KEY", "")

    async def run_all(self) -> None:
        """
        Run all enrichment tasks in parallel.
        Call this every 30 seconds from main scanner loop.
        """
        await asyncio.gather(
            self._update_fear_greed(),
            self._update_news_velocity(),
            self._update_gdelt_signals(),
            return_exceptions=True
        )

    async def _update_fear_greed(self) -> None:
        """Update Crypto Fear/Greed index. Free API, updates daily."""
        try:
            session = await ConnectionPool.get()
            resp = await session.get(FEAR_GREED_URL, timeout=5)
            data = resp.json()

            index_data = data.get("data", [{}])[0]
            value = int(index_data.get("value", 50))
            classification = index_data.get("value_classification", "Neutral")

            await self._cache.set("fear_greed:current", {
                "value": value,
                "classification": classification,
                "timestamp": datetime.utcnow().isoformat(),
            })
            logger.info("fear_greed_updated", value=value, classification=classification)

        except Exception as e:
            logger.warning("fear_greed_error", error=str(e))

    async def _update_news_velocity(self) -> None:
        """
        Fetch recent crypto news and compute velocity per symbol.
        NewsAPI free: 100 requests/day — use sparingly.
        """
        if not self._newsapi_key:
            return

        symbols_to_watch = ["bitcoin", "ethereum", "solana", "crypto", "binance", "defi"]

        try:
            session = await ConnectionPool.get()
            resp = await session.get(
                NEWSAPI_URL,
                params={
                    "q": " OR ".join(symbols_to_watch),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 50,
                    "apiKey": self._newsapi_key,
                }
            )
            articles = resp.json().get("articles", [])

            # Count articles per symbol in last 2 hours
            from datetime import timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)

            velocity_counts: Dict[str, int] = {}
            for article in articles:
                pub = article.get("publishedAt", "")
                try:
                    pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    continue

                title = (article.get("title", "") + " " +
                         article.get("description", "")).lower()

                for symbol in symbols_to_watch:
                    if symbol in title:
                        velocity_counts[symbol] = velocity_counts.get(symbol, 0) + 1

            # Store in cache
            await self._cache.set("news:velocity", velocity_counts)

            # Create summarised news text for C_AI strategy pre-processing
            if articles:
                combined = " ".join(
                    f"{a.get('title', '')}. {a.get('description', '')}."
                    for a in articles[:20]
                )
                summary = extractive_summarize(combined, sentence_count=8)
                await self._cache.set("news:crypto_summary", summary)

            logger.info("news_velocity_updated", symbols=velocity_counts)

        except Exception as e:
            logger.warning("news_velocity_error", error=str(e))

    async def _update_gdelt_signals(self) -> None:
        """
        GDELT fires 15–30 minutes BEFORE mainstream news APIs.
        Free, no API key. Checks every 15 minutes (GDELT updates every 15min).
        """
        try:
            session = await ConnectionPool.get()
            resp = await session.get(
                GDELT_URL,
                params={
                    "query": "bitcoin OR ethereum OR crypto",
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": 20,
                    "timespan": "15min",
                }
            )
            data = resp.json()
            articles = data.get("articles", [])

            if articles:
                velocity = len(articles)  # Count in last 15 min
                tones = [float(a.get("tone", 0)) for a in articles if "tone" in a]
                avg_tone = sum(tones) / len(tones) if tones else 0

                await self._cache.set("gdelt:crypto", {
                    "velocity_15min": velocity,
                    "avg_tone": avg_tone,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                logger.info("gdelt_updated", velocity=velocity, tone=round(avg_tone, 2))

        except Exception as e:
            logger.warning("gdelt_error", error=str(e))

    async def enrich_markets_with_cache(
        self, markets: List[UnifiedMarket]
    ) -> List[UnifiedMarket]:
        """
        Apply cached enrichment data to markets before scoring.
        This runs in the hot path but only reads from cache (< 1ms).
        """
        # Get fear/greed from cache
        fg = await self._cache.get("fear_greed:current") or {"value": 50}
        fg_value = fg.get("value", 50)
        fg_class = fg.get("classification", "Neutral")

        # Get news velocity from cache
        news_velocity = await self._cache.get("news:velocity") or {}

        for market in markets:
            # Apply fear/greed to ALL markets (it's global)
            market.fear_greed_index = fg_value
            market.fear_greed_classification = fg_class

            # Apply news velocity for matching symbols
            base = market.base_asset.lower()
            market.news_velocity = news_velocity.get(base, 0)

        return markets
