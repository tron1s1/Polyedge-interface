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
