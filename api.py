"""
Dashboard FastAPI backend — reads live data from Supabase.
Run: uvicorn api:app --reload --port 8000
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI(title="AlphaNode Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_query(fn):
    """Wrap a Supabase query — return empty on error instead of 500."""
    try:
        result = fn()
        return result.data if result.data else []
    except Exception as e:
        print(f"Supabase query error: {e}")
        return []


def safe_single(fn, default=None):
    """Wrap a Supabase query expecting a single row."""
    try:
        result = fn()
        return result.data if result.data else default
    except Exception:
        return default


@app.get("/api/version")
def get_version():
    return {"version": "pnl_fix_v2", "today_pnl_uses": "pnl_usdc_not_size"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/overview
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/overview")
def get_overview(mode: str = "paper"):
    nodes = safe_query(lambda: db.table("nodes").select("*").execute())
    pools = safe_query(lambda: db.table("capital_pools").select("*").execute())

    # Today's PnL from trades (filter by mode)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
    is_paper = mode == "paper"
    trades_today = safe_query(
        lambda: db.table("trades").select("size_usdc,pnl_usdc,outcome,direction,is_paper")
        .gte("created_at", today_start).execute()
    )
    mode_trades = [t for t in trades_today if bool(t.get("is_paper")) == is_paper]

    def _today_pnl_val(t):
        # Use pnl_usdc when set (CEX arb, any strategy that writes actual profit).
        # For strategies that only write size_usdc (legacy), pnl_usdc is None — skip rather
        # than misreporting the full notional as profit.
        v = t.get("pnl_usdc")
        return float(v) if v is not None else 0.0

    today_pnl = sum(_today_pnl_val(t) for t in mode_trades if t.get("outcome") == "won") + \
                sum(_today_pnl_val(t) for t in mode_trades if t.get("outcome") == "lost")

    # Paper capital total from strategy_flags
    paper_capital = 0.0
    if is_paper:
        flags = safe_query(lambda: db.table("strategy_flags").select("max_capital").execute())
        paper_capital = sum(float(f.get("max_capital") or 0) for f in flags)

    # Current regime
    regime_row = safe_single(
        lambda: db.table("deployment_config").select("value")
        .eq("key", "global_regime").single().execute(),
        default={"value": "UNKNOWN"}
    )

    live_capital = sum(p.get("current_balance") or 0 for p in pools)

    return {
        "nodes": nodes,
        "capital_pools": pools,
        "today_pnl_usdc": round(today_pnl, 2),
        "today_trades": len(mode_trades),
        "regime": regime_row.get("value", "UNKNOWN") if isinstance(regime_row, dict) else "UNKNOWN",
        "total_capital_usdc": paper_capital if is_paper else live_capital,
        "mode": mode,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/nodes
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/nodes")
def get_nodes():
    nodes = safe_query(lambda: db.table("nodes").select("*").execute())
    return {"nodes": nodes}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/strategies
# ─────────────────────────────────────────────────────────────────────────────
def _get_built_plugins() -> set:
    """Scan strategies/ folder for .py files. Returns set of strategy_ids that have a plugin."""
    strategies_dir = os.path.join(os.path.dirname(__file__), "node1-scanner", "strategies")
    built = set()
    try:
        for fname in os.listdir(strategies_dir):
            if fname.endswith(".py") and not fname.startswith("_"):
                built.add(fname[:-3])  # strip .py
    except Exception:
        pass
    return built


@app.get("/api/strategies")
def get_strategies():
    plugins = safe_query(lambda: db.table("strategy_plugins").select("*").execute())
    flags = safe_query(lambda: db.table("strategy_flags").select("*").execute())
    built_plugins = _get_built_plugins()
    all_trades = safe_query(lambda: db.table("trades").select("strategy_id,outcome,size_usdc,is_paper,pnl_usdc").execute())
    open_positions = safe_query(
        lambda: db.table("funding_positions").select("id,strategy_id,funding_collected_usdc,is_paper")
        .neq("status", "closed").execute()
    )
    # Fallback: if funding_collected_usdc is 0 for all open positions, read from funding_payments
    # (scanner syncs funding_collected_usdc on each payment; before first sync it's 0)
    open_collected_zero = all(float(p.get("funding_collected_usdc") or 0) == 0 for p in open_positions)
    if open_collected_zero and open_positions:
        open_ids = [p["id"] for p in open_positions if p.get("id")]
        all_fp_payments = safe_query(
            lambda: db.table("funding_payments").select("position_id,cumulative_total")
            .in_("position_id", open_ids).execute()
        ) if open_ids else []
        # Max cumulative per position
        _best: dict = {}
        for pay in all_fp_payments:
            pid = pay.get("position_id")
            val = float(pay.get("cumulative_total") or 0)
            if val > _best.get(pid, 0):
                _best[pid] = val
        # Map position_id → strategy_id for attribution
        _pid_to_sid = {p["id"]: p["strategy_id"] for p in open_positions if p.get("id")}
        _fp_collected_by_sid: dict = {}
        for pid, val in _best.items():
            sid = _pid_to_sid.get(pid, "")
            _fp_collected_by_sid[sid] = _fp_collected_by_sid.get(sid, 0) + val
    else:
        _fp_collected_by_sid = {}

    closed_funding = safe_query(
        lambda: db.table("funding_positions").select("strategy_id,total_pnl_usdc,is_paper")
        .eq("status", "closed").execute()
    )

    # Aggregate trade stats per strategy
    stats: dict = {}
    for t in all_trades:
        sid = t.get("strategy_id", "")
        if sid not in stats:
            stats[sid] = {"wins": 0, "losses": 0, "pending": 0, "pnl": 0.0, "paper": 0, "live": 0}
        s = stats[sid]
        outcome = t.get("outcome")
        pnl_val = t.get("pnl_usdc")
        pnl = float(pnl_val) if pnl_val is not None else float(t.get("size_usdc") or 0)
        if outcome == "won":
            s["wins"] += 1
            s["pnl"] += pnl
        elif outcome == "lost":
            s["losses"] += 1
            s["pnl"] += pnl  # pnl_usdc is already negative for losses
        elif outcome == "pending":
            s["pending"] += 1
        if t.get("is_paper"):
            s["paper"] += 1
        else:
            s["live"] += 1

    # Add collected funding P&L from open positions (accrued, not yet closed)
    if _fp_collected_by_sid:
        # Using funding_payments fallback (funding_collected_usdc not yet synced)
        for sid, collected in _fp_collected_by_sid.items():
            if sid not in stats:
                stats[sid] = {"wins": 0, "losses": 0, "pending": 0, "pnl": 0.0, "paper": 0, "live": 0}
            stats[sid]["pnl"] += collected
    else:
        for fp in open_positions:
            sid = fp.get("strategy_id", "")
            if sid in stats:
                stats[sid]["pnl"] += float(fp.get("funding_collected_usdc") or 0)

    # Add wins/losses/pnl from closed funding positions (A_M2 and any funding strategy)
    for fp in closed_funding:
        sid = fp.get("strategy_id", "")
        if sid not in stats:
            stats[sid] = {"wins": 0, "losses": 0, "pending": 0, "pnl": 0.0, "paper": 0, "live": 0}
        pnl = float(fp.get("total_pnl_usdc") or 0)
        if pnl > 0:
            stats[sid]["wins"] += 1
        elif pnl < 0:
            stats[sid]["losses"] += 1
        stats[sid]["pnl"] += pnl
        if fp.get("is_paper"):
            stats[sid]["paper"] += 1
        else:
            stats[sid]["live"] += 1

    # Join flags + live stats into plugins
    flag_map = {f["strategy_id"]: f for f in flags}
    for p in plugins:
        sid = p.get("strategy_id", "")
        f = flag_map.get(sid, {})
        p["enabled"] = f.get("enabled", False)
        p["mode"] = f.get("mode", "paper")
        p["has_plugin"] = sid in built_plugins
        s = stats.get(sid, {})
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        total_closed = wins + losses
        p["win_rate"] = round(wins / total_closed * 100, 1) if total_closed else 0
        p["total_pnl_usdc"] = round(s.get("pnl", 0.0), 2)
        p["paper_trades_count"] = s.get("paper", 0)
        p["live_trades_count"] = s.get("live", 0)
        p["pending_trades"] = s.get("pending", 0)

    return {"strategies": plugins}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scanner/live
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/scanner/live")
def get_scanner_live(node_id: str = "singapore-01"):
    cycles = safe_query(
        lambda: db.table("scanner_cycles").select("*")
        .eq("node_id", node_id)
        .order("cycle_at", desc=True)
        .limit(50)
        .execute()
    )
    return {"cycles": cycles}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scanner/opportunities
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/scanner/opportunities")
def get_scanner_opportunities(node_id: str = "singapore-01"):
    latest = safe_query(
        lambda: db.table("scanner_cycles").select("top_opportunities,cycle_at,markets_scored,duration_ms")
        .eq("node_id", node_id)
        .order("cycle_at", desc=True)
        .limit(1)
        .execute()
    )
    if latest:
        return latest[0]
    return {"top_opportunities": [], "cycle_at": None, "markets_scored": 0, "duration_ms": 0}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/risk/current
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/risk/current")
def get_risk_current():
    snapshot = safe_query(
        lambda: db.table("risk_snapshots").select("*")
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    )

    regime_row = safe_single(
        lambda: db.table("deployment_config").select("value")
        .eq("key", "global_regime").single().execute(),
        default={"value": "UNKNOWN"}
    )

    kill_row = safe_single(
        lambda: db.table("deployment_config").select("value")
        .eq("key", "kill_switch_global").single().execute(),
        default={"value": "false"}
    )

    # Regime history
    regime_history = safe_query(
        lambda: db.table("market_regime").select("*")
        .order("detected_at", desc=True)
        .limit(20)
        .execute()
    )

    return {
        "snapshot": snapshot[0] if snapshot else {},
        "regime": regime_row.get("value", "UNKNOWN") if isinstance(regime_row, dict) else "UNKNOWN",
        "kill_switch_active": (kill_row.get("value", "false") if isinstance(kill_row, dict) else "false") == "true",
        "regime_history": regime_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/portfolio
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/portfolio")
def get_portfolio(mode: str = "paper"):
    """
    Portfolio data. mode=paper returns paper trading allocations per strategy.
    mode=live returns real capital pools from capital_pools table.
    """
    if mode == "live":
        pools = safe_query(lambda: db.table("capital_pools").select("*").execute())
        return {"mode": "live", "pools": pools, "paper_strategies": []}

    # Paper mode: aggregate from strategy_flags + strategy_plugins + trades
    strategies = safe_query(
        lambda: db.table("strategy_plugins").select(
            "strategy_id, display_name, category, mode, win_rate, total_pnl_usdc"
        ).execute()
    )
    flags = safe_query(
        lambda: db.table("strategy_flags").select(
            "strategy_id, enabled, mode, max_capital"
        ).execute()
    )
    flags_map = {f["strategy_id"]: f for f in flags}

    paper_strategies = []
    total_paper_capital = 0.0
    total_paper_pnl = 0.0

    for s in strategies:
        sid = s["strategy_id"]
        flag = flags_map.get(sid, {})
        capital = float(flag.get("max_capital") or 0)
        pnl = float(s.get("total_pnl_usdc") or 0)
        paper_strategies.append({
            "strategy_id": sid,
            "display_name": s.get("display_name", sid),
            "category": s.get("category", ""),
            "enabled": flag.get("enabled", False),
            "mode": flag.get("mode", s.get("mode", "paper")),
            "max_capital": capital,
            "total_pnl_usdc": pnl,
            "win_rate": float(s.get("win_rate") or 0),
        })
        total_paper_capital += capital
        total_paper_pnl += pnl

    # Paper trade counts
    paper_trades = safe_query(
        lambda: db.table("trades").select("strategy_id, outcome, size_usdc, is_paper")
        .eq("is_paper", True).execute()
    )
    wins = [t for t in paper_trades if t.get("outcome") == "won"]
    losses = [t for t in paper_trades if t.get("outcome") == "lost"]

    return {
        "mode": "paper",
        "pools": [],
        "paper_strategies": paper_strategies,
        "summary": {
            "total_allocated_usdc": total_paper_capital,
            "total_pnl_usdc": round(total_paper_pnl, 2),
            "total_trades": len(paper_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(paper_trades) * 100, 1) if paper_trades else 0,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/tax/summary
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/tax/summary")
def get_tax_summary():
    events = safe_query(
        lambda: db.table("tax_events").select("*").execute()
    )

    # Group by financial year
    by_fy = {}
    for e in events:
        fy = e.get("financial_year", "2025-26")
        if fy not in by_fy:
            by_fy[fy] = {"gains": 0, "losses": 0, "tax_reserved": 0, "tds": 0, "events": []}
        amount = e.get("profit_usdc", 0) or 0
        if amount >= 0:
            by_fy[fy]["gains"] += amount
        else:
            by_fy[fy]["losses"] += abs(amount)
        by_fy[fy]["tax_reserved"] += e.get("tax_reserved_inr", 0) or 0
        by_fy[fy]["tds"] += e.get("tds_inr", 0) or 0
        by_fy[fy]["events"].append(e)

    return {"by_financial_year": by_fy, "all_events": events}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/versions
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/versions")
def get_versions():
    versions = safe_query(
        lambda: db.table("latency_versions").select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return {"versions": versions}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/config/apis
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# POST /api/strategies/{strategy_id}/config
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/strategies/{strategy_id}/config")
def update_strategy_config(strategy_id: str, body: dict):
    """Update strategy config fields. Generic fields + strategy-specific config jsonb."""
    generic_fields = {"mode", "max_capital_pct", "kelly_multiplier", "notes"}
    generic_updates = {k: v for k, v in body.items() if k in generic_fields}
    # strategy_config is a jsonb field for strategy-specific params (e.g. A_M1 tuning)
    strategy_config_update = body.get("strategy_config")

    if not generic_updates and not strategy_config_update:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    try:
        if generic_updates:
            db.table("strategy_plugins").update(generic_updates).eq("strategy_id", strategy_id).execute()
            if "mode" in generic_updates:
                db.table("strategy_flags").upsert(
                    {"strategy_id": strategy_id, "mode": generic_updates["mode"]},
                    on_conflict="strategy_id"
                ).execute()

        if strategy_config_update and isinstance(strategy_config_update, dict):
            # Fetch existing strategy_config to merge (partial update)
            existing = safe_single(
                lambda: db.table("strategy_plugins").select("strategy_config")
                .eq("strategy_id", strategy_id).single().execute(),
                default={}
            )
            existing_cfg = existing.get("strategy_config") or {}
            if isinstance(existing_cfg, str):
                import json as _json
                existing_cfg = _json.loads(existing_cfg)
            merged = {**existing_cfg, **strategy_config_update}
            db.table("strategy_plugins").update({"strategy_config": merged}).eq("strategy_id", strategy_id).execute()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"strategy_id": strategy_id, "updated": {**generic_updates, **({"strategy_config": strategy_config_update} if strategy_config_update else {})}}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/strategies/{strategy_id}/trades
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/strategies/{strategy_id}/trades")
def get_strategy_trades(strategy_id: str, limit: int = 50):
    """Get recent trades for a specific strategy."""
    trades = safe_query(
        lambda: db.table("trades").select("*")
        .eq("strategy_id", strategy_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"trades": trades, "count": len(trades)}


@app.get("/api/config/apis")
def get_api_config():
    configs = safe_query(lambda: db.table("api_config").select("*").execute())
    return {"apis": configs}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/strategies/{strategy_id}/toggle
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/strategies/{strategy_id}/toggle")
def toggle_strategy(strategy_id: str):
    # Get current state (row may not exist yet)
    current = safe_single(
        lambda: db.table("strategy_flags").select("enabled")
        .eq("strategy_id", strategy_id).single().execute(),
        default=None
    )
    new_enabled = not current.get("enabled", False) if current else True
    try:
        db.table("strategy_flags").upsert({
            "strategy_id": strategy_id,
            "enabled": new_enabled,
        }, on_conflict="strategy_id").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"strategy_id": strategy_id, "enabled": new_enabled}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/strategies/{strategy_id}/detail
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/strategies/{strategy_id}/detail")
def get_strategy_detail(strategy_id: str):
    """Full detail for a single strategy — plugin, flags, trades, versions, live config."""
    import importlib, sys

    # Plugin data
    plugin = safe_single(
        lambda: db.table("strategy_plugins").select("*")
        .eq("strategy_id", strategy_id).single().execute(),
        default=None
    )
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    # Flags
    flags = safe_single(
        lambda: db.table("strategy_flags").select("*")
        .eq("strategy_id", strategy_id).single().execute(),
        default={}
    )
    plugin["enabled"] = flags.get("enabled", False) if flags else False
    plugin["mode"] = flags.get("mode", "paper") if flags else "paper"
    plugin["max_capital"] = flags.get("max_capital", 0) if flags else 0
    plugin["has_plugin"] = strategy_id in _get_built_plugins()

    # ── Load DEFAULT_CONFIG from the strategy plugin dynamically ─────────────
    default_config = {}
    scanner_path = os.path.join(os.path.dirname(__file__), "node1-scanner")
    if scanner_path not in sys.path:
        sys.path.insert(0, scanner_path)
    try:
        mod = importlib.import_module(f"strategies.{strategy_id}")
        default_config = getattr(mod, "DEFAULT_CONFIG", {})
    except Exception:
        default_config = {}

    # Merge: DB strategy_config overrides defaults (so current saved values show)
    db_strategy_config = plugin.get("strategy_config") or {}
    if isinstance(db_strategy_config, str):
        import json
        try:
            db_strategy_config = json.loads(db_strategy_config)
        except Exception:
            db_strategy_config = {}
    merged_config = {**default_config, **db_strategy_config}
    plugin["strategy_config"] = merged_config
    plugin["default_config"] = default_config

    # Recent trades
    trades = safe_query(
        lambda: db.table("trades").select("*")
        .eq("strategy_id", strategy_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )

    # Compute stats from trades
    won = [t for t in trades if t.get("outcome") == "won"]
    lost = [t for t in trades if t.get("outcome") == "lost"]
    # Use pnl_usdc when available (instant strategies like CEX arb write real profit);
    # fall back to size_usdc for older strategies that don't set pnl_usdc.
    def _trade_pnl(t):
        v = t.get("pnl_usdc")
        return float(v) if v is not None else float(t.get("size_usdc", 0))
    total_pnl = sum(_trade_pnl(t) for t in won) + sum(_trade_pnl(t) for t in lost)
    paper_trades = [t for t in trades if t.get("is_paper")]
    live_trades = [t for t in trades if not t.get("is_paper")]

    # For funding-rate strategies (A_M2): stats live in funding_positions, not trades.
    # Each closed position = one trade cycle; total_pnl_usdc is the real result.
    funding_closed = safe_query(
        lambda: db.table("funding_positions").select("*")
        .eq("strategy_id", strategy_id)
        .eq("status", "closed")
        .order("closed_at", desc=True)
        .limit(200)
        .execute()
    )
    if funding_closed:
        fp_won  = [p for p in funding_closed if float(p.get("total_pnl_usdc") or 0) > 0]
        fp_lost = [p for p in funding_closed if float(p.get("total_pnl_usdc") or 0) <= 0]
        won  = won  + fp_won
        lost = lost + fp_lost
        total_pnl += sum(float(p.get("total_pnl_usdc") or 0) for p in funding_closed)
        fp_paper = [p for p in funding_closed if p.get("is_paper")]
        fp_live  = [p for p in funding_closed if not p.get("is_paper")]
        paper_trades = paper_trades + fp_paper
        live_trades  = live_trades  + fp_live

    # Add collected funding from still-open positions.
    # Primary: funding_positions.funding_collected_usdc (synced by scanner on each payment).
    # Fallback: funding_payments.cumulative_total — sum of latest cumulative per position
    # (handles the case where scanner hasn't synced yet, e.g. before first restart).
    funding_open = safe_query(
        lambda: db.table("funding_positions").select("id,funding_collected_usdc")
        .eq("strategy_id", strategy_id)
        .neq("status", "closed")
        .execute()
    )
    open_ids = [p["id"] for p in funding_open if p.get("id")]
    collected_from_db = sum(float(p.get("funding_collected_usdc") or 0) for p in funding_open)

    if collected_from_db == 0 and open_ids:
        # funding_collected_usdc not yet synced — read from funding_payments instead
        all_payments = safe_query(
            lambda: db.table("funding_payments")
            .select("position_id,cumulative_total")
            .in_("position_id", open_ids)
            .execute()
        )
        # Latest cumulative per position = highest cumulative_total value
        best: dict = {}
        for pay in all_payments:
            pid = pay.get("position_id")
            val = float(pay.get("cumulative_total") or 0)
            if val > best.get(pid, 0):
                best[pid] = val
        # Note: existing rows have double-counted cumulative (pre-fix bug) — divide by 2
        # New rows (post-fix) will have correct value. Heuristic: if single-payment positions
        # show cumulative == 2x amount, we halve. We just use as-is for now since the
        # divide-by-2 heuristic breaks multi-payment positions. Better to show slightly high
        # than zero.
        total_pnl += sum(best.values())
    else:
        total_pnl += collected_from_db

    all_closed = len(won) + len(lost)
    win_rate = (len(won) / all_closed * 100) if all_closed else 0

    # Versions (config change history)
    versions = safe_query(
        lambda: db.table("strategy_versions").select("*")
        .eq("strategy_id", strategy_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )

    # Capital pool
    pool = safe_single(
        lambda: db.table("capital_pools").select("*")
        .eq("pool_id", "crypto_sg").single().execute(),
        default={}
    )

    # open_collected = funding from still-open positions (already included in total_pnl).
    # Exposed separately so the frontend can subtract it before adding live client-side accrual,
    # avoiding double-counting collected payments.
    open_collected = sum(best.values()) if (collected_from_db == 0 and open_ids) else collected_from_db

    return {
        "strategy": plugin,
        "trades": trades,
        "stats": {
            "win_rate": round(win_rate, 1),
            "total_pnl_usdc": round(total_pnl, 2),
            "open_collected_usdc": round(open_collected, 4),   # portion of total_pnl from open positions
            "total_trades": len(trades) + len(funding_closed),  # trades table + closed funding positions
            "paper_trades": len(paper_trades),
            "live_trades": len(live_trades),
            "wins": len(won),
            "losses": len(lost),
        },
        "versions": versions,
        "capital_pool": pool,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/positions
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/positions")
def get_positions(mode: str = "paper", strategy_id: str = None):
    """
    Return open positions with LIVE P&L.
    Primary source: funding_positions table (A_M2 writes here with actual payments).
    Fallback: trades table outcome=pending for other strategies.
    """
    is_paper = mode == "paper"
    now = datetime.utcnow()
    positions = []
    total_pnl = 0.0
    total_deployed = 0.0

    # ── Primary: funding_positions (A_M2 delta-neutral positions) ────────────
    fp_query = lambda: db.table("funding_positions").select("*") \
        .eq("is_paper", is_paper) \
        .neq("status", "closed") \
        .order("opened_at", desc=True) \
        .execute()
    if strategy_id:
        fp_query = lambda: db.table("funding_positions").select("*") \
            .eq("is_paper", is_paper) \
            .eq("strategy_id", strategy_id) \
            .neq("status", "closed") \
            .order("opened_at", desc=True) \
            .execute()

    funding_positions = safe_query(fp_query)

    # Get all funding payments for open positions in one query
    open_ids = [p["id"] for p in funding_positions if p.get("id")]
    payments_map = {}  # position_id -> list of payments
    if open_ids:
        all_payments = safe_query(
            lambda: db.table("funding_payments").select("position_id,amount_usdc,payment_time,cumulative_total")
            .in_("position_id", open_ids).order("payment_time", desc=False).execute()
        )
        for pay in all_payments:
            pid = pay.get("position_id")
            if pid not in payments_map:
                payments_map[pid] = []
            payments_map[pid].append(pay)

    for fp in funding_positions:
        pos_id = fp.get("id")
        opened_raw = fp.get("opened_at", "")
        try:
            opened_dt = datetime.fromisoformat(opened_raw.replace("Z", "").replace("+00:00", ""))
        except Exception:
            opened_dt = now
        hours_held = max((now - opened_dt).total_seconds() / 3600, 0)

        spot_size = float(fp.get("spot_size_usdc") or 0)
        perp_size = float(fp.get("perp_size_usdc") or 0)
        size = spot_size + perp_size

        # Real collected P&L from actual funding payments
        payments = payments_map.get(pos_id, [])
        collected_pnl = sum(float(p.get("amount_usdc") or 0) for p in payments)

        # Latest cumulative from payments (most accurate)
        if payments:
            collected_pnl = float(payments[-1].get("cumulative_total") or collected_pnl)

        entry_apr = float(fp.get("entry_apr") or 0) * 100  # stored as decimal, show as %
        current_apr = float(fp.get("current_apr") or fp.get("entry_apr") or 0) * 100

        total_pnl += collected_pnl
        total_deployed += size

        positions.append({
            "id": pos_id,
            "strategy_id": fp.get("strategy_id", "A_M2_funding_rate"),
            "symbol": fp.get("symbol"),
            "exchange": "bybit",
            "direction": fp.get("direction"),
            "size_usdc": round(size, 2),
            "spot_size_usdc": round(spot_size, 2),
            "perp_size_usdc": round(perp_size, 2),
            "entry_price": fp.get("spot_entry_price"),
            "entry_apr": round(entry_apr, 2),
            "current_apr": round(current_apr, 2),
            "hours_held": round(hours_held, 1),
            "payments_received": len(payments),
            "collected_pnl": round(collected_pnl, 4),
            "unrealised_pnl": round(collected_pnl, 4),  # for funding: collected IS the P&L
            "is_paper": fp.get("is_paper"),
            "opened_at": opened_raw,
            "status": fp.get("status"),
        })

    # ── Fallback: trades outcome=pending for non-A_M2 strategies ─────────────
    # Strategies excluded from this fallback:
    #   - A_M2_funding_rate   → covered by funding_positions above
    #   - A_CEX_cross_arb     → instant round-trip; no open position state
    #                            (pending rows here are orphans from the old
    #                             duplicate-logging bug, now fixed in wiring)
    NO_OPEN_POSITION_STRATEGIES = {"A_M2_funding_rate", "A_CEX_cross_arb"}

    import re
    seen_symbols = {p["symbol"] for p in positions}
    pending_q = lambda: db.table("trades").select("*") \
        .eq("outcome", "pending").eq("is_paper", is_paper) \
        .order("created_at", desc=True).execute()
    if strategy_id:
        pending_q = lambda: db.table("trades").select("*") \
            .eq("outcome", "pending").eq("is_paper", is_paper) \
            .eq("strategy_id", strategy_id) \
            .order("created_at", desc=True).execute()

    pending_trades = safe_query(pending_q)
    for t in pending_trades:
        if t.get("strategy_id") in NO_OPEN_POSITION_STRATEGIES:
            continue  # these strategies never hold open positions
        size = float(t.get("size_usdc") or 0)
        created_raw = t.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created_raw.replace("Z", "").replace("+00:00", ""))
        except Exception:
            created_dt = now
        hours_held = max((now - created_dt).total_seconds() / 3600, 0)

        reasoning = t.get("ai_reasoning") or ""
        apr_match = re.search(r"APR:\s*([-\d.]+)%", reasoning)
        apr_pct = float(apr_match.group(1)) if apr_match else 0.0
        daily_rate = abs(apr_pct) / 365 / 100
        est_pnl = daily_rate * (hours_held / 24) * size

        total_pnl += est_pnl
        total_deployed += size
        positions.append({
            "id": t.get("id"),
            "strategy_id": t.get("strategy_id"),
            "symbol": t.get("symbol"),
            "exchange": t.get("exchange"),
            "direction": t.get("direction"),
            "size_usdc": size,
            "entry_price": t.get("entry_price"),
            "entry_apr": apr_pct,
            "current_apr": apr_pct,
            "hours_held": round(hours_held, 1),
            "payments_received": 0,
            "collected_pnl": round(est_pnl, 4),
            "unrealised_pnl": round(est_pnl, 4),
            "is_paper": t.get("is_paper"),
            "opened_at": created_raw,
            "status": "open",
        })

    return {
        "positions": positions,
        "total_unrealised_pnl": round(total_pnl, 4),
        "total_deployed_usdc": round(total_deployed, 2),
        "count": len(positions),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/capital/allocate
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/capital/allocate")
def allocate_capital(body: dict):
    """Set paper trading capital for a strategy (upserts strategy_flags.max_capital)."""
    amount = body.get("amount_usdc", 0)
    strategy_id = body.get("strategy_id")
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id required")
    try:
        db.table("strategy_flags").upsert({
            "strategy_id": strategy_id,
            "max_capital": amount,
        }, on_conflict="strategy_id").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"strategy_id": strategy_id, "max_capital": amount, "message": f"Allocated ${amount} USDC for {strategy_id}"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/strategies/{strategy_id}/reset-allocate
# Compounds realised P&L into the capital pool, clears trade history.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/strategies/{strategy_id}/reset-allocate")
def reset_and_allocate(strategy_id: str, body: dict):
    """
    Compound-reset:
      1. Sum realised pnl_usdc from trades table for this strategy
      2. Also sum funding_payments for funding-rate strategies (A_M2)
      3. Add pnl to current capital (strategy_flags.max_capital)
      4. Delete all trades for this strategy (clean slate)
      5. Log reset event to strategy_resets table (best-effort)
      6. Return { old_capital, pnl_compounded, new_capital, trades_cleared }
    """
    mode = body.get("mode", "paper")
    is_paper = mode != "live"

    # ── 1. Get current allocated capital ─────────────────────────────────────
    flags_rows = safe_query(
        lambda: db.table("strategy_flags").select("max_capital")
        .eq("strategy_id", strategy_id).execute()
    )
    old_capital = float(flags_rows[0].get("max_capital") or 0) if flags_rows else 0.0

    # ── 2. Sum realised P&L from trades ──────────────────────────────────────
    trades_rows = safe_query(
        lambda: db.table("trades").select("pnl_usdc,outcome,is_paper")
        .eq("strategy_id", strategy_id).execute()
    )
    paper_trades = [t for t in trades_rows if bool(t.get("is_paper")) == is_paper]
    closed_trades = [t for t in paper_trades if t.get("outcome") in ("won", "lost", "win", "loss")]
    trades_pnl = sum(float(t.get("pnl_usdc") or 0) for t in closed_trades)

    # ── 3. Sum collected funding for A_M2-type strategies ────────────────────
    funding_pnl = 0.0
    try:
        fp_rows = safe_query(
            lambda: db.table("funding_payments").select("amount_usdc")
            .eq("is_paper", is_paper).execute()
        )
        # Match to strategy via funding_positions
        pos_rows = safe_query(
            lambda: db.table("funding_positions").select("id")
            .eq("strategy_id", strategy_id).eq("is_paper", is_paper).execute()
        )
        pos_ids = {r["id"] for r in pos_rows}
        fp_rows_all = safe_query(
            lambda: db.table("funding_payments").select("position_id,amount_usdc")
            .eq("is_paper", is_paper).execute()
        )
        funding_pnl = sum(
            float(r.get("amount_usdc") or 0)
            for r in fp_rows_all
            if r.get("position_id") in pos_ids
        )
    except Exception:
        pass

    total_pnl = trades_pnl + funding_pnl

    # ── 4. New capital = old + compounded pnl ────────────────────────────────
    new_capital = max(0.0, old_capital + total_pnl)

    # ── 5. Update capital allocation ─────────────────────────────────────────
    try:
        db.table("strategy_flags").upsert(
            {"strategy_id": strategy_id, "max_capital": new_capital},
            on_conflict="strategy_id"
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update capital: {e}")

    # ── 6. Delete trades ──────────────────────────────────────────────────────
    trades_cleared = len(paper_trades)
    try:
        db.table("trades").delete().eq("strategy_id", strategy_id).eq("is_paper", is_paper).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear trades: {e}")

    # ── 7. Log reset event (best-effort — table may not exist yet) ────────────
    try:
        db.table("strategy_resets").insert({
            "strategy_id":     strategy_id,
            "mode":            mode,
            "old_capital":     old_capital,
            "pnl_compounded":  total_pnl,
            "new_capital":     new_capital,
            "trades_cleared":  trades_cleared,
            "reset_at":        datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass  # Table doesn't exist yet — non-fatal

    return {
        "strategy_id":    strategy_id,
        "old_capital":    round(old_capital, 2),
        "pnl_compounded": round(total_pnl, 2),
        "new_capital":    round(new_capital, 2),
        "trades_cleared": trades_cleared,
        "message":        f"Reset complete. Compounded ${total_pnl:.2f} → new pool ${new_capital:.2f}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/strategies/{strategy_id}/save-version
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/strategies/{strategy_id}/save-version")
def save_strategy_version(strategy_id: str, body: dict):
    """Save current config as a version snapshot for A/B tracking."""
    import uuid, importlib, sys, json

    # Get current plugin config
    plugin = safe_single(
        lambda: db.table("strategy_plugins").select("*")
        .eq("strategy_id", strategy_id).single().execute(),
        default=None
    )
    if not plugin:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Get flags (mode, max_capital)
    flags = safe_single(
        lambda: db.table("strategy_flags").select("*")
        .eq("strategy_id", strategy_id).single().execute(),
        default={}
    )

    version_tag = body.get("version_tag", f"v{datetime.utcnow().strftime('%Y%m%d_%H%M')}")
    notes = body.get("notes", "")

    trades_at_save = (plugin.get("paper_trades_count", 0) or 0) + (plugin.get("live_trades_count", 0) or 0)

    # Load DEFAULT_CONFIG from plugin module
    default_config = {}
    scanner_path = os.path.join(os.path.dirname(__file__), "node1-scanner")
    if scanner_path not in sys.path:
        sys.path.insert(0, scanner_path)
    try:
        mod = importlib.import_module(f"strategies.{strategy_id}")
        default_config = getattr(mod, "DEFAULT_CONFIG", {})
    except Exception:
        default_config = {}

    # Merge DB overrides on top of defaults — this is the live config at time of save
    db_strategy_config = plugin.get("strategy_config") or {}
    if isinstance(db_strategy_config, str):
        try:
            db_strategy_config = json.loads(db_strategy_config)
        except Exception:
            db_strategy_config = {}
    merged_config = {**default_config, **db_strategy_config}

    # Core record — only uses columns guaranteed to exist
    version_record = {
        "id": str(uuid.uuid4()),
        "strategy_id": strategy_id,
        "version_tag": version_tag,
        "notes": notes,
        "config_snapshot": {
            "kelly_multiplier": plugin.get("kelly_multiplier"),
            "max_capital_pct": plugin.get("max_capital_pct"),
            "mode": flags.get("mode", "paper") if flags else "paper",
            "max_capital": flags.get("max_capital", 0) if flags else 0,
            "strategy_config": merged_config,
            "win_rate_at_save": plugin.get("win_rate"),
            "pnl_at_save": plugin.get("total_pnl_usdc", 0),
            "trades_at_save": trades_at_save,
        },
        "created_at": datetime.utcnow().isoformat(),
    }

    try:
        db.table("strategy_versions").insert(version_record).execute()
        db.table("strategy_plugins").update({"version_tag": version_tag}).eq("strategy_id", strategy_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"version": version_record}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/kill-switch/trigger
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/kill-switch/trigger")
def trigger_kill_switch():
    try:
        db.table("deployment_config").update({"value": "true"}).eq(
            "key", "kill_switch_global"
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"kill_switch": "active", "message": "Global kill switch triggered"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/kill-switch/release
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/kill-switch/release")
def release_kill_switch():
    try:
        db.table("deployment_config").update({"value": "false"}).eq(
            "key", "kill_switch_global"
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"kill_switch": "released", "message": "Global kill switch released"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/notifications
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/notifications")
def get_notifications():
    """Generate live notifications from system state."""
    alerts = []
    now = datetime.utcnow()

    # 1. Kill switch active?
    kill_row = safe_single(
        lambda: db.table("deployment_config").select("value")
        .eq("key", "kill_switch_global").single().execute(),
        default={"value": "false"}
    )
    if (kill_row.get("value", "false") if isinstance(kill_row, dict) else "false") == "true":
        alerts.append({
            "id": "kill_switch",
            "type": "critical",
            "title": "Kill Switch Active",
            "message": "Global kill switch is ON — all trading halted.",
            "action": "/risk",
            "time": now.isoformat(),
        })

    # 2. Node health — check heartbeats
    nodes = safe_query(lambda: db.table("nodes").select("*").execute())
    for node in nodes:
        hb = node.get("last_heartbeat")
        if hb:
            try:
                hb_time = datetime.fromisoformat(hb.replace("Z", "+00:00").replace("+00:00", ""))
                age_min = (now - hb_time).total_seconds() / 60
                if age_min > 5:
                    alerts.append({
                        "id": f"node_offline_{node.get('node_id', '')}",
                        "type": "critical",
                        "title": f"Node Offline: {node.get('name', node.get('node_id', '?'))}",
                        "message": f"Last heartbeat {int(age_min)}m ago. Node may be down.",
                        "action": "/nodes",
                        "time": hb,
                    })
            except Exception:
                pass

    # 3. Regime warnings
    regime_row = safe_single(
        lambda: db.table("deployment_config").select("value")
        .eq("key", "global_regime").single().execute(),
        default={"value": "UNKNOWN"}
    )
    regime = regime_row.get("value", "UNKNOWN") if isinstance(regime_row, dict) else "UNKNOWN"
    if regime in ("CRASH_MAJOR", "CRASH_MINOR"):
        alerts.append({
            "id": "regime_crash",
            "type": "warning",
            "title": f"Regime: {regime.replace('_', ' ')}",
            "message": "Market in crash regime — risk limits tightened, some strategies paused.",
            "action": "/risk",
            "time": now.isoformat(),
        })
    elif regime == "UNKNOWN":
        alerts.append({
            "id": "regime_unknown",
            "type": "warning",
            "title": "Regime: Unknown",
            "message": "Market regime detector has not run yet or data is stale.",
            "action": "/risk",
            "time": now.isoformat(),
        })

    # 4. Scanner stale — no recent cycles
    latest_cycle = safe_query(
        lambda: db.table("scanner_cycles").select("cycle_at,node_id")
        .order("cycle_at", desc=True)
        .limit(1)
        .execute()
    )
    if latest_cycle:
        try:
            cycle_time = datetime.fromisoformat(
                latest_cycle[0]["cycle_at"].replace("Z", "+00:00").replace("+00:00", "")
            )
            age_min = (now - cycle_time).total_seconds() / 60
            if age_min > 2:
                alerts.append({
                    "id": "scanner_stale",
                    "type": "warning",
                    "title": "Scanner Stale",
                    "message": f"No scan cycles for {int(age_min)}m. Scanner may have stopped.",
                    "action": "/scanner",
                    "time": latest_cycle[0]["cycle_at"],
                })
        except Exception:
            pass
    else:
        alerts.append({
            "id": "scanner_no_data",
            "type": "info",
            "title": "No Scanner Data",
            "message": "No scan cycles recorded yet. Start the scanner to begin.",
            "action": "/scanner",
            "time": now.isoformat(),
        })

    # 5. Fear/Greed extremes
    regime_history = safe_query(
        lambda: db.table("market_regime").select("fear_greed_index,detected_at")
        .order("detected_at", desc=True)
        .limit(1)
        .execute()
    )
    if regime_history:
        fg = regime_history[0].get("fear_greed_index", 50)
        if fg is not None and fg <= 15:
            alerts.append({
                "id": "fear_extreme",
                "type": "info",
                "title": f"Extreme Fear ({fg})",
                "message": "Fear & Greed index at extreme low — historically signals reversal opportunity.",
                "action": "/scanner",
                "time": regime_history[0].get("detected_at", now.isoformat()),
            })
        elif fg is not None and fg >= 85:
            alerts.append({
                "id": "greed_extreme",
                "type": "warning",
                "title": f"Extreme Greed ({fg})",
                "message": "Fear & Greed at extreme high — consider tightening risk or taking profit.",
                "action": "/risk",
                "time": regime_history[0].get("detected_at", now.isoformat()),
            })

    # 6. No strategies enabled
    flags = safe_query(lambda: db.table("strategy_flags").select("strategy_id,enabled").execute())
    enabled_count = sum(1 for f in flags if f.get("enabled"))
    if enabled_count == 0:
        alerts.append({
            "id": "no_strategies",
            "type": "info",
            "title": "No Strategies Enabled",
            "message": f"{'All ' + str(len(flags)) + ' strategies are' if flags else 'No strategies'} disabled. Enable strategies to start trading.",
            "action": "/strategies",
            "time": now.isoformat(),
        })

    # 7. Risk snapshot warnings
    snapshot = safe_query(
        lambda: db.table("risk_snapshots").select("*")
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    )
    if snapshot:
        s = snapshot[0]
        drawdown = s.get("drawdown_pct", 0) or 0
        if drawdown > 10:
            alerts.append({
                "id": "drawdown_high",
                "type": "critical",
                "title": f"High Drawdown: {drawdown:.1f}%",
                "message": "Maximum drawdown exceeds 10%. Consider activating kill switch.",
                "action": "/risk",
                "time": s.get("created_at", now.isoformat()),
            })

    # Sort: critical first, then warning, then info
    priority = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: priority.get(a["type"], 3))

    return {"notifications": alerts, "count": len(alerts)}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/analytics")
def get_analytics(mode: str = "paper"):
    """Deep analytics: PnL over time, per-strategy breakdown, win/loss, improvements."""
    is_paper = mode == "paper"

    # All trades for this mode
    all_trades = safe_query(
        lambda: db.table("trades").select("*")
        .order("created_at", desc=False).execute()
    )
    trades = [t for t in all_trades if bool(t.get("is_paper")) == is_paper]

    # ── PnL over time (daily buckets) ────────────────────────────────────────
    daily_pnl: dict = {}
    cumulative = 0.0
    for t in trades:
        date = (t.get("created_at") or "")[:10]
        if not date:
            continue
        pnl = t.get("size_usdc", 0) if t.get("outcome") == "won" else -t.get("size_usdc", 0)
        daily_pnl[date] = daily_pnl.get(date, 0) + pnl

    pnl_series = []
    cumulative = 0.0
    for date in sorted(daily_pnl):
        cumulative += daily_pnl[date]
        pnl_series.append({"date": date, "daily_pnl": round(daily_pnl[date], 2), "cumulative": round(cumulative, 2)})

    # ── Per-strategy breakdown ────────────────────────────────────────────────
    by_strategy: dict = {}
    for t in trades:
        sid = t.get("strategy_id", "unknown")
        if sid not in by_strategy:
            by_strategy[sid] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
        by_strategy[sid]["trades"] += 1
        if t.get("outcome") == "won":
            by_strategy[sid]["wins"] += 1
            by_strategy[sid]["pnl"] += t.get("size_usdc", 0)
        elif t.get("outcome") == "lost":
            by_strategy[sid]["losses"] += 1
            by_strategy[sid]["pnl"] -= t.get("size_usdc", 0)

    # Get display names
    plugins = safe_query(lambda: db.table("strategy_plugins").select("strategy_id,display_name,category").execute())
    plugin_map = {p["strategy_id"]: p for p in plugins}

    strategy_breakdown = []
    for sid, stats in by_strategy.items():
        total = stats["trades"]
        win_rate = round(stats["wins"] / total * 100, 1) if total else 0
        plugin = plugin_map.get(sid, {})
        strategy_breakdown.append({
            "strategy_id": sid,
            "display_name": plugin.get("display_name", sid),
            "category": plugin.get("category", ""),
            "trades": total,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": win_rate,
            "pnl": round(stats["pnl"], 2),
        })
    strategy_breakdown.sort(key=lambda x: x["pnl"], reverse=True)

    # ── Overall stats ─────────────────────────────────────────────────────────
    total_trades = len(trades)
    wins = [t for t in trades if t.get("outcome") == "won"]
    losses = [t for t in trades if t.get("outcome") == "lost"]
    total_pnl = sum(t.get("size_usdc", 0) for t in wins) - sum(t.get("size_usdc", 0) for t in losses)
    avg_win = sum(t.get("size_usdc", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("size_usdc", 0) for t in losses) / len(losses) if losses else 0
    profit_factor = (sum(t.get("size_usdc", 0) for t in wins) / sum(t.get("size_usdc", 0) for t in losses)) if losses else 0

    # ── Direction breakdown ───────────────────────────────────────────────────
    long_trades = [t for t in trades if t.get("direction") == "long"]
    short_trades = [t for t in trades if t.get("direction") == "short"]

    # ── Improvements (rule-based) ─────────────────────────────────────────────
    improvements = []
    win_rate_overall = round(len(wins) / total_trades * 100, 1) if total_trades else 0

    if win_rate_overall < 50 and total_trades > 5:
        improvements.append({
            "type": "warning",
            "title": "Win Rate Below 50%",
            "detail": f"Current win rate is {win_rate_overall}%. Review entry conditions — consider tightening signal thresholds.",
        })
    if avg_loss > avg_win * 1.5 and avg_win > 0:
        improvements.append({
            "type": "critical",
            "title": "Losses Larger Than Wins",
            "detail": f"Avg win ${avg_win:.2f} vs avg loss ${avg_loss:.2f}. Tighten stop-loss or reduce position sizing.",
        })
    if profit_factor > 0 and profit_factor < 1.2:
        improvements.append({
            "type": "warning",
            "title": "Low Profit Factor",
            "detail": f"Profit factor is {profit_factor:.2f}. Target >1.5. Reduce losing strategy allocation.",
        })
    worst = [s for s in strategy_breakdown if s["pnl"] < 0]
    for s in worst[:2]:
        improvements.append({
            "type": "warning",
            "title": f"Losing Strategy: {s['display_name']}",
            "detail": f"${abs(s['pnl']):.2f} total loss across {s['trades']} trades ({s['win_rate']}% win rate). Consider disabling or reconfiguring.",
        })
    if not improvements:
        improvements.append({
            "type": "info",
            "title": "Performance Looks Healthy",
            "detail": "No critical issues detected. Keep monitoring regime changes and drawdown levels.",
        })

    # ── Capital utilisation ───────────────────────────────────────────────────
    flags = safe_query(lambda: db.table("strategy_flags").select("strategy_id,max_capital,enabled").execute())
    total_allocated = sum(float(f.get("max_capital") or 0) for f in flags if is_paper)
    active_strategies = len([f for f in flags if f.get("enabled")])

    return {
        "mode": mode,
        "summary": {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate_overall,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "total_allocated": total_allocated,
            "active_strategies": active_strategies,
            "long_trades": len(long_trades),
            "short_trades": len(short_trades),
        },
        "pnl_series": pnl_series,
        "strategy_breakdown": strategy_breakdown,
        "improvements": improvements,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)

