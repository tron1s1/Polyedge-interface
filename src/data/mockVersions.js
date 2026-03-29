import { VERSION_STATUS } from '../utils/constants'

const versionTemplates = {
  'latency-arb': [
    { name: 'v1_baseline', status: VERSION_STATUS.RETIRED, winRate: 89.2, avgPnl: 8.40, avgLatency: 312, trades: 200, sharpe: 1.4, changes: 'Initial configuration' },
    { name: 'v2_gap_20', status: VERSION_STATUS.RETIRED, winRate: 91.5, avgPnl: 11.20, avgLatency: 280, trades: 180, sharpe: 1.6, changes: 'Gap threshold: 15% → 20%' },
    { name: 'v3_presign', status: VERSION_STATUS.RETIRED, winRate: 93.1, avgPnl: 14.50, avgLatency: 195, trades: 156, sharpe: 1.8, changes: 'Enabled order pre-signing (T5)' },
    { name: 'v4_tokyo_vps', status: VERSION_STATUS.RETIRED, winRate: 94.8, avgPnl: 16.30, avgLatency: 148, trades: 132, sharpe: 2.0, changes: 'VPS: Pune → Tokyo, oracle direct (T6)' },
    { name: 'v5_gap_25_kelly', status: VERSION_STATUS.WINNER, winRate: 96.2, avgPnl: 19.80, avgLatency: 142, trades: 98, sharpe: 2.2, changes: 'Gap: 20% → 25%, Kelly: 0.25 → 0.30' },
    { name: 'v6_aggressive', status: VERSION_STATUS.TESTING, winRate: 95.4, avgPnl: 22.10, avgLatency: 138, trades: 34, sharpe: 2.1, changes: 'Kelly: 0.30 → 0.40, oracle guard: 90s → 60s' },
  ],
  'negrisk-arb': [
    { name: 'v1_base', status: VERSION_STATUS.RETIRED, winRate: 100, avgPnl: 4.20, avgLatency: 450, trades: 240, sharpe: 3.1, changes: 'Initial scanner' },
    { name: 'v2_batch_api', status: VERSION_STATUS.WINNER, winRate: 100, avgPnl: 5.80, avgLatency: 320, trades: 180, sharpe: 3.4, changes: 'Batch API (T10), min gap: 3% → 4%' },
    { name: 'v3_predictive', status: VERSION_STATUS.TESTING, winRate: 100, avgPnl: 6.10, avgLatency: 290, trades: 42, sharpe: 3.5, changes: 'Predictive pre-loading (T4)' },
  ],
  'ai-news': [
    { name: 'v1_basic', status: VERSION_STATUS.RETIRED, winRate: 68.0, avgPnl: 5.20, avgLatency: 8200, trades: 150, sharpe: 0.8, changes: 'Basic prompt, no feedback loop' },
    { name: 'v2_superforecaster', status: VERSION_STATUS.RETIRED, winRate: 74.5, avgPnl: 9.10, avgLatency: 4800, trades: 130, sharpe: 1.2, changes: 'Superforecaster prompt + base rates' },
    { name: 'v3_feedback', status: VERSION_STATUS.RETIRED, winRate: 78.2, avgPnl: 12.40, avgLatency: 3200, trades: 110, sharpe: 1.5, changes: 'Feedback loop + calibration injection' },
    { name: 'v4_streaming', status: VERSION_STATUS.WINNER, winRate: 81.4, avgPnl: 15.70, avgLatency: 1800, trades: 87, sharpe: 1.8, changes: 'Claude streaming (T2), haiku triage (T1)' },
    { name: 'v5_model_race', status: VERSION_STATUS.TESTING, winRate: 82.1, avgPnl: 16.20, avgLatency: 1400, trades: 28, sharpe: 1.9, changes: 'Parallel model race (T11)' },
  ],
  'market-making': [
    { name: 'v1_spread_capture', status: VERSION_STATUS.RETIRED, winRate: 82.0, avgPnl: 3.10, avgLatency: 520, trades: 300, sharpe: 1.3, changes: 'Basic spread capture' },
    { name: 'v2_both_sides', status: VERSION_STATUS.WINNER, winRate: 87.3, avgPnl: 4.80, avgLatency: 380, trades: 220, sharpe: 1.7, changes: 'Added both-sides arb, kill switch' },
    { name: 'v3_presign', status: VERSION_STATUS.TESTING, winRate: 88.1, avgPnl: 5.20, avgLatency: 290, trades: 45, sharpe: 1.8, changes: 'Order pre-signing (T5)' },
  ],
}

export function getVersions(strategyId) {
  const templates = versionTemplates[strategyId] || []
  const now = Date.now()
  return templates.map((v, i) => ({
    id: `${strategyId}-${v.name}`,
    ...v,
    score: parseFloat((v.winRate * 0.3 + Math.min(v.avgPnl, 25) * 1.0 + Math.max(0, 350 - v.avgLatency) * 0.05 + v.sharpe * 8).toFixed(1)),
    timestamp: new Date(now - (templates.length - i) * 7 * 86400000).toISOString(),
    tradeTarget: 50,
  }))
}

export function getActiveVersion(strategyId) {
  const versions = getVersions(strategyId)
  return versions.find(v => v.status === VERSION_STATUS.WINNER) || versions[versions.length - 1]
}
