"""
Health API — minimal FastAPI app running on Node 1.
Exposes a /health endpoint so dashboard can verify node is alive.
All real data goes via Supabase — this is just liveness check.
Port: 8080 (configure in Hetzner firewall)
"""
import os
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database.supabase_client import SupabaseClient
from latency.base_methods import TieredCache
import structlog

logger = structlog.get_logger()

app = FastAPI(title="Node 1 Health API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to dashboard domain in production
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

db = SupabaseClient()
cache = TieredCache(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


@app.on_event("startup")
async def _connect_cache():
    """Connect the TieredCache to Redis so L2 reads/writes actually work."""
    try:
        await cache.connect()
        logger.info("health_api_cache_connected")
    except Exception as e:
        logger.warning("health_api_cache_connect_failed", error=str(e))


@app.get("/health")
async def health():
    """Liveness check. Dashboard polls this every 30 seconds."""
    try:
        from core.kill_switch_bus import _RISK_STATE
        regime = await cache.get("regime:current") or {}
        capital = await cache.get("capital:current_usdc") or 0.0
        tax_reserve = await cache.get("tax:reserve_usdc") or 0.0
        pnl_today = await cache.get("pnl:today:usdc") or 0.0

        return {
            "status": "online",
            "node_id": os.getenv("NODE_ID", "singapore-01"),
            "slot": os.getenv("DEPLOY_SLOT", "green"),
            "timestamp": datetime.utcnow().isoformat(),
            "regime": regime.get("regime", "UNKNOWN"),
            "kelly_multiplier": regime.get("kelly_multiplier", 0.75),
            "capital_usdc": round(capital, 2),
            "pnl_today_usdc": round(pnl_today, 2),
            "tax_reserve_usdc": round(tax_reserve, 2),
            "global_kill_switch": _RISK_STATE.get("global_kill", False),
            "blocked_strategies": list(_RISK_STATE.get("blocked_strategies", set())),
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.post("/kill-switch/trigger")
async def trigger_kill_switch(reason: str = "Manual trigger"):
    """Emergency halt from dashboard. DOES NOT require auth in MVP."""
    from core.kill_switch_bus import _RISK_STATE
    _RISK_STATE["global_kill"] = True
    await cache.set("risk:global_kill", True)
    logger.critical("kill_switch_triggered_via_api", reason=reason)
    return {"status": "halted", "reason": reason}


@app.post("/kill-switch/release")
async def release_kill_switch():
    """Release halt. Manual action only."""
    from core.kill_switch_bus import _RISK_STATE
    _RISK_STATE["global_kill"] = False
    await cache.set("risk:global_kill", False)
    logger.warning("kill_switch_released_via_api")
    return {"status": "released"}


# -------------------------------------------------------------------------
# STRATEGY CONFIG API
# -------------------------------------------------------------------------

class StrategyConfigUpdate(BaseModel):
    """Partial-update payload. Only send fields you want to change."""
    kelly_multiplier: Optional[float] = None
    max_capital_pct: Optional[float] = None
    mode: Optional[str] = None        # 'paper' | 'live'
    notes: Optional[str] = None
    config: Optional[dict] = None     # Strategy-specific fields (A_M1 params)


def _get_supabase() -> SupabaseClient:
    """Return the module-level Supabase client."""
    return db


def _suggest_kelly(strategy: dict) -> float:
    """
    Auto-suggest Kelly fraction from paper trade history.
    A_math strategies: always 1.0 (mathematical certainty).
    Other strategies: half-Kelly from observed win rate.
    """
    if strategy.get("category") == "A_math":
        return 1.0
    win_rate = strategy.get("win_rate")
    if win_rate and win_rate > 0:
        kelly = max(0.1, min(0.9, 2 * float(win_rate) - 1))
        return round(kelly * 0.5, 2)
    return 0.25


def _validate_funding_config(config: dict) -> None:
    """Validate A_M2-specific config values. Raises HTTPException on violation."""
    if "min_apr_to_open" in config:
        v = float(config["min_apr_to_open"])
        if not 0.01 <= v <= 2.0:
            raise HTTPException(400, "min_apr_to_open must be 0.01–2.0 (1%–200% APR)")

    if "max_position_size_usdc" in config:
        v = float(config["max_position_size_usdc"])
        if not 50 <= v <= 50_000:
            raise HTTPException(400, "max_position_size_usdc must be $50–$50,000")

    if "max_positions_open" in config:
        v = int(config["max_positions_open"])
        if not 1 <= v <= 10:
            raise HTTPException(400, "max_positions_open must be 1–10")

    if "perp_leverage" in config and config["perp_leverage"] != 1:
        raise HTTPException(400, "perp_leverage must be 1 (never leverage the hedge)")

    if "monitored_symbols" in config and len(config["monitored_symbols"]) == 0:
        raise HTTPException(400, "Must monitor at least 1 symbol")


def _validate_triangle_config(config: dict) -> None:
    """Validate A_M1-specific config values. Raises HTTPException on violation."""
    if "min_gap_pct" in config:
        v = float(config["min_gap_pct"])
        if not 0.05 <= v <= 1.0:
            raise HTTPException(400, "min_gap_pct must be 0.05–1.0%")

    if "max_trade_size_usdc" in config:
        v = float(config["max_trade_size_usdc"])
        if not 50 <= v <= 50_000:
            raise HTTPException(400, "max_trade_size_usdc must be $50–$50,000")

    if "min_trade_size_usdc" in config:
        v = float(config["min_trade_size_usdc"])
        if not 10 <= v <= 500:
            raise HTTPException(400, "min_trade_size_usdc must be $10–$500")

    if "fee_per_leg_pct" in config:
        v = float(config["fee_per_leg_pct"])
        if not 0.01 <= v <= 0.5:
            raise HTTPException(400, "fee_per_leg_pct must be 0.01–0.5%")

    if "active_triangles" in config:
        if not isinstance(config["active_triangles"], list):
            raise HTTPException(400, "active_triangles must be a list")
        if len(config["active_triangles"]) == 0:
            raise HTTPException(400, "At least one triangle must be active")


@app.get("/api/strategies")
async def list_all_strategies():
    """
    Return list of all registered strategies from strategy_plugins table.
    Used by dashboard to display strategy list on main page.
    Includes all necessary fields for dashboard rendering.
    """
    supa = _get_supabase()
    node_id = os.getenv("NODE_ID", "singapore-01")

    try:
        result = supa.table("strategy_plugins").select("*").execute()

        # Aggregate trade stats via a single SQL GROUP BY — one round-trip, no full scan
        live_stats: dict = {}
        try:
            agg = supa._client.rpc("get_strategy_trade_stats", {}).execute()
            for row in (agg.data or []):
                sid = row.get("strategy_id")
                if sid:
                    live_stats[sid] = row
        except Exception:
            pass  # RPC not available yet — fall back to strategy_plugins static values

        strategies = []
        if result.data:
            for strat in result.data:
                sid = strat.get("strategy_id")
                stats = live_stats.get(sid, {})
                total = stats.get("total", 0)
                wins  = stats.get("wins", 0)
                strategies.append({
                    "strategy_id":        sid,
                    "display_name":       strat.get("display_name"),
                    "category":           strat.get("category"),
                    "category_label":     strat.get("category_label"),
                    "mode":               strat.get("mode", "paper"),
                    "enabled":            strat.get("enabled", False),
                    "node_id":            node_id,
                    # Live-computed from strategy_executions — always accurate
                    "win_rate":           round(wins / total, 4) if total > 0 else strat.get("win_rate"),
                    "total_pnl_usdc":     round(stats.get("total_pnl_usdc", strat.get("total_pnl_usdc") or 0.0), 4),
                    "paper_trades_count": stats.get("paper_trades_count", strat.get("paper_trades_count", 0)),
                    "live_trades_count":  stats.get("live_trades_count", strat.get("live_trades_count", 0)),
                    "description":        strat.get("description"),
                    "file_name":          strat.get("file_name"),
                    "version_tag":        strat.get("version_tag"),
                    "notes":              strat.get("notes"),
                    "kelly_multiplier":   strat.get("kelly_multiplier", 1.0),
                    "max_capital_pct":    strat.get("max_capital_pct", 0.05),
                    "config":             strat.get("config") or {},
                })

        return {
            "strategies": strategies,
            "count": len(strategies),
            "node_id": node_id,
        }

    except Exception as e:
        logger.error("list_strategies_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list strategies: {str(e)}")


@app.get("/api/strategies/{strategy_id}/config")
async def get_strategy_config(strategy_id: str):
    """
    Return full config for a strategy including:
    - Generic fields (kelly, max_capital_pct, mode)
    - Strategy-specific jsonb config
    - Current regime Kelly (from deployment_config)
    - Effective Kelly (per_strategy × regime)
    """
    supa = _get_supabase()

    result = supa.table("strategy_plugins").select(
        "strategy_id, display_name, category, mode, kelly_multiplier, "
        "max_capital_pct, notes, config, win_rate, live_trades_count, "
        "paper_trades_count, total_pnl_usdc, version_tag"
    ).eq("strategy_id", strategy_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    strategy = result.data

    # Regime Kelly from deployment_config
    regime_result = supa.table("deployment_config").select("value").eq(
        "key", "regime_kelly_current"
    ).single().execute()
    regime_kelly = float((regime_result.data or {}).get("value", "0.75"))

    # Regime name for display label
    regime_name_result = supa.table("deployment_config").select("value").eq(
        "key", "global_regime"
    ).single().execute()
    regime_name = (regime_name_result.data or {}).get("value", "BULL_RANGING")

    # Pool balance for allocation display
    pool_result = supa.table("capital_pools").select(
        "current_balance, pool_id"
    ).eq("pool_id", "crypto_sg").single().execute()
    pool_balance = float((pool_result.data or {}).get("current_balance", 0))

    per_strategy_kelly = float(strategy.get("kelly_multiplier") or 1.0)
    effective_kelly    = per_strategy_kelly * regime_kelly
    max_cap_pct        = float(strategy.get("max_capital_pct") or 0.20)
    allocated_usdc     = pool_balance * max_cap_pct
    specific_config    = strategy.get("config") or {}

    return {
        "strategy_id": strategy_id,
        "display_name": strategy.get("display_name"),
        "category":     strategy.get("category"),
        "mode":         strategy.get("mode", "paper"),
        "kelly_multiplier": per_strategy_kelly,
        "max_capital_pct":  max_cap_pct,
        "notes":        strategy.get("notes", ""),
        "kelly": {
            "per_strategy": per_strategy_kelly,
            "regime":       regime_kelly,
            "regime_name":  regime_name,
            "effective":    round(effective_kelly, 4),
            "suggestion":   _suggest_kelly(strategy),
        },
        "capital": {
            "pool_id":           "crypto_sg",
            "pool_balance_usdc": pool_balance,
            "allocated_usdc":    round(allocated_usdc, 2),
            "allocated_pct":     max_cap_pct,
        },
        "strategy_config": specific_config,
        "performance": {
            "win_rate":       strategy.get("win_rate"),
            "paper_trades":   strategy.get("paper_trades_count", 0),
            "live_trades":    strategy.get("live_trades_count", 0),
            "total_pnl_usdc": strategy.get("total_pnl_usdc", 0),
        },
        "version_tag": strategy.get("version_tag"),
    }


@app.patch("/api/strategies/{strategy_id}/config")
async def update_strategy_config(strategy_id: str, update: StrategyConfigUpdate):
    """
    Partial-update strategy config.
    Writes to strategy_plugins AND strategy_flags (plugin picks up in < 30s).
    Also pushes to Redis cache immediately so plugin picks up without waiting.
    """
    supa = _get_supabase()
    plugin_update: dict = {}
    flags_update:  dict = {}

    if update.kelly_multiplier is not None:
        if not 0.0 <= update.kelly_multiplier <= 1.0:
            raise HTTPException(400, "kelly_multiplier must be 0.0–1.0")
        plugin_update["kelly_multiplier"] = update.kelly_multiplier

    if update.max_capital_pct is not None:
        if not 0.0 < update.max_capital_pct <= 0.65:
            raise HTTPException(400, "max_capital_pct must be 0.01–0.65")
        plugin_update["max_capital_pct"] = update.max_capital_pct

    if update.mode is not None:
        if update.mode not in ("paper", "live"):
            raise HTTPException(400, "mode must be 'paper' or 'live'")
        plugin_update["mode"] = update.mode
        flags_update["mode"]  = update.mode

    if update.notes is not None:
        plugin_update["notes"] = update.notes

    if update.config is not None:
        if strategy_id == "A_M1_triangular_arb":
            _validate_triangle_config(update.config)
        if strategy_id == "A_M2_funding_rate":
            _validate_funding_config(update.config)

        if strategy_id == "A_CEX_cross_arb" and update.config:
            c = update.config
            if "min_gap_pct" in c and not (0.10 <= c["min_gap_pct"] <= 2.0):
                raise HTTPException(400, "min_gap_pct must be 0.10–2.0%")
            if "max_trade_size_usdc" in c and not (50 <= c["max_trade_size_usdc"] <= 50_000):
                raise HTTPException(400, "max_trade_size_usdc must be $50–$50,000")
            if "active_pairs" in c and len(c["active_pairs"]) == 0:
                raise HTTPException(400, "Must have at least 1 active pair")
            for fee_key in ("fee_binance_pct", "fee_okx_pct", "fee_kucoin_pct", "fee_mexc_pct"):
                if fee_key in c and not (0.01 <= c[fee_key] <= 0.5):
                    raise HTTPException(400, f"{fee_key} must be 0.01–0.5%")
            if "max_concurrent_trades" in c and not (1 <= c["max_concurrent_trades"] <= 5):
                raise HTTPException(400, "max_concurrent_trades must be 1–5")

                # Merge into existing jsonb — never overwrite entire column
        existing = supa.table("strategy_plugins").select("config").eq(
            "strategy_id", strategy_id
        ).single().execute()
        existing_config = (existing.data or {}).get("config") or {}
        merged_config = {**existing_config, **update.config}
        plugin_update["config"] = merged_config
        flags_update["config_snapshot"] = merged_config

    if not plugin_update:
        raise HTTPException(400, "No fields to update")

    # Persist to Supabase
    supa.table("strategy_plugins").update(plugin_update).eq(
        "strategy_id", strategy_id
    ).execute()

    if flags_update:
        supa.table("strategy_flags").update(flags_update).eq(
            "strategy_id", strategy_id
        ).execute()

    # Push merged strategy config to Redis immediately so plugin picks up
    # without waiting for the next 60s cache TTL cycle
    if "config" in plugin_update:
        try:
            await cache.set(
                f"strategy_config:{strategy_id}",
                plugin_update["config"],
                ttl=60,
            )
        except Exception as e:
            logger.warning("cache_push_failed", strategy=strategy_id, error=str(e))

    logger.info("strategy_config_updated",
                strategy=strategy_id,
                fields=list(plugin_update.keys()))

    return {
        "status": "updated",
        "strategy_id": strategy_id,
        "updated_fields": list(plugin_update.keys()),
    }


@app.post("/api/strategies/{strategy_id}/snapshot")
async def save_version_snapshot(strategy_id: str, label: Optional[str] = None):
    """
    Save current config as a named version snapshot for A/B comparison.
    e.g. 'v1-gap-0.12' vs 'v2-gap-0.08'
    """
    supa = _get_supabase()

    current = supa.table("strategy_plugins").select(
        "kelly_multiplier, max_capital_pct, mode, config, version_tag"
    ).eq("strategy_id", strategy_id).single().execute()

    if not current.data:
        raise HTTPException(404, "Strategy not found")

    snapshot_tag = label or f"snapshot-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"

    supa.table("latency_versions").insert({
        "version_tag": snapshot_tag,
        "strategy_id": strategy_id,
        "node_id":     os.getenv("NODE_ID", "singapore-01"),
        "base_methods": ["B1", "B2", "B3", "B4", "B5", "B7", "B8"],
        "is_paper":    current.data.get("mode") == "paper",
        "is_active":   False,
        "commit_hash": snapshot_tag,
    }).execute()

    logger.info("version_snapshot_saved",
                strategy=strategy_id,
                tag=snapshot_tag)

    return {
        "status": "snapshot_saved",
        "version_tag": snapshot_tag,
        "config_saved": current.data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# A_M2 FUNDING RATE — SPECIFIC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/strategies/A_M2_funding_rate/positions")
async def get_funding_positions():
    """Return all current open positions with live metrics."""
    supa = _get_supabase()
    result = supa.table("funding_positions").select("*").eq(
        "status", "holding"
    ).eq("node_id", os.getenv("NODE_ID", "singapore-01")).execute()

    positions = result.data or []
    return {
        "open_positions": len(positions),
        "positions": positions,
    }


@app.get("/api/strategies/A_M2_funding_rate/payments")
async def get_funding_payments(limit: int = 50):
    """Return recent funding payments received."""
    supa = _get_supabase()
    result = supa.table("funding_payments").select("*").order(
        "payment_time", desc=True
    ).limit(limit).execute()
    return {"payments": result.data or []}


@app.get("/api/strategies/A_M2_funding_rate/income-summary")
async def get_income_summary():
    """Summary: total income, APR achieved, payments per symbol."""
    from datetime import timezone
    from strategies.A_M2_funding_rate import FundingRateMonitor

    supa = _get_supabase()
    payments = supa.table("funding_payments").select(
        "symbol, amount_usdc, annualised_rate, payment_time"
    ).execute().data or []

    by_symbol: dict = {}
    total = 0.0
    for p in payments:
        sym = p["symbol"]
        amt = float(p.get("amount_usdc", 0))
        if sym not in by_symbol:
            by_symbol[sym] = {"total_usdc": 0.0, "count": 0}
        by_symbol[sym]["total_usdc"] += amt
        by_symbol[sym]["count"] += 1
        total += amt

    from datetime import datetime
    next_payment = FundingRateMonitor._next_funding_time(datetime.now(timezone.utc))

    return {
        "total_funding_collected_usdc": round(total, 4),
        "payment_count": len(payments),
        "by_symbol": by_symbol,
        "next_payment_times": {
            "next_utc": next_payment.isoformat(),
        }
    }


@app.get("/api/strategies/A_M2_funding_rate/promotion-gates")
async def get_promotion_gates():
    """Check all 6 promotion gates — must all pass before going live."""
    from strategies.A_M2_funding_rate import FundingPromotionGates
    supa = _get_supabase()
    gates = FundingPromotionGates(supa)
    return await gates.check_all_gates()


# ─────────────────────────────────────────────────────────────────────────────
# A_CEX CROSS-EXCHANGE ARB — SPECIFIC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/strategies/A_CEX_cross_arb/prices")
async def get_cex_price_table():
    """Live price comparison table across all exchanges (dashboard display)."""
    from strategies.A_CEX_cross_arb import StrategyConfig, CrossExchangePriceMonitor, ALL_EXCHANGES
    config  = StrategyConfig(cache)
    monitor = CrossExchangePriceMonitor(cache, config)
    table   = await monitor.get_current_prices_table()
    return {"prices": table, "exchanges": ALL_EXCHANGES}


@app.get("/api/strategies/A_CEX_cross_arb/floats")
async def get_cex_floats():
    """Current USDC float balances on each exchange."""
    supa   = _get_supabase()
    result = supa.table("exchange_floats").select("*").eq(
        "node_id", os.getenv("NODE_ID", "singapore-01")
    ).execute()
    return {"floats": result.data or []}


@app.get("/api/strategies/A_CEX_cross_arb/opportunities")
async def get_live_opportunities():
    """Current live arb opportunities (top 10) at this moment."""
    from strategies.A_CEX_cross_arb import StrategyConfig, CrossExchangePriceMonitor
    config  = StrategyConfig(cache)
    monitor = CrossExchangePriceMonitor(cache, config)
    opps    = await monitor.find_opportunities()
    return {
        "count": len(opps),
        "opportunities": [
            {
                "symbol":          o.symbol,
                "buy":             o.buy_exchange,
                "sell":            o.sell_exchange,
                "gap_pct":         round(o.gap_pct, 4),
                "net_pct":         round(o.net_profit_pct, 4),
                "size_usdc":       o.trade_size_usdc,
                "expected_profit": round(o.expected_profit_usdc, 2),
            }
            for o in opps[:10]
        ],
    }


@app.get("/api/strategies/A_CEX_cross_arb/performance-by-pair")
async def get_pair_performance():
    """Win rate, PnL, and avg execution time broken down per exchange pair."""
    supa   = _get_supabase()
    result = supa.table("trades").select(
        "exchange, pnl_usdc, outcome, latency_ms"
    ).eq("strategy_id", "A_CEX_cross_arb").execute()

    by_pair: dict = {}
    for t in (result.data or []):
        pair = t.get("exchange", "unknown")
        if pair not in by_pair:
            by_pair[pair] = {"trades": 0, "wins": 0, "pnl": 0.0, "ms_list": []}
        by_pair[pair]["trades"] += 1
        if t.get("outcome") == "win":
            by_pair[pair]["wins"] += 1
        by_pair[pair]["pnl"] += float(t.get("pnl_usdc") or 0)
        if t.get("latency_ms"):
            by_pair[pair]["ms_list"].append(float(t["latency_ms"]))

    for pair, s in by_pair.items():
        s["win_rate"] = round(s["wins"] / max(s["trades"], 1), 4)
        s["avg_ms"]   = round(sum(s["ms_list"]) / max(len(s["ms_list"]), 1), 1)
        del s["ms_list"]

    return {"by_pair": by_pair}


@app.get("/api/strategies/A_CEX_cross_arb/promotion-gates")
async def get_cex_promotion_gates():
    """Check all 6 promotion gates for A_CEX — must all pass before going live."""
    from strategies.A_CEX_cross_arb import CEXPromotionGates
    supa  = _get_supabase()
    gates = CEXPromotionGates(supa)
    return await gates.check_all_gates()


# ─────────────────────────────────────────────────────────────────────────────
# A_M1 TRIANGULAR ARBITRAGE — SPECIFIC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/strategies/A_M1_triangular_arb/graph-stats")
async def get_triangle_graph_stats():
    """Return graph statistics: pair count, triangle count, currency count."""
    try:
        import asyncio

        # In a production setup, access the running strategy instance
        # For MVP, return from Supabase cache
        supa = _get_supabase()

        graph_stats = {}
        try:
            graph_stats = await asyncio.wait_for(cache.get("a_m1:graph:stats"), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        if not graph_stats:
            graph_stats = {
                "total_pairs": 0,
                "currencies": 0,
                "triangles": 0,
                "graph_builds": 0,
            }

        return {
            "graph": graph_stats,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.warning("graph_stats_error", error=str(e))
        return {"graph": {}, "error": str(e)}


@app.get("/api/strategies/A_M1_triangular_arb/top-opportunities")
async def get_top_triangles(limit: int = 20):
    """Return top N currently profitable triangles."""
    try:
        import asyncio

        opportunities = []
        try:
            opportunities = await asyncio.wait_for(cache.get("a_m1:opportunities:top"), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        if not opportunities:
            opportunities = []

        return {
            "count": len(opportunities),
            "opportunities": opportunities[:limit],
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.warning("top_triangles_error", error=str(e))
        return {"opportunities": [], "error": str(e)}


@app.get("/api/strategies/A_M1_triangular_arb/performance-by-start")
async def get_performance_by_start_currency():
    """Performance breakdown by start currency (USDT/BTC/ETH/BNB)."""
    supa = _get_supabase()

    try:
        result = supa.table("strategy_executions").select(
            "triangle_id, net_profit_usdc, net_profit_pct, created_at"
        ).eq("strategy_id", "A_M1_triangular_arb").execute()

        trades = result.data or []
        by_currency: dict = {}

        for t in trades:
            tri_id = t.get("triangle_id", "")
            start_curr = tri_id.split("_")[0] if "_" in tri_id else "USDT"

            if start_curr not in by_currency:
                by_currency[start_curr] = {
                    "trades": 0,
                    "wins": 0,
                    "total_pnl_usdc": 0.0,
                    "avg_profit_pct": 0.0,
                }

            by_currency[start_curr]["trades"] += 1
            if float(t.get("net_profit_usdc") or 0) > 0:
                by_currency[start_curr]["wins"] += 1
            by_currency[start_curr]["total_pnl_usdc"] += float(t.get("net_profit_usdc") or 0)

        # Calculate averages
        for curr, stats in by_currency.items():
            if stats["trades"] > 0:
                stats["win_rate"] = round(stats["wins"] / stats["trades"], 4)
                stats["avg_profit_pct"] = round(
                    sum(float(t.get("net_profit_pct") or 0) for t in trades
                        if t.get("triangle_id", "").startswith(curr + "_")) / stats["trades"],
                    4
                )

        return {"by_currency": by_currency}

    except Exception as e:
        logger.warning("performance_by_start_error", error=str(e))
        return {"by_currency": {}}


@app.get("/api/strategies/A_M1_triangular_arb/promotion-gates")
async def get_a_m1_promotion_gates():
    """Check all 6 promotion gates for A_M1 — must all pass before going live."""
    supa = _get_supabase()

    try:
        from strategies.A_M1_triangular_arb import TrianglePromotionGates
        gates = TrianglePromotionGates(supa)
        return await gates.check_all_gates()
    except Exception as e:
        logger.warning("a_m1_gates_error", error=str(e))
        return {
            "all_passed": False,
            "strategy_id": "A_M1_triangular_arb",
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# LIVE-TEST CONTROL — arm/disarm + master trading toggle
# Cross-process: API writes to cache, scanner's LiveTestState reload_loop picks
# up changes within ~2s. Keys match LiveTestState._key() format exactly.
# ─────────────────────────────────────────────────────────────────────────────

class _LiveTestArmBody(BaseModel):
    count: int
    size_usdc: Optional[float] = None
    cooldown_s: Optional[float] = None


class _TradingToggleBody(BaseModel):
    master_enabled: Optional[bool] = None
    dry_run_enabled: Optional[bool] = None
    size_usdc: Optional[float] = None
    cooldown_s: Optional[float] = None


async def _get_live_test_state(strategy_id: str):
    """Instantiate a LiveTestState against the shared cache and load current
    persisted state. Cheap — it's just a cache GET. Validated strategy_ids only."""
    from execution.live_test_state import LiveTestState
    # Whitelist — only strategies that support live execution
    allowed = {"A_M1_triangular_arb"}
    if strategy_id not in allowed:
        raise HTTPException(400, f"live-test not supported for {strategy_id}")
    state = LiveTestState(cache, strategy_id)
    await state.load()
    return state


@app.get("/api/strategies/{strategy_id}/live-test/status")
async def get_live_test_status(strategy_id: str):
    """Return current arm/disarm + master toggle + last-fire result."""
    try:
        state = await _get_live_test_state(strategy_id)
        return {
            "strategy_id": strategy_id,
            **state.status(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("live_test_status_error", error=str(e))
        raise HTTPException(500, f"live-test status failed: {e}")


@app.post("/api/strategies/{strategy_id}/live-test/arm")
async def arm_live_test(strategy_id: str, body: _LiveTestArmBody):
    """Queue N live-test fires. Decrements on each fire.

    Body: {count, size_usdc?, cooldown_s?}

    Safety: size is capped at $100 per fire; count at 50 per request.
    """
    if body.count <= 0 or body.count > 50:
        raise HTTPException(400, "count must be 1–50")
    if body.size_usdc is not None and (body.size_usdc <= 0 or body.size_usdc > 100):
        raise HTTPException(400, "size_usdc must be 0–100 for live-test")

    state = await _get_live_test_state(strategy_id)
    if body.size_usdc is not None:
        await state.set_test_size(body.size_usdc)
    if body.cooldown_s is not None:
        await state.set_cooldown(body.cooldown_s)
    status = await state.arm(body.count)
    return {"strategy_id": strategy_id, **status}


@app.post("/api/strategies/{strategy_id}/live-test/disarm")
async def disarm_live_test(strategy_id: str):
    """Reset armed_count to 0 — scanner reverts to paper on next opportunity."""
    state = await _get_live_test_state(strategy_id)
    status = await state.disarm()
    return {"strategy_id": strategy_id, **status}


@app.post("/api/strategies/{strategy_id}/trading/toggle")
async def toggle_trading(strategy_id: str, body: _TradingToggleBody):
    """Flip master trading, dry-run mode, size, or cooldown.

    Body: {master_enabled?, dry_run_enabled?, size_usdc?, cooldown_s?}

    Master = False → nothing fires live/dry-run even if armed.
    dry_run = True → fires go to Binance as rejected orders (latency-only).
    """
    state = await _get_live_test_state(strategy_id)
    if body.master_enabled is not None:
        await state.set_master(bool(body.master_enabled))
    if body.dry_run_enabled is not None:
        await state.set_dry_run(bool(body.dry_run_enabled))
    if body.size_usdc is not None:
        if body.size_usdc <= 0 or body.size_usdc > 100:
            raise HTTPException(400, "size_usdc must be 0–100 for live-test")
        await state.set_test_size(body.size_usdc)
    if body.cooldown_s is not None:
        await state.set_cooldown(body.cooldown_s)
    return {"strategy_id": strategy_id, **state.status()}


@app.get("/api/strategies/A_M1_triangular_arb/live-triangles")
async def get_live_triangles(limit: int = 50):
    """
    Return triangles currently being evaluated by the A_M1 scanner.
    Shows which triangle pairs are being checked in real-time, their profits,
    and evaluation status.
    """
    try:
        import asyncio

        # Get data from cache with timeout protection
        graph_stats = {}
        opportunities = []
        live_triangles = []

        try:
            graph_stats = await asyncio.wait_for(cache.get("a_m1:graph:stats"), timeout=2.0) or {}
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        try:
            opportunities = await asyncio.wait_for(cache.get("a_m1:opportunities:top"), timeout=2.0) or []
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        try:
            live_triangles = await asyncio.wait_for(cache.get("a_m1:triangles:live"), timeout=2.0) or []
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        # If no graph stats yet, strategy hasn't fully initialized
        has_graph = bool(graph_stats and graph_stats.get("total_pairs", 0) > 0)

        # Read best profit from L1 cache (written by scanner heartbeat)
        best_profit_data = {}
        try:
            import time as _time
            entry = cache._L1.get("a_m1:best_profit")
            if entry and _time.monotonic() < entry[1]:
                best_profit_data = entry[0]
        except Exception:
            pass

        # Merge best profit into graph_stats for frontend
        merged_stats = {**(graph_stats or {}), **best_profit_data}

        return {
            "strategy_id": "A_M1_triangular_arb",
            "status": "running" if has_graph else "initializing",
            "evaluated_count": len(live_triangles),
            "graph_stats": merged_stats,
            "triangles_evaluated": live_triangles[:limit],
            "top_opportunities": opportunities[:limit],
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.warning("live_triangles_error", error=str(e))
        return {
            "status": "error",
            "evaluated_count": 0,
            "triangles_evaluated": [],
            "top_opportunities": [],
            "graph_stats": {},
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────
# GLOBAL DASHBOARD ENDPOINTS
# /api/stats, /api/trades, /api/open, /api/scanner, /api/strategies/{id}/detail
# ─────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """System-wide stats for dashboard header: capital, PnL, trade counts."""
    supa = db._client
    try:
        # Capital pool
        pool = supa.table("capital_pools").select(
            "current_balance, pool_id"
        ).eq("pool_id", "crypto_sg").single().execute()
        capital = float((pool.data or {}).get("current_balance") or 0.0)
    except Exception:
        capital = 0.0

    try:
        # Aggregate PnL + trade counts from strategy_plugins
        plugins = supa.table("strategy_plugins").select(
            "total_pnl_usdc, paper_trades_count, live_trades_count, win_rate"
        ).execute()
        rows = plugins.data or []
        total_pnl   = sum(float(r.get("total_pnl_usdc") or 0) for r in rows)
        paper_total = sum(int(r.get("paper_trades_count") or 0) for r in rows)
        live_total  = sum(int(r.get("live_trades_count") or 0) for r in rows)
        win_rates   = [float(r["win_rate"]) for r in rows if r.get("win_rate")]
        avg_wr      = round(sum(win_rates) / len(win_rates), 4) if win_rates else None
    except Exception:
        total_pnl = paper_total = live_total = 0
        avg_wr = None

    return {
        "capital_usdc":       round(capital, 2),
        "total_pnl_usdc":     round(total_pnl, 4),
        "paper_trades_total": paper_total,
        "live_trades_total":  live_total,
        "avg_win_rate":       avg_wr,
        "node_id":            os.getenv("NODE_ID", "singapore-01"),
        "timestamp":          datetime.utcnow().isoformat(),
    }


@app.get("/api/trades")
async def get_recent_trades(limit: int = 20):
    """Recent trade executions across all strategies, newest first."""
    supa = db._client
    try:
        result = supa.table("strategy_executions").select(
            "id, strategy_id, triangle_id, is_paper, net_profit_pct, "
            "net_profit_usdc, execution_ms, status, error, created_at"
        ).order("created_at", desc=True).limit(limit).execute()
        return {"trades": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        logger.warning("get_trades_error", error=str(e))
        return {"trades": [], "count": 0, "error": str(e)}


@app.get("/api/open")
async def get_open_positions():
    """All currently open positions (funding + any live positions)."""
    supa = db._client
    positions = []

    # Funding rate positions (A_M2)
    try:
        result = supa.table("funding_positions").select("*").eq(
            "status", "holding"
        ).execute()
        for row in (result.data or []):
            row["strategy_id"] = "A_M2_funding_rate"
            positions.append(row)
    except Exception:
        pass

    # Any live strategy_executions still open (no close timestamp)
    try:
        result = supa.table("strategy_executions").select(
            "id, strategy_id, triangle_id, net_profit_usdc, created_at"
        ).eq("status", "open").order("created_at", desc=True).limit(50).execute()
        positions.extend(result.data or [])
    except Exception:
        pass

    return {"positions": positions, "count": len(positions)}


@app.get("/api/scanner")
async def get_scanner_status():
    """Scanner heartbeat and latest cycle stats."""
    supa = db._client
    try:
        # Latest scanner cycle
        result = supa.table("scanner_cycles").select(
            "node_id, cycle_at, markets_scored, duration_ms, regime, allocation"
        ).order("cycle_at", desc=True).limit(1).execute()
        latest = (result.data or [None])[0]
    except Exception:
        latest = None

    try:
        # Node online status
        node = supa.table("node_status").select(
            "node_id, last_seen, status"
        ).eq("node_id", os.getenv("NODE_ID", "singapore-01")).single().execute()
        node_data = node.data or {}
    except Exception:
        node_data = {}

    return {
        "node_id":        os.getenv("NODE_ID", "singapore-01"),
        "status":         node_data.get("status", "unknown"),
        "last_seen":      node_data.get("last_seen"),
        "latest_cycle":   latest,
        "timestamp":      datetime.utcnow().isoformat(),
    }


def _map_execution_to_trade(row: dict) -> dict:
    """
    Map a strategy_executions row to the trade shape the frontend expects.
    Frontend fields: symbol, direction, size_usdc, outcome, edge_detected,
                     is_paper, created_at, ai_reasoning, entry_price
    """
    tri_id   = row.get("triangle_id", "")
    pnl_pct  = float(row.get("net_profit_pct") or 0)
    pnl_usdc = float(row.get("net_profit_usdc") or 0)
    status   = row.get("status", "success")

    # Approximate trade size from pnl (net_profit_usdc = size * net_profit_pct/100)
    size_usdc = round(pnl_usdc / (pnl_pct / 100), 2) if pnl_pct else 0.0

    outcome = "won" if pnl_usdc > 0 else ("lost" if status == "failed" else "pending")

    return {
        "symbol":       tri_id.replace("_", "→").rstrip("→0").rstrip("→"),
        "direction":    "ARB",
        "size_usdc":    size_usdc,
        "outcome":      outcome,
        "edge_detected": round(pnl_pct, 4),
        "is_paper":     row.get("is_paper", True),
        "created_at":   row.get("created_at"),
        "entry_price":  None,
        "ai_reasoning": f"Triangle arb: {tri_id} | net {pnl_pct:+.4f}% | ${pnl_usdc:+.4f}",
        # Raw fields for completeness
        "net_profit_pct":  pnl_pct,
        "net_profit_usdc": pnl_usdc,
        "execution_ms":    row.get("execution_ms"),
        "triangle_id":     tri_id,
    }


@app.get("/api/strategies/{strategy_id}/trades")
async def get_strategy_trades(strategy_id: str, limit: int = 50):
    """Trade history for one strategy — used by strategy detail trades tab."""
    supa = _get_supabase()
    try:
        result = supa.table("strategy_executions").select(
            "triangle_id, is_paper, net_profit_pct, net_profit_usdc, "
            "execution_ms, status, error, created_at"
        ).eq("strategy_id", strategy_id).order(
            "created_at", desc=True
        ).limit(limit).execute()
        trades = [_map_execution_to_trade(r) for r in (result.data or [])]
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        logger.warning("get_strategy_trades_error", error=str(e))
        return {"trades": [], "count": 0, "error": str(e)}


@app.get("/api/strategies/{strategy_id}/detail")
async def get_strategy_detail(strategy_id: str):
    """
    Full detail for one strategy.
    Returns { strategy, trades, stats, versions } — shape expected by StrategyDetailPage.
    """
    supa = _get_supabase()

    # Load plugin row
    try:
        plugin = supa.table("strategy_plugins").select("*").eq(
            "strategy_id", strategy_id
        ).single().execute()
        if not plugin.data:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Load all executions for this strategy (for trades list + live stats)
    try:
        exec_result = supa.table("strategy_executions").select(
            "triangle_id, is_paper, net_profit_pct, net_profit_usdc, "
            "execution_ms, status, error, created_at"
        ).eq("strategy_id", strategy_id).order(
            "created_at", desc=True
        ).limit(50).execute()
        exec_rows = exec_result.data or []
    except Exception:
        exec_rows = []

    # Compute live stats from executions (not from stale strategy_plugins counters)
    paper_count = sum(1 for r in exec_rows if r.get("is_paper"))
    live_count  = sum(1 for r in exec_rows if not r.get("is_paper"))
    total       = len(exec_rows)
    wins        = sum(1 for r in exec_rows if float(r.get("net_profit_usdc") or 0) > 0)
    total_pnl   = sum(float(r.get("net_profit_usdc") or 0) for r in exec_rows)
    win_rate    = round((wins / total) * 100, 1) if total > 0 else 0.0

    trades = [_map_execution_to_trade(r) for r in exec_rows]

    # Version snapshots
    try:
        ver_result = supa.table("latency_versions").select(
            "version_tag, created_at, win_rate_at_save, pnl_at_save"
        ).eq("strategy_id", strategy_id).order(
            "created_at", desc=True
        ).limit(10).execute()
        versions = ver_result.data or []
    except Exception:
        versions = []

    data = plugin.data
    return {
        "strategy": {
            "strategy_id":      data.get("strategy_id"),
            "display_name":     data.get("display_name"),
            "category":         data.get("category"),
            "category_label":   data.get("category_label"),
            "mode":             data.get("mode", "paper"),
            "enabled":          data.get("enabled", False),
            "kelly_multiplier": data.get("kelly_multiplier", 1.0),
            "max_capital_pct":  data.get("max_capital_pct", 0.05),
            "config":           data.get("config") or {},
            "notes":            data.get("notes"),
            "version_tag":      data.get("version_tag"),
            "description":      data.get("description"),
            "file_name":        data.get("file_name"),
        },
        "trades": trades,
        "stats": {
            "win_rate":           win_rate,       # percentage e.g. 100.0
            "total_trades":       total,
            "paper_trades":       paper_count,
            "live_trades":        live_count,
            "wins":               wins,
            "losses":             total - wins,
            "total_pnl_usdc":     round(total_pnl, 4),
            "open_collected_usdc": 0.0,           # triangular arb has no open positions
        },
        "versions": versions,
        "timestamp": datetime.utcnow().isoformat(),
    }
