"""
Live execution subsystem for A_M1 triangular arbitrage.

Public surface:
  BinanceWSTrader          — persistent WS trade API client (IOC LIMIT + cancel)
  BoundedParallelExecutor  — 3-leg Approach D live executor
  HedgeEngine              — partial-fill market unwind
  LatencyCircuitBreaker    — global gate when wire latency degrades
  LiveTestState            — arm/disarm counter + master trading toggle

Execution modes (set on TradeResult.execution_mode):
  paper_instant          — legacy scanner-price fills (no longer used)
  paper_sim_latency      — paper with L1 re-read + synthetic slippage + book walk
  live_dry_run           — real mainnet orders, insufficient-balance rejects,
                           real wire latency captured, synthetic fill from L1
  live_test              — real $10 (configurable) orders, one-shot via arm()
  live                   — real capital-allocated orders, routed by promotion gates
"""
from execution.binance_ws_trader import BinanceWSTrader, OrderAck
from execution.latency_circuit_breaker import LatencyCircuitBreaker
from execution.live_test_state import LiveTestState
from execution.hedge_engine import HedgeEngine
from execution.live_executor import BoundedParallelExecutor

__all__ = [
    "BinanceWSTrader",
    "OrderAck",
    "LatencyCircuitBreaker",
    "LiveTestState",
    "HedgeEngine",
    "BoundedParallelExecutor",
]
