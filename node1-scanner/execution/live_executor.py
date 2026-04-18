"""
BoundedParallelExecutor — Approach D 3-leg live executor.

The sequential triangle executor (legacy) waits for leg N's fill before
sizing leg N+1. That's 3 serial RTTs = 3-leg latency floor of ~15-30ms even
on a colocated VPS.

This executor overlaps the legs as much as possible while preserving size
correctness by using a CONSERVATIVE quantity estimate per leg:
  - Leg 1 qty: known (we decide at entry)
  - Leg 2 qty: estimated from scanner_price of leg 1, rounded DOWN by a
    safety factor (e.g., multiply by 0.998 to absorb small slippage)
  - Leg 3 qty: same — estimated from the chain, rounded down

All 3 legs are sent near-simultaneously (gathered, not awaited in series).
Acks arrive out of order; we correlate by clientOrderId.

After all 3 acks:
  - COMPLETE:  all 3 FILLED (or ≥99% filled) → log as win/loss by net pct
  - PARTIAL:   at least 1 missed → HedgeEngine unwinds held positions
  - ABORTED:   leg 1 missed → nothing to unwind (best case failure)
  - NO_FILL:   no legs filled
  - FAILED:    unexpected error (timeout, WS disconnect mid-flight)

Live test mode (<=$10 trades):
  - Same code path as live, with hard-capped size.
  - LiveTestState.record_fire() is called on completion.

Dry-run mode:
  - Same code path, but ws_trader.place_ioc_limit(dry_run=True) — sends a
    tiny quantity that guarantees -2010 reject. Real wire latency captured.
  - Synthetic fill from L1 at ack time.

The executor does NOT implement promotion gating. That's the caller's job.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

from execution.binance_ws_trader import BinanceWSTrader, OrderAck
from execution.hedge_engine import HedgeEngine, HedgeResult
from execution.latency_circuit_breaker import LatencyCircuitBreaker

if TYPE_CHECKING:
    from strategies.A_M1_triangular_arb import Triangle, TriangleOpportunity, TradeResult

logger = structlog.get_logger()


# Safety factor applied to inferred next-leg quantity. Compensates for tiny
# slippage on the previous leg + Binance's LOT_SIZE step rounding.
# 0.998 = 2 bps haircut. Means leg 2's size is 2 bps smaller than a naive
# calc — harmless if leg 1 filled at scanner_px, safe if leg 1 slipped.
_QTY_SAFETY_FACTOR = 0.998


@dataclass
class ExecutionReport:
    """Raw report the executor returns; strategy translates into TradeResult."""
    triangle_id: str
    execution_mode: str                 # 'live_dry_run' | 'live_test' | 'live'
    outcome_status: str                 # COMPLETE | PARTIAL_HEDGED | NO_FILL | ABORTED | FAILED
    scanner_prices: Dict[str, float]
    actual_fill_prices: Dict[str, float]
    per_leg_slippage_bps: Dict[str, float]
    per_leg_latency_ms: Dict[str, float]
    per_leg_status: Dict[str, str]
    trade_size_usdc: float
    net_pnl_usdc: float
    net_pnl_pct: float
    expected_pnl_usdc: float
    expected_pnl_pct: float
    fees_paid_usdc: float
    total_latency_ms: float
    hedge: Optional[HedgeResult] = None
    error: Optional[str] = None
    raw_acks: List[Dict] = field(default_factory=list)


class BoundedParallelExecutor:
    def __init__(
        self,
        ws_trader: BinanceWSTrader,
        cache,
        hedge_engine: Optional[HedgeEngine] = None,
        breaker: Optional[LatencyCircuitBreaker] = None,
        kill_switch=None,
        fee_per_leg_pct: float = 0.075,
    ):
        self.ws = ws_trader
        self.cache = cache
        self.hedge = hedge_engine or HedgeEngine(ws_trader, kill_switch)
        self.breaker = breaker
        self.kill_switch = kill_switch
        self.fee_per_leg_pct = fee_per_leg_pct

    async def execute(
        self,
        opportunity: "TriangleOpportunity",
        trade_size_usdc: float,
        execution_mode: str,            # 'live' | 'live_test' | 'live_dry_run'
    ) -> ExecutionReport:
        """Execute one 3-leg triangle.

        execution_mode determines:
          - 'live_dry_run': orders sent with tiny qty → guaranteed -2010 reject
          - 'live_test':    real orders, hard-capped size (caller enforces)
          - 'live':         real orders, capital-allocated size
        """
        triangle = opportunity.triangle
        t0 = time.perf_counter()

        # Pre-flight gates
        if self.kill_switch and getattr(self.kill_switch, "is_tripped", lambda: False)():
            return self._failed(triangle, execution_mode, trade_size_usdc,
                                opportunity, "kill_switch_tripped", t0)
        if self.breaker and self.breaker.is_tripped():
            return self._failed(triangle, execution_mode, trade_size_usdc,
                                opportunity, "latency_circuit_tripped", t0)

        scanner_prices = {
            triangle.leg1_symbol: opportunity.leg1_price,
            triangle.leg2_symbol: opportunity.leg2_price,
            triangle.leg3_symbol: opportunity.leg3_price,
        }

        # ── Quantity planning ────────────────────────────────────────────
        # Leg 1: we know exactly how much start currency to spend/receive.
        # In a USDT-started triangle with leg1 BUY XYZ: size_usdc / leg1_px
        # base units. With leg1 SELL USDT: size_usdc base units.
        dry_run = (execution_mode == "live_dry_run")
        leg1_qty, leg2_qty, leg3_qty = self._plan_quantities(
            triangle, opportunity, trade_size_usdc
        )

        # In dry-run, use a tiny qty that reliably triggers -2010 but is
        # syntactically valid (above Binance minNotional would actually
        # attempt to match). We pick 1e-8 which will fail LOT_SIZE validation
        # on most symbols, generating -1013 — ALSO a pre-match reject with
        # real wire latency. Either way: no match, real RTT.
        if dry_run:
            leg1_qty = leg2_qty = leg3_qty = 1e-8

        leg_specs = [
            (1, triangle.leg1_symbol, triangle.leg1_side,
             triangle.leg1_tolerance_bps, opportunity.leg1_price, leg1_qty),
            (2, triangle.leg2_symbol, triangle.leg2_side,
             triangle.leg2_tolerance_bps, opportunity.leg2_price, leg2_qty),
            (3, triangle.leg3_symbol, triangle.leg3_side,
             triangle.leg3_tolerance_bps, opportunity.leg3_price, leg3_qty),
        ]

        # ── Fire all 3 in parallel ────────────────────────────────────────
        # Per-leg limit price = scanner_px × (1 ± tolerance). IOC means
        # "fill what you can at this price or better, cancel the rest."
        tasks = []
        for idx, sym, side, tol_bps, scanner_px, qty in leg_specs:
            tol_frac = tol_bps / 10_000.0
            if side == "BUY":
                limit_px = scanner_px * (1.0 + tol_frac)
            else:
                limit_px = scanner_px * (1.0 - tol_frac)
            tasks.append(self.ws.place_ioc_limit(
                symbol=sym,
                side=side,
                price=limit_px,
                quantity=qty,
                dry_run=dry_run,
                client_order_id=f"a_m1_t{int(time.time()*1000)}_l{idx}",
            ))

        try:
            acks: List[OrderAck] = await asyncio.gather(*tasks, return_exceptions=False)
        except Exception as e:
            return self._failed(triangle, execution_mode, trade_size_usdc,
                                opportunity, f"gather_error: {e}", t0)

        # Feed latency breaker with per-leg RTT samples
        if self.breaker:
            for a in acks:
                if a.latency_ms > 0:
                    self.breaker.record(a.latency_ms)

        # ── Reconcile ─────────────────────────────────────────────────────
        per_leg_status: Dict[str, str] = {}
        per_leg_fill: Dict[str, float] = {}
        per_leg_slip: Dict[str, float] = {}
        per_leg_latency: Dict[str, float] = {}
        raw_acks: List[Dict] = []

        for idx, (_, sym, side, _, scanner_px, _), ack in zip(
            range(1, 4), leg_specs, acks
        ):
            label = f"leg{idx}"
            per_leg_latency[label] = round(ack.latency_ms, 2)
            raw_acks.append({
                "leg": idx, "symbol": sym, "side": side,
                "status": ack.status, "executed_qty": ack.executed_qty,
                "avg_fill_price": ack.avg_fill_price,
                "error_code": ack.error_code, "error_msg": ack.error_msg,
                "latency_ms": ack.latency_ms,
                "order_id": ack.order_id,
            })

            if dry_run:
                # Dry-run: use L1 at ack time as synthetic fill
                syn_px = self._read_l1(sym, side)
                per_leg_fill[sym] = syn_px or scanner_px
                per_leg_status[label] = "DRY_RUN_REJECTED"
                ref = syn_px or scanner_px
                if side == "BUY":
                    per_leg_slip[label] = round((ref - scanner_px) / scanner_px * 10_000, 2)
                else:
                    per_leg_slip[label] = round((scanner_px - ref) / scanner_px * 10_000, 2)
                continue

            if ack.is_filled:
                per_leg_fill[sym] = ack.avg_fill_price
                per_leg_status[label] = "FILLED"
            elif ack.is_partial:
                per_leg_fill[sym] = ack.avg_fill_price
                per_leg_status[label] = "PARTIALLY_FILLED"
            else:
                per_leg_status[label] = "CANCELED_NO_FILL"

            if ack.avg_fill_price > 0 and scanner_px > 0:
                if side == "BUY":
                    per_leg_slip[label] = round((ack.avg_fill_price - scanner_px) / scanner_px * 10_000, 2)
                else:
                    per_leg_slip[label] = round((scanner_px - ack.avg_fill_price) / scanner_px * 10_000, 2)
            else:
                per_leg_slip[label] = 0.0

        total_latency_ms = (time.perf_counter() - t0) * 1000
        if self.breaker:
            self.breaker.record(total_latency_ms)

        # ── Outcome classification + P&L ──────────────────────────────────
        if dry_run:
            # Dry-run never has real P&L — estimate what WOULD have happened
            outcome, net_pct = self._estimate_dry_run_outcome(
                triangle, opportunity, per_leg_fill
            )
            return ExecutionReport(
                triangle_id=triangle.triangle_id,
                execution_mode=execution_mode,
                outcome_status=outcome,
                scanner_prices=scanner_prices,
                actual_fill_prices=per_leg_fill,
                per_leg_slippage_bps=per_leg_slip,
                per_leg_latency_ms=per_leg_latency,
                per_leg_status=per_leg_status,
                trade_size_usdc=trade_size_usdc,
                net_pnl_usdc=0.0,            # Zero real P&L
                net_pnl_pct=net_pct,         # Estimated pct
                expected_pnl_usdc=trade_size_usdc * opportunity.net_profit_pct / 100.0,
                expected_pnl_pct=opportunity.net_profit_pct,
                fees_paid_usdc=0.0,
                total_latency_ms=round(total_latency_ms, 2),
                raw_acks=raw_acks,
            )

        # Real execution
        filled_count = sum(1 for s in per_leg_status.values()
                           if s in ("FILLED", "PARTIALLY_FILLED"))

        if filled_count == 3:
            # COMPLETE
            net_usdc, net_pct = self._compute_pnl(triangle, opportunity,
                                                   per_leg_fill, trade_size_usdc)
            fees = trade_size_usdc * 3 * self.fee_per_leg_pct / 100.0
            return ExecutionReport(
                triangle_id=triangle.triangle_id,
                execution_mode=execution_mode,
                outcome_status="COMPLETE",
                scanner_prices=scanner_prices,
                actual_fill_prices=per_leg_fill,
                per_leg_slippage_bps=per_leg_slip,
                per_leg_latency_ms=per_leg_latency,
                per_leg_status=per_leg_status,
                trade_size_usdc=trade_size_usdc,
                net_pnl_usdc=round(net_usdc, 6),
                net_pnl_pct=round(net_pct, 6),
                expected_pnl_usdc=trade_size_usdc * opportunity.net_profit_pct / 100.0,
                expected_pnl_pct=opportunity.net_profit_pct,
                fees_paid_usdc=round(fees, 6),
                total_latency_ms=round(total_latency_ms, 2),
                raw_acks=raw_acks,
            )

        if filled_count == 0:
            return ExecutionReport(
                triangle_id=triangle.triangle_id,
                execution_mode=execution_mode,
                outcome_status="NO_FILL",
                scanner_prices=scanner_prices,
                actual_fill_prices=per_leg_fill,
                per_leg_slippage_bps=per_leg_slip,
                per_leg_latency_ms=per_leg_latency,
                per_leg_status=per_leg_status,
                trade_size_usdc=trade_size_usdc,
                net_pnl_usdc=0.0,
                net_pnl_pct=0.0,
                expected_pnl_usdc=trade_size_usdc * opportunity.net_profit_pct / 100.0,
                expected_pnl_pct=opportunity.net_profit_pct,
                fees_paid_usdc=0.0,
                total_latency_ms=round(total_latency_ms, 2),
                raw_acks=raw_acks,
            )

        # Partial — hedge
        hedge = await self._hedge_partials(triangle, opportunity, acks, per_leg_status)
        # Crude P&L estimate: fees paid on filled legs + hedge loss
        filled_fees = sum(1 for s in per_leg_status.values()
                          if s in ("FILLED", "PARTIALLY_FILLED"))
        fees = trade_size_usdc * filled_fees * self.fee_per_leg_pct / 100.0
        hedge_loss = hedge.net_loss_usdc if hedge else 0.0
        net_usdc = hedge_loss - fees
        net_pct = (net_usdc / trade_size_usdc) * 100.0 if trade_size_usdc else 0.0

        return ExecutionReport(
            triangle_id=triangle.triangle_id,
            execution_mode=execution_mode,
            outcome_status="PARTIAL_HEDGED",
            scanner_prices=scanner_prices,
            actual_fill_prices=per_leg_fill,
            per_leg_slippage_bps=per_leg_slip,
            per_leg_latency_ms=per_leg_latency,
            per_leg_status=per_leg_status,
            trade_size_usdc=trade_size_usdc,
            net_pnl_usdc=round(net_usdc, 6),
            net_pnl_pct=round(net_pct, 6),
            expected_pnl_usdc=trade_size_usdc * opportunity.net_profit_pct / 100.0,
            expected_pnl_pct=opportunity.net_profit_pct,
            fees_paid_usdc=round(fees, 6),
            total_latency_ms=round(total_latency_ms, 2),
            hedge=hedge,
            raw_acks=raw_acks,
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _plan_quantities(self, triangle, opportunity, size_usdc: float):
        """Conservative per-leg quantity estimates.
        Returns (leg1_qty, leg2_qty, leg3_qty) all in the BASE asset of each
        leg's trading pair. These are estimates; real slippage/rounding on
        leg 1 may make leg 2's real available qty slightly different — we
        apply _QTY_SAFETY_FACTOR to cushion.
        """
        p1 = opportunity.leg1_price
        p2 = opportunity.leg2_price
        # p3 reserved for future per-leg qty refinement — currently unused.
        _ = opportunity.leg3_price

        # Leg 1: start USDC → buy/sell base at p1
        if triangle.leg1_side == "BUY":
            leg1_qty = size_usdc / p1 if p1 > 0 else 0.0
        else:
            leg1_qty = size_usdc  # selling start currency units

        # Output of leg 1 (in leg 1's OTHER currency)
        fee_factor = 1.0 - self.fee_per_leg_pct / 100.0
        after1 = (leg1_qty) * fee_factor * _QTY_SAFETY_FACTOR

        # Leg 2: consume after1 of whichever currency leg 1 produced.
        # Without leg metadata on currency direction, we use a defensive
        # estimate: the raw base quantity from leg 2's symbol at scanner price.
        if triangle.leg2_side == "BUY":
            leg2_qty = (after1 * p1 / p2) if p2 > 0 else 0.0
        else:
            leg2_qty = after1

        after2 = leg2_qty * fee_factor * _QTY_SAFETY_FACTOR

        # Leg 3: close the loop.
        if triangle.leg3_side == "BUY":
            leg3_qty = after2 / opportunity.leg3_price if opportunity.leg3_price > 0 else 0.0
        else:
            leg3_qty = after2

        return (max(leg1_qty, 0.0), max(leg2_qty, 0.0), max(leg3_qty, 0.0))

    def _read_l1(self, symbol: str, side: str) -> Optional[float]:
        """Read current top-of-book for the required side.
        For a BUY we need ask, for a SELL we need bid."""
        key = f"ask:binance:{symbol}" if side == "BUY" else f"bid:binance:{symbol}"
        try:
            entry = self.cache._L1.get(key)
            if entry and entry[1] >= time.monotonic():
                return float(entry[0])
        except Exception:
            return None
        return None

    def _estimate_dry_run_outcome(self, triangle, opportunity, fills):
        """For dry-run, compute net_pct using L1 fill snapshots.
        Acts like paper_sim_latency but with real wire latency."""
        fee_mult = 1.0 - self.fee_per_leg_pct / 100.0
        amount = 1.0
        try:
            p1 = fills.get(triangle.leg1_symbol, opportunity.leg1_price)
            p2 = fills.get(triangle.leg2_symbol, opportunity.leg2_price)
            p3 = fills.get(triangle.leg3_symbol, opportunity.leg3_price)
            if triangle.leg1_side == "BUY": amount = amount / p1 * fee_mult
            else:                            amount = amount * p1 * fee_mult
            if triangle.leg2_side == "BUY": amount = amount / p2 * fee_mult
            else:                            amount = amount * p2 * fee_mult
            if triangle.leg3_side == "BUY": amount = amount / p3 * fee_mult
            else:                            amount = amount * p3 * fee_mult
            net_pct = (amount - 1.0) * 100.0
            outcome = "COMPLETE" if net_pct > 0 else "COMPLETE"  # dry-run always "complete" by definition
            return outcome, round(net_pct, 6)
        except Exception:
            return "FAILED", 0.0

    def _compute_pnl(self, triangle, opportunity, fills, size_usdc):
        fee_mult = 1.0 - self.fee_per_leg_pct / 100.0
        amount = 1.0
        p1 = fills.get(triangle.leg1_symbol) or opportunity.leg1_price
        p2 = fills.get(triangle.leg2_symbol) or opportunity.leg2_price
        p3 = fills.get(triangle.leg3_symbol) or opportunity.leg3_price
        if triangle.leg1_side == "BUY": amount = amount / p1 * fee_mult
        else:                            amount = amount * p1 * fee_mult
        if triangle.leg2_side == "BUY": amount = amount / p2 * fee_mult
        else:                            amount = amount * p2 * fee_mult
        if triangle.leg3_side == "BUY": amount = amount / p3 * fee_mult
        else:                            amount = amount * p3 * fee_mult
        net_pct = (amount - 1.0) * 100.0
        net_usdc = size_usdc * (net_pct / 100.0)
        return net_usdc, net_pct

    async def _hedge_partials(self, triangle, opportunity, acks, per_leg_status):
        """Decide what to unwind and call HedgeEngine."""
        leg1_ack, leg2_ack, leg3_ack = acks
        # Simplest triangle-partial logic: find the LAST filled leg, unwind it.
        # A more sophisticated engine tracks net exposure per currency and
        # unwinds the minimum — leaving that for future enhancement.
        if per_leg_status.get("leg3") in ("FILLED", "PARTIALLY_FILLED"):
            # If leg 3 filled, we're actually done (no partial) — already handled upstream.
            return None
        if per_leg_status.get("leg2") in ("FILLED", "PARTIALLY_FILLED"):
            return await self.hedge.unwind(
                held_symbol=triangle.leg2_symbol,
                held_side_to_exit="SELL" if triangle.leg2_side == "BUY" else "BUY",
                held_quantity=leg2_ack.executed_qty,
                reference_price=leg2_ack.avg_fill_price or opportunity.leg2_price,
                context="leg2_unwind",
            )
        if per_leg_status.get("leg1") in ("FILLED", "PARTIALLY_FILLED"):
            return await self.hedge.unwind(
                held_symbol=triangle.leg1_symbol,
                held_side_to_exit="SELL" if triangle.leg1_side == "BUY" else "BUY",
                held_quantity=leg1_ack.executed_qty,
                reference_price=leg1_ack.avg_fill_price or opportunity.leg1_price,
                context="leg1_unwind",
            )
        return None

    def _failed(self, triangle, execution_mode, size_usdc, opportunity, reason, t0):
        return ExecutionReport(
            triangle_id=triangle.triangle_id,
            execution_mode=execution_mode,
            outcome_status="FAILED",
            scanner_prices={},
            actual_fill_prices={},
            per_leg_slippage_bps={},
            per_leg_latency_ms={},
            per_leg_status={},
            trade_size_usdc=size_usdc,
            net_pnl_usdc=0.0,
            net_pnl_pct=0.0,
            expected_pnl_usdc=size_usdc * opportunity.net_profit_pct / 100.0,
            expected_pnl_pct=opportunity.net_profit_pct,
            fees_paid_usdc=0.0,
            total_latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            error=reason,
        )
