"""
UniversalScanner — the main loop for Node 1 (Singapore).
Assembles and coordinates all components.
Runs forever. Never blocks. All I/O is async.
"""
import asyncio
import os
import time
from datetime import datetime
from typing import Optional
import structlog

from ingestion.ingestion_manager import MarketIngester
from ingestion.binance_adapter import BinanceWebSocketFeed, TRACKED_SYMBOLS
from enrichment.enrichment_pipeline import EnrichmentPipeline
from core.opportunity_scorer import OpportunityScorer
from core.strategy_router import StrategyRouter
from core.market_regime_detector import MarketRegimeDetector
from core.kill_switch_bus import KillSwitchBus
from core.capital_allocator import DynamicCapitalAllocator
from core.india_tax_engine import IndiaTaxEngine
from latency.base_methods import TieredCache, AsyncEventBus
from database.supabase_client import SupabaseClient
from strategies.base_strategy import StrategyRegistry

logger = structlog.get_logger()


class UniversalScanner:
    """
    Heart of Node 1.
    Runs 5 concurrent async tasks:
    1. WebSocket listener (real-time price feed)
    2. Enrichment pipeline (news, fear/greed — every 30s)
    3. Main scan cycle (event-driven scoring + routing)
    4. Regime detector (every 30s)
    5. Capital allocator (every 5 min)
    6. Risk monitor (every 10s — background)
    7. Heartbeat (every 30s — tells dashboard node is alive)
    """

    def __init__(self):
        self._node_id = os.getenv("NODE_ID", "singapore-01")
        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # Core components
        self.cache = TieredCache(self._redis_url)
        self.event_bus = AsyncEventBus()
        self.db = SupabaseClient()

        # Pipeline components
        self.ingester = MarketIngester(self.cache, self.event_bus)
        self.enrichment = EnrichmentPipeline(self.cache)
        self.scorer = OpportunityScorer(self.cache)
        self.kill_switch = KillSwitchBus(self.cache, self.event_bus, self.db)
        self.allocator = DynamicCapitalAllocator(self.cache, self.db)
        self.tax_engine = IndiaTaxEngine(self.cache, self.db)
        self.regime_detector = MarketRegimeDetector(self.cache, self.event_bus, self.db)
        self.router = StrategyRouter(self.event_bus, self.cache, self.db)
        self.registry = StrategyRegistry()

        # WebSocket feeds
        self.binance_ws = BinanceWebSocketFeed(
            self.cache, self.event_bus, TRACKED_SYMBOLS
        )

        self._last_full_scan = 0.0
        self._scan_count = 0
        self._latest_cycle_row: dict = {}  # Buffered — flushed to DB every 60s

    async def startup(self) -> None:
        """Initialize all connections. Called once before run_forever()."""
        logger.info("scanner_starting", node_id=self._node_id)

        # Connect cache
        await self.cache.connect()
        logger.info("redis_connected")

        # Load strategy plugins
        self.registry.load_all(self.kill_switch, self.db, self.tax_engine, self.cache)
        logger.info("strategies_loaded", count=len(self.registry.get_all()))

        # Call startup() on each strategy — reloads open positions from DB
        # so capital limits and duplicate checks work correctly after restarts
        for strat in self.registry.get_all().values():
            if hasattr(strat, "startup"):
                try:
                    strategy_id = getattr(strat, "STRATEGY_ID", "?")
                    await asyncio.wait_for(strat.startup(), timeout=15.0)
                    logger.info("strategy_startup_complete", strategy=strategy_id)
                except asyncio.TimeoutError:
                    logger.warning("strategy_startup_timeout", strategy=getattr(strat, "STRATEGY_ID", "?"))
                except Exception as e:
                    logger.warning("strategy_startup_error", strategy=getattr(strat, "STRATEGY_ID", "?"), error=str(e))

        # Refresh strategy flags (non-blocking with 8s timeout)
        try:
            await asyncio.wait_for(self.router.refresh_enabled_strategies(), timeout=8.0)
        except asyncio.TimeoutError:
            logger.warning("strategy_flag_refresh_timeout")
        except Exception as e:
            logger.warning("strategy_flag_refresh_error", error=str(e))

        # Initial capital setup — load from DB so kill switch + allocator work correctly
        current = None
        try:
            current = await asyncio.wait_for(self.cache.get("capital:current_usdc"), timeout=3.0)
        except Exception as e:
            logger.warning("capital_cache_load_failed", error=str(e))

        if not current:
            capital = 0.0
            try:
                loop = asyncio.get_event_loop()
                pool = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: self.db.table("capital_pools").select("current_balance")
                        .eq("pool_id", "crypto_sg").single().execute()),
                    timeout=8.0,
                )
                capital = float((pool.data or {}).get("current_balance") or 0.0)
            except Exception:
                pass
            # Also sum paper capital from strategy_flags as fallback
            if capital <= 0:
                try:
                    loop = asyncio.get_event_loop()
                    flags = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: self.db.table("strategy_flags").select("max_capital").execute()),
                        timeout=8.0,
                    )
                    capital = sum(float(r.get("max_capital") or 0) for r in (flags.data or []))
                except Exception:
                    pass
            if capital <= 0:
                capital = 2000.0  # safe default for paper trading

            try:
                await asyncio.wait_for(self.cache.set("capital:current_usdc", capital), timeout=3.0)
                await asyncio.wait_for(self.cache.set("capital:peak_usdc", capital), timeout=3.0)
            except Exception as e:
                logger.warning("capital_cache_store_failed", error=str(e))
            logger.info("capital_initialized", usdc=capital)

        # Update node status to online (fire-and-forget, non-blocking)
        asyncio.create_task(self.db.heartbeat(self._node_id))
        logger.info("scanner_startup_complete")

    async def run_forever(self) -> None:
        """
        Main loop. Runs all async tasks concurrently.
        Never returns unless process is killed.
        """
        await self.startup()

        tasks = [
            self._run_event_bus(),
            self._run_websocket_feed(),
            self._run_enrichment_loop(),
            self._run_scan_loop(),
            self._run_regime_loop(),
            self._run_allocation_loop(),
            self._run_risk_monitor_loop(),
            self._run_heartbeat_loop(),
            self._run_cache_cleanup_loop(),
            self._run_config_sync_loop(),
            self._run_cycle_flush_loop(),
        ]

        # Add dedicated loops for strategies that manage their own scanning
        # (e.g. A_CEX_cross_arb — scans all Redis symbols independently of routing)
        for strat in self.registry.get_all().values():
            if getattr(strat, "RUNS_OWN_LOOP", False) and hasattr(strat, "run_forever"):
                logger.info("strategy_own_loop_launched", strategy=strat.STRATEGY_ID)
                tasks.append(strat.run_forever())

        await asyncio.gather(*tasks)

    # ── Task 1: Event Bus ──────────────────────────────────────────────────

    async def _run_event_bus(self) -> None:
        """Event bus dispatch loop. Must be first task started."""
        await self.event_bus.run()

    # ── Task 2: WebSocket Price Feed ───────────────────────────────────────

    async def _run_websocket_feed(self) -> None:
        """Binance real-time price feed. Auto-reconnects."""
        # Subscribe regime change handler
        self.event_bus.subscribe("REGIME_CHANGE", self._on_regime_change)

        # Subscribe to price changes for regime signal updates
        self.event_bus.subscribe("PRICE_CHANGE", self._on_price_change)

        await self.binance_ws.connect()

    async def _on_price_change(self, event: dict) -> None:
        """Update price change metrics for regime detection."""
        data = event.get("data", {})
        symbol = data.get("symbol", "")
        change_pct = data.get("change_pct", 0)

        if symbol == "BTCUSDT":
            # Keep rolling 1h and 4h change estimates
            await self.cache.set(f"price_change:binance:BTCUSDT:1h", change_pct)

    async def _on_regime_change(self, event: dict) -> None:
        """Notify all strategies of regime change."""
        data = event.get("data", {})
        regime = data.get("regime", "")
        paused = data.get("paused_strategies", [])

        for strategy in self.registry.get_all().values():
            try:
                await strategy.on_regime_change(regime, paused)
            except Exception as e:
                logger.warning("regime_notify_error", strategy=strategy.STRATEGY_ID, error=str(e))

    # ── Task 3: Enrichment ────────────────────────────────────────────────

    async def _run_enrichment_loop(self) -> None:
        """Update news, fear/greed every 30 seconds."""
        while True:
            try:
                await self.enrichment.run_all()
            except Exception as e:
                logger.warning("enrichment_error", error=str(e))
            await asyncio.sleep(30)

    # ── Task 4: Main Scan Loop ────────────────────────────────────────────

    async def _run_scan_loop(self) -> None:
        """
        Main scan cycle — runs continuously with no delay.
        Immediately restarts after each cycle completes.
        asyncio.sleep(0) yields one tick to the event loop so WebSocket feed,
        heartbeat, and other tasks stay responsive, then scans again instantly.
        """
        while True:
            try:
                await self._process_scan_cycle({"type": "SCHEDULED"})
            except Exception as e:
                logger.error("scan_loop_error", error=str(e))
            await asyncio.sleep(0)

    async def _process_scan_cycle(self, trigger_event=None) -> None:
        """One complete scan cycle: ingest → enrich → score → route → log."""
        start = time.perf_counter()

        try:
            # 1. Ingest all markets from all exchanges (parallel, < 500ms)
            # Hard cap: if any exchange hangs, don't freeze the scan cycle for >20s
            markets = await asyncio.wait_for(self.ingester.get_all_markets(), timeout=20.0)

            # 2. Enrich with cached intelligence (< 1ms — reads from cache)
            markets = await self.enrichment.enrich_markets_with_cache(markets)

            # 3. Score all markets in parallel (< 1s for 1000 markets)
            scored = await self.scorer.score_all(markets)

            # 4. Get top opportunities
            top_markets = self.scorer.get_top_opportunities(scored, top_n=20)

            # 5. Route top markets to strategies
            routes = await self.router.route_all(top_markets)

            duration_ms = (time.perf_counter() - start) * 1000
            self._scan_count += 1

            # 6. Log cycle to Supabase (async, non-blocking)
            asyncio.create_task(self._log_scan_cycle(
                markets_scored=len(scored),
                duration_ms=duration_ms,
                top_opportunities=top_markets[:10],
                routes=routes,
            ))

            if duration_ms > 15000:
                # On VPS (2-6ms to Binance) this should stay under 2s.
                # On local dev (REST over internet) 5-12s is normal — only alert above 15s.
                logger.error("SCAN_PERFORMANCE_VIOLATION",
                             duration_ms=duration_ms,
                             markets=len(scored))
            else:
                logger.debug("scan_cycle_complete",
                             markets=len(scored),
                             routed=len(routes),
                             duration_ms=round(duration_ms, 2))

        except asyncio.TimeoutError:
            logger.warning("scan_cycle_timeout", msg="Exchange fetch took >20s — skipping cycle")
        except Exception as e:
            logger.error("scan_cycle_error", error=str(e))

    async def _log_scan_cycle(self, markets_scored, duration_ms, top_opportunities, routes):
        """Buffer the latest scan cycle — written to Supabase every 60s by _run_cycle_flush_loop."""
        try:
            regime_data = await self.cache.get("regime:current") or {}
            alloc = await self.cache.get("capital:allocation") or {}
            self._latest_cycle_row = {
                "node_id": self._node_id,
                "cycle_at": datetime.utcnow().isoformat(),
                "markets_scored": markets_scored,
                "duration_ms": round(duration_ms, 2),
                "top_opportunities": [m.to_dict() for m in top_opportunities],
                "regime": regime_data.get("regime", "UNKNOWN"),
                "allocation": alloc,
                "slot": os.getenv("DEPLOY_SLOT", "green"),
            }
        except Exception as e:
            logger.warning("scan_log_error", error=str(e))

    async def _run_cycle_flush_loop(self) -> None:
        """Write the latest buffered scan cycle to Supabase every 60s (1 write/min instead of ~20/min)."""
        while True:
            await asyncio.sleep(60)
            if not self._latest_cycle_row:
                continue
            row = self._latest_cycle_row
            def _write():
                try:
                    self.db.table("scanner_cycles").insert(row).execute()
                except Exception:
                    pass
            asyncio.get_event_loop().run_in_executor(None, _write)

    # ── Task 5: Regime Loop ───────────────────────────────────────────────

    async def _run_regime_loop(self) -> None:
        """Detect market regime every 30 seconds."""
        while True:
            try:
                await self.regime_detector.detect_regime()
            except Exception as e:
                logger.warning("regime_detect_error", error=str(e))
            await asyncio.sleep(30)

    # ── Task 6: Capital Allocation Loop ───────────────────────────────────

    async def _run_allocation_loop(self) -> None:
        """Recompute capital allocation every 5 minutes."""
        while True:
            try:
                await self.allocator.compute_and_store_allocation()
            except Exception as e:
                logger.warning("allocation_error", error=str(e))
            await asyncio.sleep(300)

    # ── Task 7: Risk Monitor Loop ─────────────────────────────────────────

    async def _run_risk_monitor_loop(self) -> None:
        """Background risk analysis every 10 seconds."""
        await self.kill_switch.run_background_monitor()

    # ── Task 8: Heartbeat ─────────────────────────────────────────────────

    async def _run_heartbeat_loop(self) -> None:
        """Tell dashboard this node is alive every 30 seconds."""
        while True:
            try:
                await self.db.heartbeat(self._node_id)
            except Exception as e:
                logger.warning("heartbeat_error", error=str(e))
            await asyncio.sleep(30)

    # ── Task 9: Cache cleanup ─────────────────────────────────────────────

    async def _run_cache_cleanup_loop(self) -> None:
        """Clear expired L1 cache entries every 60 seconds."""
        while True:
            self.cache.clear_l1()
            await asyncio.sleep(60)

    async def _run_config_sync_loop(self) -> None:
        """
        Sync strategy configs from Supabase → cache every 30s.
        Ensures dashboard config changes (monitored_symbols, APR thresholds, etc.)
        are picked up by running strategies without a scanner restart.
        """
        while True:
            try:
                loop = asyncio.get_event_loop()
                rows = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: self.db.table("strategy_plugins")
                        .select("strategy_id, strategy_config").execute()),
                    timeout=8.0,
                )
                for row in (rows.data or []):
                    sid = row.get("strategy_id")
                    cfg = row.get("strategy_config")
                    if sid and cfg and isinstance(cfg, dict) and cfg:
                        await self.cache.set(
                            f"strategy_config:{sid}",
                            cfg,
                            ttl=60,
                        )
                logger.debug("config_sync_done", strategies=len(rows.data or []))
            except Exception as e:
                logger.warning("config_sync_error", error=str(e))
            await asyncio.sleep(30)
