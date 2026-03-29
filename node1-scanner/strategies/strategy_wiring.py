"""
Strategy Wiring — connects loaded strategy plugins to the event bus.

The StrategyRouter publishes ROUTE_{STRATEGY_ID} events for each routed market.
This module subscribes each loaded strategy instance to its own route event,
calling strategy.on_market_signal() when triggered.

This module lives in strategies/ (not core/) so core/ files stay untouched.
Called once during scanner startup from main.py.
"""
import asyncio
from typing import Dict, Optional
from strategies.base_strategy import BaseStrategy, StrategyRegistry
from latency.base_methods import AsyncEventBus, TieredCache
from ingestion.market_normalizer import UnifiedMarket
import structlog

logger = structlog.get_logger()


def wire_strategies(
    registry: StrategyRegistry,
    event_bus: AsyncEventBus,
    cache: TieredCache,
    db=None,
) -> int:
    """
    Subscribe each loaded strategy to its ROUTE_{STRATEGY_ID} event.

    When the StrategyRouter publishes ROUTE_A_M1_TRIANGULAR_ARB,
    the corresponding Strategy.on_market_signal() gets called.

    Returns number of strategies wired.
    """
    wired = 0
    strategies = registry.get_all()

    for strategy_id, strategy in strategies.items():
        event_name = f"ROUTE_{strategy_id.upper()}"

        # Create a closure that captures this specific strategy instance
        def make_handler(strat):
            async def handler(event):
                data = event.get("data", {})
                market_dict = data.get("market", {})

                # Reconstruct UnifiedMarket from dict
                try:
                    market = UnifiedMarket.from_dict(market_dict) if hasattr(UnifiedMarket, 'from_dict') else _dict_to_market(market_dict)
                except Exception as e:
                    logger.warning("market_reconstruct_error", strategy=strat.STRATEGY_ID, error=str(e))
                    return

                # Resolve capital allocation for this strategy
                alloc = await _get_strategy_alloc(strat.STRATEGY_ID, cache, db)

                try:
                    decision = await strat.on_market_signal(market, alloc)
                    if decision:
                        logger.info("strategy_decision",
                                    strategy=strat.STRATEGY_ID,
                                    symbol=decision.symbol,
                                    direction=decision.direction,
                                    size_usdc=decision.size_usdc,
                                    paper=strat._is_paper)

                        # Step 2: execute the trade (paper sim or live)
                        regime = (await cache.get("market:regime")) or "NEUTRAL"

                        if hasattr(strat, "execute_signal") and decision.opportunity_id:
                            # Two-step strategy (e.g. A_M2): execute_signal handles
                            # position management + logs to funding_positions
                            try:
                                await strat.execute_signal(
                                    decision, market, decision.opportunity_id, regime
                                )
                            except Exception as ex:
                                logger.error("execute_signal_error",
                                             strategy=strat.STRATEGY_ID, error=str(ex))

                        # Log to unified trades table unless the strategy handles
                        # its own complete trade logging (e.g. A_CEX_cross_arb
                        # writes win/loss directly; logging here would add a
                        # duplicate "pending" row for every trade).
                        if not getattr(strat, "SELF_LOGS_TRADES", False):
                            try:
                                await strat.log_trade_to_db(market, decision, regime, strat._is_paper)
                            except Exception as ex:
                                logger.error("trade_log_error",
                                             strategy=strat.STRATEGY_ID, error=str(ex))

                except Exception as e:
                    logger.error("strategy_signal_error",
                                strategy=strat.STRATEGY_ID,
                                error=str(e))

            return handler

        event_bus.subscribe(event_name, make_handler(strategy))
        logger.info("strategy_wired", strategy_id=strategy_id, route_event=event_name)
        wired += 1

    return wired


async def _get_strategy_alloc(strategy_id: str, cache: TieredCache, db=None) -> float:
    """
    Resolve how much USDC this strategy can deploy.

    Priority:
    1. capital:allocation.per_strategy.{strategy_id} — live allocator (regime-aware)
    2. strategy_flags.max_capital from DB — paper trading capital set via dashboard
    3. 0.0 — no capital, strategy will skip execution
    """
    # 1. Try live allocator cache
    alloc_data = await cache.get("capital:allocation")
    if alloc_data and isinstance(alloc_data, dict):
        per_strategy = alloc_data.get("per_strategy", {})
        if strategy_id in per_strategy and per_strategy[strategy_id] > 0:
            return float(per_strategy[strategy_id])

    # 2. Try paper capital from strategy_flags via DB
    if db is not None:
        try:
            result = db.table("strategy_flags").select("max_capital, mode") \
                .eq("strategy_id", strategy_id).single().execute()
            if result.data:
                max_capital = result.data.get("max_capital") or 0.0
                if max_capital > 0:
                    # Cache it briefly so repeated calls in same cycle are fast
                    await cache.set(f"paper_capital:{strategy_id}", max_capital, ttl=30)
                    return float(max_capital)
        except Exception:
            pass

    # 3. Try cached paper capital from previous DB read
    cached = await cache.get(f"paper_capital:{strategy_id}")
    if cached:
        return float(cached)

    return 0.0


def _dict_to_market(d: dict) -> UnifiedMarket:
    """Reconstruct a UnifiedMarket from a to_dict() output."""
    from ingestion.market_normalizer import FundingData

    m = UnifiedMarket(
        market_id=d.get("market_id", ""),
        exchange=d.get("exchange", ""),
        symbol=d.get("symbol", ""),
        base_asset=d.get("symbol", "").replace("USDT", ""),
        quote_asset="USDT",
        price=d.get("price", 0.0),
        volume_24h=d.get("volume_24h", 0.0),
    )
    m.price_change_24h = d.get("price_change_24h", 0.0)
    m.opportunity_score = d.get("opportunity_score", 0.0)
    m.suggested_strategies = d.get("suggested_strategies", [])
    m.max_exchange_gap_pct = d.get("max_exchange_gap_pct", 0.0)
    m.triangular_gap_pct = d.get("triangular_gap_pct", 0.0)
    m.funding = FundingData(
        current_rate=d.get("funding_rate", 0.0),
        rate_annualised=d.get("funding_annualised", 0.0),
    )
    return m
