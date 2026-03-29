"""
Main entry point for Node 1 Scanner.
Run: python main.py
Or as systemd service on Hetzner VPS.
"""
import asyncio
import os
import signal
import structlog
from dotenv import load_dotenv

load_dotenv()

import logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


async def run_scanner():
    from core.scanner import UniversalScanner
    from strategies.strategy_wiring import wire_strategies

    scanner = UniversalScanner()

    # Startup initializes connections and loads strategy plugins
    await scanner.startup()

    # Wire loaded strategies to event bus (ROUTE_* events → on_market_signal)
    # Pass db so wiring can read paper capital from strategy_flags.max_capital
    wired = wire_strategies(scanner.registry, scanner.event_bus, scanner.cache, db=scanner.db)
    logger.info("strategies_wired_to_event_bus", count=wired)

    # Run all async tasks (scan loop, websocket, enrichment, etc.)
    await asyncio.gather(
        scanner._run_event_bus(),
        scanner._run_websocket_feed(),
        scanner._run_enrichment_loop(),
        scanner._run_scan_loop(),
        scanner._run_regime_loop(),
        scanner._run_allocation_loop(),
        scanner._run_risk_monitor_loop(),
        scanner._run_heartbeat_loop(),
        scanner._run_cache_cleanup_loop(),
        scanner._run_config_sync_loop(),
    )


async def run_health_api():
    """Start health API — non-fatal if port is already in use."""
    try:
        import uvicorn
        from dashboard_connector.health_api import app
        port = int(os.getenv("HEALTH_PORT", "8080"))
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    except SystemExit:
        logger.warning("health_api_port_in_use", port=8080)
        logger.info("Scanner will continue without health API endpoint")
    except OSError as e:
        logger.warning("health_api_port_in_use", port=8080, error=str(e))
        logger.info("Scanner will continue without health API endpoint")
    except Exception as e:
        logger.warning("health_api_error", error=str(e))


async def main():
    """Run scanner + health API concurrently. Scanner is the primary task."""
    node_id = os.getenv("NODE_ID", "singapore-01")
    logger.info("=" * 60)
    logger.info(f"AlphaNode — Node 1 Scanner Starting")
    logger.info(f"Node ID:  {node_id}")
    logger.info(f"Slot:     {os.getenv('DEPLOY_SLOT', 'green')}")
    logger.info(f"Env:      {os.getenv('APP_ENV', 'development')}")
    logger.info("=" * 60)

    # Graceful shutdown (signal handlers not supported on Windows)
    if os.name != "nt":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    # Run both but don't let health API crash kill the scanner
    await asyncio.gather(
        run_scanner(),
        run_health_api(),
        return_exceptions=True,
    )


async def shutdown():
    logger.info("graceful_shutdown_initiated")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    asyncio.run(main())
