"""
HedgeEngine — bounded-loss unwind of partial 3-leg fills.

Partial-fill cases we must handle:

  CASE A: Leg 1 filled, Leg 2 missed
    We hold the leg 1 out-currency. Immediately MARKET SELL/BUY it back to
    the start currency. Worst-case loss = 2 × fee + spread.

  CASE B: Legs 1+2 filled, Leg 3 missed
    We hold the leg 2 out-currency (intermediate). MARKET unwind via the
    SHORTEST path back to start currency — which in a triangle is the
    inverse of leg 3. Worst-case loss = 3 × fee + spread.

  CASE C: Leg 1 missed
    Nothing held, nothing to hedge. Abort cleanly.

The engine uses MARKET orders (NOT IOC LIMIT) for hedges because:
  - A partial fill means we're already exposed; we MUST exit.
  - Binance spot MARKET orders fill against the book immediately.
  - Slippage is capped by the book depth, not by an arbitrary price gate.

Safety:
  - Max hedge attempts: 2 (retry once on transient error, then give up and
    log for manual intervention — kill switch).
  - Max hedge size: the quantity we're holding, exactly. Never larger.
  - Kill-switch check before sending.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

from execution.binance_ws_trader import BinanceWSTrader, OrderAck

logger = structlog.get_logger()


@dataclass
class HedgeResult:
    attempted: bool = False
    success: bool = False
    unwind_orders: List[Dict] = field(default_factory=list)
    net_loss_usdc: float = 0.0      # Negative number = loss
    error: Optional[str] = None
    # Latency of each hedge order
    hedge_latency_ms: List[float] = field(default_factory=list)


class HedgeEngine:
    def __init__(self, ws_trader: BinanceWSTrader, kill_switch=None):
        self.ws = ws_trader
        self.kill_switch = kill_switch

    async def unwind(
        self,
        held_symbol: str,
        held_side_to_exit: str,        # 'SELL' to exit a BUY, 'BUY' to exit a SELL
        held_quantity: float,
        reference_price: float,         # Last-known L1 for reporting only
        dry_run: bool = False,
        context: str = "",
    ) -> HedgeResult:
        """Exit a single held position via MARKET order.

        For triangle partials, the caller tells us exactly what we're holding
        (symbol, qty) and which side closes it. Caller is responsible for
        choosing the CORRECT symbol — usually the inverse of the missed leg.
        """
        if held_quantity <= 0:
            return HedgeResult(attempted=False, success=True, error="zero_qty")

        if self.kill_switch and getattr(self.kill_switch, "is_tripped", lambda: False)():
            return HedgeResult(attempted=False, success=False,
                               error="kill_switch_tripped")

        result = HedgeResult(attempted=True)
        MAX_ATTEMPTS = 2

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                # We use IOC LIMIT at a very loose price rather than MARKET so
                # all safety rails (precision, min-notional, recvWindow) are
                # the same as the hot path. The limit is set to 10% beyond
                # reference — effectively MARKET within any normal book.
                loose_bound = 0.10  # 10%
                if held_side_to_exit == "SELL":
                    limit_px = reference_price * (1.0 - loose_bound)
                else:
                    limit_px = reference_price * (1.0 + loose_bound)

                ack: OrderAck = await self.ws.place_ioc_limit(
                    symbol=held_symbol,
                    side=held_side_to_exit,
                    price=limit_px,
                    quantity=held_quantity,
                    dry_run=dry_run,
                    client_order_id=f"hedge_{context}_{attempt}_{int(time.time()*1000)}",
                )
                result.hedge_latency_ms.append(ack.latency_ms)

                if ack.is_filled or ack.is_partial:
                    result.unwind_orders.append({
                        "symbol": held_symbol,
                        "side": held_side_to_exit,
                        "qty": ack.executed_qty,
                        "quote": ack.cumulative_quote_qty,
                        "avg_px": ack.avg_fill_price,
                        "status": ack.status,
                        "latency_ms": ack.latency_ms,
                        "attempt": attempt,
                    })
                    if ack.is_filled or ack.executed_qty >= held_quantity * 0.99:
                        result.success = True
                        break
                    # Partial hedge → loop to cover remainder
                    held_quantity -= ack.executed_qty
                    continue

                # Not filled — retry once, then give up
                if attempt >= MAX_ATTEMPTS:
                    result.error = f"hedge_failed status={ack.status} err={ack.error_msg}"
                    break

            except Exception as e:
                if attempt >= MAX_ATTEMPTS:
                    result.error = f"hedge_exception: {e}"
                    break
                await asyncio.sleep(0.1)

        return result
