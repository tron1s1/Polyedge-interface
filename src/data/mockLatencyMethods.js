import { createRng, randRange } from '../utils/seedRandom'

// Top layer methods definition with strategy applicability
export const TOP_METHODS = [
  {
    id: 'T1', name: 'Haiku Triage Gate', description: '200ms filter before Sonnet call — skip low-value markets',
    strategies: ['ai-news'],
    configurable: true,
    params: [
      { key: 'confidenceThreshold', label: 'Haiku Confidence Threshold', min: 0.5, max: 0.95, step: 0.05, unit: '', default: 0.85 },
      { key: 'fallbackToSonnet', label: 'Fallback to Sonnet', type: 'toggle', default: true },
    ],
  },
  {
    id: 'T2', name: 'Claude Streaming', description: 'Act on first tokens instead of waiting for full response',
    strategies: ['ai-news'],
    configurable: true,
    params: [
      { key: 'earlyCancelThreshold', label: 'Early Cancel Probability', min: 0.3, max: 0.7, step: 0.05, unit: '', default: 0.55 },
    ],
  },
  {
    id: 'T3', name: 'Prompt Pre-building', description: 'Pre-build prompts N min before needed — test staleness tolerance',
    strategies: ['ai-news', 'negrisk-arb'],
    configurable: true,
    params: [
      { key: 'ttlMinutes', label: 'Prompt TTL', min: 1, max: 15, step: 1, unit: 'min', default: 5 },
    ],
  },
  {
    id: 'T4', name: 'Predictive Pre-loading', description: 'Pre-analyze markets predicted to spike next',
    strategies: ['ai-news', 'negrisk-arb'],
    configurable: true,
    params: [
      { key: 'spikeScoreThreshold', label: 'Spike Score Threshold', min: 20, max: 80, step: 5, unit: '', default: 50 },
      { key: 'preloadCount', label: 'Markets to Pre-load', min: 3, max: 20, step: 1, unit: '', default: 10 },
    ],
  },
  {
    id: 'T5', name: 'Order Pre-signing', description: 'Wallet signature computed before trade decision',
    strategies: ['latency-arb', 'market-making'],
    configurable: true,
    params: [
      { key: 'preSizes', label: 'Pre-sign Sizes', type: 'text', default: '100, 250, 500, 1000, 2500' },
    ],
  },
  {
    id: 'T6', name: 'Oracle Direct Subscription', description: 'Chainlink events via on-chain listener, not REST',
    strategies: ['latency-arb'],
    configurable: false,
  },
  {
    id: 'T7', name: 'Co-location VPS', description: 'Server physically near exchange nodes',
    strategies: ['latency-arb', 'market-making'],
    configurable: true,
    params: [
      { key: 'region', label: 'VPS Region', type: 'select', options: ['Tokyo', 'Singapore', 'Frankfurt', 'US East'], default: 'Tokyo' },
    ],
  },
  {
    id: 'T8', name: 'News Webhook Push', description: 'Push alerts instead of polling APIs',
    strategies: ['ai-news'],
    configurable: true,
    params: [
      { key: 'pollingFallback', label: 'Polling Fallback Interval', min: 10, max: 120, step: 5, unit: 's', default: 30 },
    ],
  },
  {
    id: 'T9', name: 'Supabase Edge Functions', description: 'DB logic at edge — 2-5ms vs 50ms round-trip',
    strategies: ['ai-news', 'negrisk-arb'],
    configurable: false,
  },
  {
    id: 'T10', name: 'Batch API Calls', description: 'One request for 50 markets instead of 50 requests',
    strategies: ['negrisk-arb', 'market-making'],
    configurable: true,
    params: [
      { key: 'batchSize', label: 'Batch Size', min: 10, max: 100, step: 5, unit: '', default: 50 },
    ],
  },
  {
    id: 'T11', name: 'Parallel Model Race', description: 'Haiku + Sonnet race simultaneously, use winner',
    strategies: ['ai-news'],
    configurable: true,
    params: [
      { key: 'raceConfidence', label: 'Fast-accept Confidence', min: 0.7, max: 0.95, step: 0.05, unit: '', default: 0.85 },
    ],
  },
  {
    id: 'T12', name: 'TCP Kernel Tuning', description: 'OS-level socket optimisation on VPS',
    strategies: ['latency-arb', 'market-making'],
    configurable: false,
  },
]

export function getMethodsForStrategy(strategyId) {
  return TOP_METHODS.filter(m => m.strategies.includes(strategyId))
}

// Generate mock performance data for each method per strategy
let _perfCache = {}

export function getMethodPerformance(strategyId, methodId, rangeId) {
  const key = `${strategyId}-${methodId}-${rangeId}`
  if (_perfCache[key]) return _perfCache[key]

  const seed = (strategyId.length * 100 + methodId.charCodeAt(1) * 37)
  const rng = createRng(seed)

  // Generate A/B test versions for this method
  const rangeDays = { 'today': 1, 'yesterday': 2, '7d': 7, '15d': 15, '1m': 30, '3m': 90, '6m': 180, '12m': 365, 'all': 365 }
  const days = rangeDays[rangeId] || 30
  const baseTradeCount = Math.max(2, Math.floor(days * randRange(rng, 0.8, 2.5)))

  const versionA = {
    id: 'A',
    label: 'Enabled',
    trades: baseTradeCount,
    avgLatency: Math.round(randRange(rng, 80, 400)),
    p50Latency: Math.round(randRange(rng, 60, 300)),
    p95Latency: Math.round(randRange(rng, 200, 800)),
    p99Latency: Math.round(randRange(rng, 400, 1200)),
    winRate: parseFloat(randRange(rng, 75, 98).toFixed(1)),
    avgPnl: parseFloat(randRange(rng, 0.8, 4.2).toFixed(2)),
    totalPnl: 0,
    costPerTrade: parseFloat(randRange(rng, 0.01, 0.15).toFixed(3)),
    edgeCaptured: parseFloat(randRange(rng, 18, 38).toFixed(1)),
  }
  versionA.totalPnl = parseFloat((versionA.avgPnl * versionA.trades).toFixed(2))

  const versionB = {
    id: 'B',
    label: 'Disabled / Baseline',
    trades: Math.floor(baseTradeCount * randRange(rng, 0.85, 1.15)),
    avgLatency: Math.round(versionA.avgLatency * randRange(rng, 1.3, 2.8)),
    p50Latency: Math.round(versionA.p50Latency * randRange(rng, 1.3, 2.5)),
    p95Latency: Math.round(versionA.p95Latency * randRange(rng, 1.2, 2.0)),
    p99Latency: Math.round(versionA.p99Latency * randRange(rng, 1.1, 1.8)),
    winRate: parseFloat(randRange(rng, 65, versionA.winRate - 2).toFixed(1)),
    avgPnl: parseFloat(randRange(rng, 0.3, versionA.avgPnl - 0.2).toFixed(2)),
    totalPnl: 0,
    costPerTrade: parseFloat(randRange(rng, 0, 0.05).toFixed(3)),
    edgeCaptured: parseFloat(randRange(rng, 8, versionA.edgeCaptured - 3).toFixed(1)),
  }
  versionB.totalPnl = parseFloat((versionB.avgPnl * versionB.trades).toFixed(2))

  // Latency improvement
  const latencyDelta = versionB.avgLatency - versionA.avgLatency
  const latencyImprovement = parseFloat(((latencyDelta / versionB.avgLatency) * 100).toFixed(1))

  // Determine status
  const sampleSufficient = versionA.trades >= 50
  const status = sampleSufficient
    ? (versionA.avgPnl > versionB.avgPnl && versionA.avgLatency < versionB.avgLatency ? 'winner' : 'testing')
    : 'testing'

  const result = {
    methodId,
    strategyId,
    versions: [versionA, versionB],
    latencyDelta,
    latencyImprovement,
    status,
    sampleSufficient,
    sampleProgress: Math.min(100, Math.round((versionA.trades / 50) * 100)),
  }

  _perfCache[key] = result
  return result
}

// Generate version history for configurable methods
export function getMethodVersions(strategyId, methodId) {
  const seed = (strategyId.length * 200 + methodId.charCodeAt(1) * 53)
  const rng = createRng(seed)
  const method = TOP_METHODS.find(m => m.id === methodId)
  if (!method || !method.configurable) return []

  const versions = []
  const count = Math.floor(randRange(rng, 2, 6))
  for (let i = 0; i < count; i++) {
    const daysAgo = Math.floor(randRange(rng, i * 10, (i + 1) * 15))
    const date = new Date(Date.now() - daysAgo * 86400000)
    versions.push({
      id: `${methodId}_v${count - i}`,
      name: `${methodId}_v${count - i}`,
      createdAt: date,
      trades: Math.floor(randRange(rng, 20, 120)),
      avgLatency: Math.round(randRange(rng, 80, 500)),
      winRate: parseFloat(randRange(rng, 70, 98).toFixed(1)),
      avgPnl: parseFloat(randRange(rng, 0.5, 4.0).toFixed(2)),
      status: i === 0 ? 'testing' : (i === 1 ? 'winner' : 'retired'),
      configSnapshot: method.params ? Object.fromEntries(
        method.params.filter(p => p.type !== 'toggle').map(p => [p.key, p.type === 'select' ? p.options?.[Math.floor(rng() * (p.options?.length || 1))] : p.type === 'text' ? p.default : parseFloat(randRange(rng, p.min || 0, p.max || 1).toFixed(2))])
      ) : {},
    })
  }
  return versions
}
