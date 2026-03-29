"""
BaseStrategy — every strategy plugin MUST inherit this class.
Scanner calls on_market_signal(). Strategy does everything else.
Core code NEVER imports from strategies/. Strategies import from core, ingestion, latency.
"""
import asyncio
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime
from ingestion.market_normalizer import UnifiedMarket
from core.kill_switch_bus import KillSwitchBus
from database.supabase_client import SupabaseClient
from core.india_tax_engine import IndiaTaxEngine
import structlog

logger = structlog.get_logger()


class TradeDecision:
    """What a strategy returns when it decides to trade."""
    def __init__(
        self,
        symbol: str,
        exchange: str,
        direction: str,           # 'BUY' | 'SELL' | 'SHORT' | 'CLOSE'
        size_usdc: float,
        leverage: float = 1.0,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        ai_confidence: Optional[float] = None,
        reasoning: str = "",
        edge_detected: float = 0.0,
        version_tag: str = "v1",
        opportunity_id: str = "",  # For strategies using two-step execute_signal
    ):
        self.symbol = symbol
        self.exchange = exchange
        self.direction = direction
        self.size_usdc = size_usdc
        self.leverage = leverage
        self.stop_loss_price = stop_loss_price
        self.take_profit_price = take_profit_price
        self.ai_confidence = ai_confidence
        self.reasoning = reasoning
        self.edge_detected = edge_detected
        self.version_tag = version_tag
        self.opportunity_id = opportunity_id


class BaseStrategy(ABC):
    """
    Contract every strategy plugin implements.
    Scanner calls on_market_signal() with a scored UnifiedMarket.
    Strategy decides whether to trade and returns TradeDecision or None.
    """

    # REQUIRED class attributes (must set in every plugin)
    STRATEGY_ID: str = ""
    DISPLAY_NAME: str = ""
    CATEGORY: str = ""

    # 'A_math' | 'B_technical' | 'C_information' | 'D_timing'
    CATEGORY_LABEL: str = ""
    DESCRIPTION: str = ""
    NODE_ID: str = "singapore-01"
    VERSION: str = "v1"

    def __init__(
        self,
        kill_switch: KillSwitchBus,
        db: SupabaseClient,
        tax_engine: IndiaTaxEngine,
        allocated_usdc: float = 0.0,
    ):
        self._ks = kill_switch
        self._db = db
        self._tax = tax_engine
        self._allocated_usdc = allocated_usdc
        self._is_paper = True          # Always starts paper
        self._consecutive_losses = 0
        self._total_trades = 0
        self._wins = 0
        self.logger = structlog.get_logger().bind(strategy=self.STRATEGY_ID)

    # ── ABSTRACT METHODS (must implement) ─────────────────────────────────

    @abstractmethod
    async def on_market_signal(
        self,
        market: UnifiedMarket,
        allocated_usdc: float,
    ) -> Optional[TradeDecision]:
        """
        Called by scanner when this strategy should analyze a market.

        Args:
            market: Scored UnifiedMarket with all signals pre-computed
            allocated_usdc: How much USDC this strategy can use right now

        Returns:
            TradeDecision if trade recommended, None if no trade.

        RULES:
        1. ALWAYS check kill switch BEFORE any analysis.
        2. Log reasoning BEFORE returning (never after).
        3. Never raise exceptions — catch all, return None.
        4. Paper mode: strategy still analyzes but ExecutionEngine simulates.
        5. Stop loss REQUIRED for any leveraged position.
        """
        pass

    @abstractmethod
    async def get_health_status(self) -> Dict[str, Any]:
        """Called by dashboard every 30s to show strategy health."""
        pass

    # ── DEFAULT IMPLEMENTATIONS (can override) ─────────────────────────────

    async def on_regime_change(self, new_regime: str, paused: list) -> None:
        """Called when market regime changes. Override for custom logic."""
        if self.STRATEGY_ID in paused:
            self.logger.info("strategy_paused_by_regime", regime=new_regime)

    async def on_kill_switch(self, reason: str) -> None:
        """Called by KillSwitchBus. Clean up open positions if needed."""
        self.logger.warning("kill_switch_received", reason=reason)

    async def on_promote_to_live(self) -> None:
        """Called when strategy is promoted from paper to live."""
        self._is_paper = False
        self.logger.info("promoted_to_live")

    # ── HELPERS for subclasses ─────────────────────────────────────────────

    def check_kill_switch(self, size_usdc: float, leverage: float = 1.0) -> tuple[bool, str]:
        """Convenience wrapper around KillSwitchBus.pre_trade_check()."""
        return self._ks.pre_trade_check(self.STRATEGY_ID, size_usdc, leverage)

    def apply_kelly(self, raw_size: float) -> float:
        """Apply regime Kelly multiplier to position size."""
        return self._ks.apply_kelly_to_size(raw_size, self.STRATEGY_ID)

    async def log_trade_to_db(
        self,
        market: UnifiedMarket,
        decision: TradeDecision,
        regime: str,
        is_paper: bool,
    ) -> str:
        """Log trade decision to Supabase. Returns trade_id."""
        import uuid
        trade_id = str(uuid.uuid4())

        record = {
            "id": trade_id,
            "strategy_id": self.STRATEGY_ID,
            "version_tag": self.VERSION,
            "market_id": market.market_id,
            "symbol": decision.symbol,
            "exchange": decision.exchange,
            "node_id": self.NODE_ID,
            "pool_id": "crypto_sg",
            "direction": decision.direction,
            "entry_price": market.price,
            "size_usdc": decision.size_usdc,
            "kelly_fraction": decision.size_usdc / max(self._allocated_usdc, 1),
            "leverage": decision.leverage,
            "stop_loss_price": decision.stop_loss_price,
            "take_profit_price": decision.take_profit_price,
            "ai_confidence": decision.ai_confidence,
            "ai_reasoning": decision.reasoning,
            "opportunity_score": market.opportunity_score,
            "edge_detected": decision.edge_detected,
            "regime_at_trade": regime,
            "is_paper": is_paper,
            "slot": os.getenv("DEPLOY_SLOT", "green"),
            "created_at": datetime.utcnow().isoformat(),
            "outcome": "pending",
        }

        try:
            self._db.table("trades").insert(record).execute()
        except Exception as e:
            self.logger.error("trade_log_error", error=str(e))

        return trade_id


class StrategyRegistry:
    """
    Auto-discovers strategy plugins from strategies/ directory.
    Supports hot-reload: upload .py → reload → active without restart.
    """

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}
        self._instances: Dict[str, BaseStrategy] = {}

    def load_all(self, kill_switch, db, tax_engine, cache=None) -> None:
        """Load all strategy plugins found in strategies/ directory."""
        import importlib
        import pkgutil
        import strategies

        for _, name, _ in pkgutil.iter_modules(strategies.__path__):
            if name.startswith("_") or name == "base_strategy":
                continue
            try:
                module = importlib.import_module(f"strategies.{name}")
                if hasattr(module, "Strategy"):
                    cls = module.Strategy
                    if cls.STRATEGY_ID:
                        # Pass cache so strategies can init monitors/simulators
                        try:
                            instance = cls(kill_switch, db, tax_engine, cache=cache)
                        except TypeError:
                            # Fallback: plugin doesn't accept cache kwarg
                            instance = cls(kill_switch, db, tax_engine)
                        self._instances[cls.STRATEGY_ID] = instance
                        logger.info("strategy_loaded", strategy_id=cls.STRATEGY_ID)
            except Exception as e:
                logger.error("strategy_load_error", name=name, error=str(e))

    def hot_reload(self, strategy_id: str, kill_switch, db, tax_engine, cache=None) -> bool:
        """Hot-reload a single strategy. Zero downtime."""
        import importlib
        import pkgutil
        import strategies

        for _, name, _ in pkgutil.iter_modules(strategies.__path__):
            try:
                module = importlib.import_module(f"strategies.{name}")
                if (hasattr(module, "Strategy") and
                        getattr(module.Strategy, "STRATEGY_ID", "") == strategy_id):
                    importlib.reload(module)
                    cls = module.Strategy
                    try:
                        self._instances[strategy_id] = cls(kill_switch, db, tax_engine, cache=cache)
                    except TypeError:
                        self._instances[strategy_id] = cls(kill_switch, db, tax_engine)
                    logger.info("strategy_hot_reloaded", strategy_id=strategy_id)
                    return True
            except Exception as e:
                logger.error("hot_reload_error", strategy_id=strategy_id, error=str(e))
        return False

    def get(self, strategy_id: str) -> Optional[BaseStrategy]:
        return self._instances.get(strategy_id)

    def get_all(self) -> Dict[str, BaseStrategy]:
        return dict(self._instances)
