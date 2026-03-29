"""
Base latency methods B1–B8.
All 8 are ALWAYS active — never optional, never disabled.
These are the infrastructure layer every strategy sits on top of.
"""
import asyncio
import time
import msgpack
import httpx
import redis.asyncio as aioredis
from typing import Any, Optional
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer
import structlog

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────
# B1 — ASYNC PARALLEL PROCESSING
# All market operations via asyncio.gather() — NEVER sequential
# Target: 1,000 markets processed in < 1 second
# ─────────────────────────────────────────────────────────────

async def process_all_parallel(items: list, processor_fn) -> list:
    """Process any list of items in parallel. Core of B1."""
    results = await asyncio.gather(
        *[processor_fn(item) for item in items],
        return_exceptions=True
    )
    # Filter out exceptions, log them
    clean = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("parallel_processor_error", index=i, error=str(r))
        else:
            clean.append(r)
    return clean


# ─────────────────────────────────────────────────────────────
# B2 — PERSISTENT WEBSOCKET CONNECTIONS
# One connection per source. Auto-reconnect with backoff.
# Never close and reopen — connection costs 150–400ms each time.
# ─────────────────────────────────────────────────────────────

class PersistentWebSocket:
    """
    Persistent WebSocket with exponential backoff reconnect.
    Usage: Subclass this and implement on_message().
    """
    RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30, 60]

    def __init__(self, url: str, name: str):
        self.url = url
        self.name = name
        self._ws = None
        self._running = False
        self._reconnect_count = 0

    async def connect(self):
        import websockets
        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._reconnect_count = 0
                    logger.info("ws_connected", source=self.name)
                    await self.on_connect(ws)
                    async for message in ws:
                        await self.on_message(message)
            except Exception as e:
                delay = self.RECONNECT_DELAYS[
                    min(self._reconnect_count, len(self.RECONNECT_DELAYS) - 1)
                ]
                logger.warning("ws_disconnected", source=self.name, error=str(e), retry_in=delay)
                self._reconnect_count += 1
                await asyncio.sleep(delay)

    async def on_connect(self, ws):
        """Override to send subscription messages after connect."""
        pass

    async def on_message(self, message: str):
        """Override to handle incoming messages."""
        raise NotImplementedError

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()


# ─────────────────────────────────────────────────────────────
# B3 — TIERED REDIS CACHE (L1 in-process dict + L2 Redis)
# L1: Python dict reads at 0.01ms
# L2: Redis reads at 0.1ms
# L3: Supabase/API — only on cache miss (20–500ms)
# ─────────────────────────────────────────────────────────────

class TieredCache:
    """
    Two-level cache: in-process dict (L1) + Redis (L2).
    L1 is always checked first. Falls through to L2, then L3 caller.
    TTLs are per-key-prefix based on data freshness requirements.
    """
    # Default TTLs in seconds
    TTL = {
        "price:":       5,     # Exchange prices change every 100ms
        "meta:":        60,    # Market metadata (relatively stable)
        "news:":        300,   # News summaries (5 min)
        "corr:":        3600,  # Correlation map (1 hour)
        "flag:":        30,    # Feature flags (30 sec propagation)
        "regime:":      10,    # Market regime (10 sec)
        "risk:":        5,     # Risk state (5 sec)
        "funding:":     300,   # Funding rates (8h cycle, check every 5 min)
        "prompt:":      300,   # Pre-built Claude prompts (5 min freshness)
    }

    def __init__(self, redis_url: str):
        self._L1: dict[str, tuple[Any, float]] = {}  # value, expiry_timestamp
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url

    async def connect(self):
        self._redis = await aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=False,  # raw bytes for msgpack
        )

    def _get_ttl(self, key: str) -> int:
        for prefix, ttl in self.TTL.items():
            if key.startswith(prefix):
                return ttl
        return 60  # default 60s

    async def get(self, key: str) -> Optional[Any]:
        # L1: in-process dict (0.01ms)
        if key in self._L1:
            value, expiry = self._L1[key]
            if time.monotonic() < expiry:
                return value
            del self._L1[key]

        # L2: Redis (0.1ms)
        if self._redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    value = msgpack.unpackb(raw, raw=False)
                    ttl = self._get_ttl(key)
                    self._L1[key] = (value, time.monotonic() + ttl)
                    return value
            except Exception as e:
                logger.warning("redis_get_error", key=key, error=str(e))

        return None  # Cache miss — caller fetches from source

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if ttl is None:
            ttl = self._get_ttl(key)

        # Write to L1
        self._L1[key] = (value, time.monotonic() + ttl)

        # Write to L2
        if self._redis:
            try:
                raw = msgpack.packb(value, use_bin_type=True)
                await self._redis.set(key, raw, ex=ttl)
            except Exception as e:
                logger.warning("redis_set_error", key=key, error=str(e))

    async def delete(self, key: str) -> None:
        self._L1.pop(key, None)
        if self._redis:
            await self._redis.delete(key)

    def clear_l1(self) -> None:
        """Clear expired L1 entries. Call every 60 seconds."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._L1.items() if now > exp]
        for k in expired:
            del self._L1[k]


# ─────────────────────────────────────────────────────────────
# B4 — HTTP CONNECTION POOLING (HTTP/2)
# Single shared session per process. HTTP/2 multiplexing.
# Saves 100–300ms vs creating new connections per request.
# ─────────────────────────────────────────────────────────────

class ConnectionPool:
    """Singleton HTTP/2 connection pool for all REST API calls."""
    _instance: Optional[httpx.AsyncClient] = None

    @classmethod
    async def get(cls) -> httpx.AsyncClient:
        if cls._instance is None or cls._instance.is_closed:
            cls._instance = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=30,
                    keepalive_expiry=30,
                ),
                timeout=httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=1.0),
                http2=True,
                follow_redirects=True,
            )
        return cls._instance

    @classmethod
    async def close(cls):
        if cls._instance and not cls._instance.is_closed:
            await cls._instance.aclose()
            cls._instance = None


# ─────────────────────────────────────────────────────────────
# B5 — EVENT-DRIVEN ARCHITECTURE
# AsyncEventBus: publish events, strategies subscribe.
# No polling loops — everything reacts to events.
# ─────────────────────────────────────────────────────────────

class AsyncEventBus:
    """
    Lightweight async event bus.
    Publishers: WebSocket handlers, scanners, risk module.
    Subscribers: Strategy plugins, risk module, allocator.

    Event types used in Node 1:
    PRICE_CHANGE, FUNDING_RATE_UPDATE, TRIANGULAR_GAP,
    CEX_PRICE_GAP, LISTING_ANNOUNCED, NEWS_SPIKE,
    WHALE_DEPOSIT, FEAR_GREED_EXTREME, REGIME_CHANGE,
    KILL_SWITCH, STRATEGY_ROUTE_{STRATEGY_ID}
    """

    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50000)

    def subscribe(self, event_type: str, handler) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict) -> None:
        """Non-blocking publish. Skips queue if no subscribers.
        Ring-buffer: evicts oldest event to make room for new one — never drops incoming."""
        # Fast path: skip entirely if no one is listening (avoids queue pressure)
        if event_type not in self._subscribers and "*" not in self._subscribers:
            return
        event = {"type": event_type, "data": data, "ts": time.monotonic()}
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Evict oldest, insert newest — keep bus always current
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(event)

    async def run(self) -> None:
        """Main dispatch loop. Run as background task."""
        while True:
            event = await self._queue.get()
            event_type = event["type"]
            handlers = self._subscribers.get(event_type, [])
            # Also check wildcard subscribers
            handlers += self._subscribers.get("*", [])
            if handlers:
                await asyncio.gather(
                    *[self._safe_call(h, event) for h in handlers],
                    return_exceptions=True
                )

    async def _safe_call(self, handler, event: dict) -> None:
        try:
            await handler(event)
        except Exception as e:
            logger.error("event_handler_error", handler=str(handler), error=str(e))


# ─────────────────────────────────────────────────────────────
# B6 — EXTRACTIVE SUMMARISATION (Zero Claude cost for news prep)
# sumy LsaSummarizer — 5ms locally, zero API cost.
# Only pre-processed summaries go to Claude (not raw articles).
# ─────────────────────────────────────────────────────────────

def extractive_summarize(text: str, sentence_count: int = 5) -> str:
    """
    Extract key sentences from news text without any AI/API call.
    Takes 3–8ms locally. Reduces 10,000 words to 5 sentences.
    These 5 sentences are what gets sent to Claude in C_AI strategy.
    """
    if not text or len(text) < 100:
        return text
    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LsaSummarizer()
        sentences = summarizer(parser.document, sentence_count)
        return " ".join(str(s) for s in sentences)
    except Exception as e:
        logger.warning("summarize_error", error=str(e))
        return text[:500]  # fallback: first 500 chars


# ─────────────────────────────────────────────────────────────
# B7 — DATABASE CONNECTION POOLING (Supabase pgBouncer)
# ALWAYS port 6543 (pooler), never 5432.
# Batch writes: collect during cycle, single executemany() at end.
# ─────────────────────────────────────────────────────────────

class BatchWriter:
    """
    Collects DB writes during a scan cycle, flushes once per cycle.
    Reduces DB round trips from N (one per trade) to 1 (one batch).
    """
    def __init__(self, supabase_client):
        self._client = supabase_client
        self._pending: dict[str, list] = {}  # table → list of records

    def queue(self, table: str, record: dict) -> None:
        if table not in self._pending:
            self._pending[table] = []
        self._pending[table].append(record)

    async def flush(self) -> None:
        """Call at end of each scan cycle. Writes all pending records."""
        for table, records in self._pending.items():
            if not records:
                continue
            try:
                self._client.table(table).upsert(records).execute()
            except Exception as e:
                logger.error("batch_write_error", table=table, count=len(records), error=str(e))
        self._pending.clear()


# ─────────────────────────────────────────────────────────────
# B8 — MSGPACK SERIALISATION
# 3–10× faster than JSON. 20–30% smaller payloads.
# Used for ALL inter-process communication.
# ─────────────────────────────────────────────────────────────

def pack(data: dict) -> bytes:
    """Serialize for IPC. Use instead of json.dumps()."""
    return msgpack.packb(data, use_bin_type=True)


def unpack(data: bytes) -> dict:
    """Deserialize from IPC. Use instead of json.loads()."""
    return msgpack.unpackb(data, raw=False)
