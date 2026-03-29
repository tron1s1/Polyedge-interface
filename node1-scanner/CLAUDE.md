# Node 1 Scanner — Singapore
## AlphaNode Trading System

### What this node is
Autonomous crypto CEX scanner for Singapore VPS (Hetzner CX22, $6/mo).
Proximity target: Binance (2–6ms), Bybit (3–8ms), OKX (4–10ms).
Scores ALL crypto markets. Routes to 15 strategy plugins.
Reports to shared Supabase DB. Never has its own dashboard.

### Node identity
NODE_ID=singapore-01
DEPLOY_SLOT=green (or blue for staging)
PRIMARY_EXCHANGE=binance

### Hard rules — NEVER violate
- Never hardcode API keys. Env vars only.
- All amounts in USDC floats. Never cents/integers.
- Every market update → event bus. No direct module-to-module calls.
- Log every routing decision BEFORE routing.
- Pre-trade risk check (cache lookup) before EVERY execution.
- Redis TTLs: prices=5s, market_meta=60s, news=300s, corr_map=3600s.
- Kill switch bus checked before every capital operation.
- Strategy plugins in strategies/. Core never imports from strategies/.
- DEPLOY_SLOT from ENV only. Never hardcode 'green'.
- Max leverage: 10x. Hardcoded. Not configurable.

### Performance targets
- Score 1,000+ markets in < 1 second
- WebSocket event → strategy route: < 50ms
- Redis read: < 1ms
- Pre-trade risk check: < 0.001ms (dict lookup only)
- Plugin hot-reload: < 2 seconds

### What this node is NOT doing
- No Django/Flask. FastAPI only for health endpoint.
- No ML model training. sklearn only for local triage.
- No strategy logic in core/. Pure infrastructure.
- No sync I/O in hot path.
- No fixed allocations. Dynamic regime-based only.
- No Polymarket. No prediction markets. Crypto CEX + DeFi only.

### Architecture decisions
- asyncio throughout. No threads.
- msgpack for all IPC.
- httpx.AsyncClient with HTTP/2 for REST.
- Redis L2 + in-process dict L1 for cache.
- Supabase pooler port 6543 always.
- Persistent WebSockets with auto-reconnect + exponential backoff.
- Event-driven: strategies subscribe to event bus.
