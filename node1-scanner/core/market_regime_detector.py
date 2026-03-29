"""
MarketRegimeDetector — classifies market state every 30 seconds.
7 regimes: BULL_TRENDING, BULL_RANGING, VOLATILE_UP, CRASH_MINOR,
           CRASH_MAJOR, RECOVERY, BLACK_SWAN
Regime determines: kelly_multiplier, which strategies activate, bear engine.
"""
import asyncio
import os
from datetime import datetime
from typing import Optional, Dict, List
from latency.base_methods import TieredCache, AsyncEventBus, ConnectionPool
from database.supabase_client import SupabaseClient
import structlog

logger = structlog.get_logger()

# Regime thresholds
REGIME_THRESHOLDS = {
    "bull_trending_min_fg":       55,    # Fear/Greed above = greed
    "bull_trending_min_1h":       0.5,   # BTC 1h > 0.5%
    "ranging_max_24h":            2.5,   # BTC 24h abs < 2.5%
    "volatile_up_min_4h":         3.0,   # BTC 4h > 3%
    "crash_minor_drop_1h":        -3.0,  # BTC 1h < -3%
    "crash_major_drop_4h":        -10.0, # BTC 4h < -10%
    "crash_major_fg":             20,    # Fear/Greed below
    "black_swan_drop_1h":         -20.0, # BTC drops 20%+ in 1h
}

# Regime → kelly multiplier
REGIME_KELLY = {
    "BULL_TRENDING":  1.00,
    "BULL_RANGING":   0.75,
    "VOLATILE_UP":    0.60,
    "CRASH_MINOR":    0.40,
    "CRASH_MAJOR":    0.20,
    "RECOVERY":       0.50,
    "BLACK_SWAN":     0.00,  # Only math strategies allowed
}

# Regime → which strategies to PAUSE (rest continue)
REGIME_PAUSED = {
    "BULL_TRENDING":  [],
    "BULL_RANGING":   ["D_LEV_event_futures"],
    "VOLATILE_UP":    ["D_PAIR_long_short"],
    "CRASH_MINOR":    ["D_LEV_event_futures", "B_SNIPE_token"],
    "CRASH_MAJOR":    ["D_LEV_event_futures", "B_SNIPE_token",
                       "C_AI_crypto_news"],
    "RECOVERY":       ["D_LEV_event_futures"],
    "BLACK_SWAN":     ["D_SHORT_systematic", "D_LEV_event_futures",
                       "B_SNIPE_token", "D_GRID_trading",
                       "C_AI_crypto_news", "D_PAIR_long_short"],
    # Math strategies NEVER paused: A_M1, A_M2, A_CEX, A_STAB, A_FL
}

# Regime → which bear strategies to ACTIVATE
REGIME_BEAR_ACTIVATE = {
    "CRASH_MINOR":   ["D_SHORT_systematic"],
    "CRASH_MAJOR":   ["D_SHORT_systematic", "C_FEAR_greed"],
    "BLACK_SWAN":    [],  # Nothing directional
}


class MarketRegimeDetector:
    """
    Classifies current market state.
    Called every 30 seconds by scanner.
    Writes regime to Supabase + cache.
    Publishes REGIME_CHANGE event when regime changes.
    """

    def __init__(self, cache: TieredCache, event_bus: AsyncEventBus, db: SupabaseClient):
        self._cache = cache
        self._bus = event_bus
        self._db = db
        self._current_regime = "BULL_RANGING"  # Default until first detection

    async def detect_regime(self) -> str:
        """
        Detect current market regime from cached signals.
        All reads from L1 cache — total time < 1ms.
        Returns regime string.
        """
        # Read signals from cache (all < 0.1ms each)
        btc_1h = await self._cache.get("price_change:binance:BTCUSDT:1h") or 0
        btc_4h = await self._cache.get("price_change:binance:BTCUSDT:4h") or 0
        btc_24h = await self._cache.get("price_change:binance:BTCUSDT:24h") or 0
        fg_data = await self._cache.get("fear_greed:current") or {"value": 50}
        fg = fg_data.get("value", 50)
        funding = await self._cache.get("funding:bybit:BTCUSDT") or {"rate": 0}
        funding_rate = funding.get("rate", 0)

        # ── Regime classification (ordered by severity, highest first) ────

        if btc_1h < REGIME_THRESHOLDS["black_swan_drop_1h"]:
            regime = "BLACK_SWAN"

        elif btc_4h < REGIME_THRESHOLDS["crash_major_drop_4h"] or fg < REGIME_THRESHOLDS["crash_major_fg"]:
            regime = "CRASH_MAJOR"

        elif btc_1h < REGIME_THRESHOLDS["crash_minor_drop_1h"]:
            regime = "CRASH_MINOR"

        elif btc_4h > REGIME_THRESHOLDS["volatile_up_min_4h"]:
            regime = "VOLATILE_UP"

        elif (abs(btc_24h) < REGIME_THRESHOLDS["ranging_max_24h"]
              and abs(btc_1h) < 1.0):
            regime = "BULL_RANGING"

        elif (btc_1h > REGIME_THRESHOLDS["bull_trending_min_1h"]
              and fg > REGIME_THRESHOLDS["bull_trending_min_fg"]
              and funding_rate > 0):
            regime = "BULL_TRENDING"

        elif (self._current_regime in ["CRASH_MINOR", "CRASH_MAJOR"]
              and btc_4h > 3.0):
            regime = "RECOVERY"

        else:
            regime = "BULL_RANGING"  # Default

        # ── Publish event if regime changed ──────────────────────────────
        if regime != self._current_regime:
            prev_regime = self._current_regime
            self._current_regime = regime

            logger.info("regime_changed",
                        from_regime=prev_regime,
                        to_regime=regime,
                        btc_1h=btc_1h,
                        btc_4h=btc_4h,
                        fear_greed=fg)

            await self._bus.publish("REGIME_CHANGE", {
                "regime": regime,
                "prev_regime": prev_regime,
                "kelly_multiplier": REGIME_KELLY[regime],
                "paused_strategies": REGIME_PAUSED.get(regime, []),
                "bear_activate": REGIME_BEAR_ACTIVATE.get(regime, []),
                "btc_1h": btc_1h,
                "btc_4h": btc_4h,
                "fear_greed": fg,
            })

            # Update Supabase
            self._db.table("deployment_config").update({
                "value": regime,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("key", "global_regime").execute()

            self._db.table("market_regime").insert({
                "regime": regime,
                "btc_change_1h": btc_1h,
                "btc_change_4h": btc_4h,
                "btc_change_24h": btc_24h,
                "fear_greed_index": fg,
                "funding_rate": funding_rate,
                "kelly_multiplier": REGIME_KELLY[regime],
                "paused_strategies": REGIME_PAUSED.get(regime, []),
            }).execute()

            # Update Telegram alert
            if regime in ["BLACK_SWAN", "CRASH_MAJOR"]:
                await self._send_telegram_alert(
                    f"⚠️ REGIME CHANGE: {prev_regime} → {regime}\n"
                    f"BTC 1h: {btc_1h:.1f}% | 4h: {btc_4h:.1f}% | F&G: {fg}"
                )

        # Update cache with current regime (fast flag for pre-trade checks)
        await self._cache.set("regime:current", {
            "regime": regime,
            "kelly_multiplier": REGIME_KELLY[regime],
            "paused_strategies": REGIME_PAUSED.get(regime, []),
        })

        return regime

    async def _send_telegram_alert(self, message: str) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            session = await ConnectionPool.get()
            await session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message}
            )
        except Exception as e:
            logger.warning("telegram_error", error=str(e))

    @property
    def current_regime(self) -> str:
        return self._current_regime

    def get_kelly_multiplier(self) -> float:
        return REGIME_KELLY.get(self._current_regime, 0.50)

    def is_strategy_paused(self, strategy_id: str) -> bool:
        return strategy_id in REGIME_PAUSED.get(self._current_regime, [])
