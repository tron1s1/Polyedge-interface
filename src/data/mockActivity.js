import { createRng, randPick, randRange } from '../utils/seedRandom'

const templates = {
  'latency-arb': [
    (rng) => ({ text: `Latency Arb fired: BTC >${Math.round(randRange(rng, 60, 80))}k YES @ $${randRange(rng, 0.40, 0.65).toFixed(2)}, gap ${Math.round(randRange(rng, 18, 42))}%`, pnl: randRange(rng, 40, 280) }),
    (rng) => ({ text: `Latency Arb: ETH gap detected ${Math.round(randRange(rng, 15, 35))}%, oracle age ${Math.round(randRange(rng, 90, 240))}s`, pnl: randRange(rng, 20, 150) }),
    (rng) => ({ text: `Latency Arb: SOL market, gap ${Math.round(randRange(rng, 20, 38))}% — executed in ${Math.round(randRange(rng, 95, 180))}ms`, pnl: randRange(rng, 30, 200) }),
  ],
  'negrisk-arb': [
    (rng) => ({ text: `NegRisk scan: Senate race sum = $${randRange(rng, 0.72, 0.93).toFixed(2)}, buying all sides`, pnl: randRange(rng, 15, 90) }),
    (rng) => ({ text: `NegRisk: Election market gap ${Math.round(randRange(rng, 4, 18))}% — $${Math.round(randRange(rng, 100, 500))} deployed`, pnl: randRange(rng, 10, 60) }),
  ],
  'ai-news': [
    (rng) => ({ text: `AI News: Fed decision, Claude conf ${randRange(rng, 0.68, 0.92).toFixed(2)}, edge ${Math.round(randRange(rng, 14, 32))}%`, pnl: randRange(rng, -40, 180) }),
    (rng) => ({ text: `AI News: Breaking — tariff update, analyzing in ${Math.round(randRange(rng, 1.2, 2.8) * 1000)}ms`, pnl: randRange(rng, -20, 120) }),
  ],
  'market-making': [
    (rng) => ({ text: `Market Maker: Spread captured on ${randPick(rng, ['ETH', 'BTC', 'Tesla', 'Gold'])} market`, pnl: randRange(rng, 2, 15) }),
    (rng) => ({ text: `Market Maker: Both-sides arb — YES+NO = $${randRange(rng, 0.88, 0.96).toFixed(2)}`, pnl: randRange(rng, 5, 40) }),
  ],
}

export function generateActivityFeed(mode, count = 50) {
  const rng = createRng(mode === 'paper' ? 777 : 888)
  const now = Date.now()
  const entries = []

  for (let i = 0; i < count; i++) {
    const stratId = randPick(rng, ['latency-arb', 'negrisk-arb', 'ai-news', 'market-making'])
    const templateFn = randPick(rng, templates[stratId])
    const { text, pnl } = templateFn(rng)
    entries.push({
      id: `feed-${mode}-${i}`,
      strategyId: stratId,
      text,
      pnl: parseFloat(pnl.toFixed(2)),
      timestamp: new Date(now - i * randRange(rng, 60000, 300000)),
    })
  }
  return entries
}

export function generateAlerts(mode) {
  const base = [
    { id: 'a1', severity: 'warning', message: 'Latency Arb: 2 consecutive losses. 1 more triggers 30-min pause.', timestamp: new Date(Date.now() - 3600000) },
    { id: 'a2', severity: 'info', message: 'NegRisk scanner found 3 new opportunities. Total gap: $142.', timestamp: new Date(Date.now() - 1800000) },
    { id: 'a3', severity: 'success', message: 'AI News version v4_streaming promoted to winner. Win rate: 81.4%', timestamp: new Date(Date.now() - 7200000) },
  ]
  if (mode === 'live') {
    base.unshift(
      { id: 'a0', severity: 'error', message: 'Daily loss cap reached for Market Making. Strategy paused until tomorrow.', timestamp: new Date(Date.now() - 900000) }
    )
  }
  return base
}
