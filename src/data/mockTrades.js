import { createRng, randRange, randPick, randDate } from '../utils/seedRandom'
import { STRATEGIES, TRADE_STATUS } from '../utils/constants'

const MARKETS = {
  'latency-arb': [
    'BTC above $70k by Apr', 'BTC above $65k by Mar 31', 'ETH above $4k by Apr',
    'SOL above $200 by Apr', 'BTC above $80k by Jun', 'ETH above $3.5k by Mar',
  ],
  'negrisk-arb': [
    'US Senate Race — Ohio', '2026 French Election', 'UK PM Next — Multi',
    'FIFA World Cup Winner', 'Fed Chair Next', 'NBA MVP 2026',
  ],
  'ai-news': [
    'Fed cuts rates March', 'Trump tariff announcement', 'China GDP > 5%',
    'SpaceX Starship success', 'AI regulation bill passes', 'OPEC cuts production',
  ],
  'market-making': [
    'Biden approval > 45%', 'Tesla stock > $300', 'Ethereum merge delay',
    'Netflix subscribers > 300M', 'Gold above $2200', 'Oil above $90',
  ],
}

function generateTrade(rng, strategyId, mode, index, dayOffset) {
  const strategy = STRATEGIES.find(s => s.id === strategyId)
  const market = randPick(rng, MARKETS[strategyId])
  const direction = rng() > 0.45 ? 'YES' : 'NO'
  const entryPrice = parseFloat(randRange(rng, 0.25, 0.78).toFixed(2))
  const baseWinRate = strategy.winRate / 100
  const won = rng() < baseWinRate
  const status = dayOffset < 1 && rng() > 0.7 ? TRADE_STATUS.PENDING : (won ? TRADE_STATUS.WON : TRADE_STATUS.LOST)
  const exitPrice = status === TRADE_STATUS.PENDING ? null : (won
    ? parseFloat((entryPrice + randRange(rng, 0.08, 0.35)).toFixed(2))
    : parseFloat((entryPrice - randRange(rng, 0.05, 0.15)).toFixed(2)))
  const size = parseFloat(randRange(rng, mode === 'paper' ? 50 : 100, mode === 'paper' ? 500 : 2000).toFixed(0))
  const pnl = status === TRADE_STATUS.PENDING ? 0 : (won
    ? size * (exitPrice - entryPrice) / entryPrice
    : -(size * (entryPrice - exitPrice) / entryPrice))
  const confidence = strategyId === 'ai-news' ? parseFloat(randRange(rng, 0.55, 0.95).toFixed(2)) : null
  const edge = parseFloat(randRange(rng, 0.05, 0.38).toFixed(2))
  const latency = strategyId === 'latency-arb' ? Math.round(randRange(rng, 80, 280)) :
    strategyId === 'ai-news' ? Math.round(randRange(rng, 800, 2500)) :
    Math.round(randRange(rng, 100, 600))
  const gapSize = strategyId === 'latency-arb' ? parseFloat(randRange(rng, 0.08, 0.42).toFixed(2)) : null

  return {
    id: `${mode}-${strategyId}-${index}`,
    strategyId,
    mode,
    market,
    direction,
    entryPrice,
    exitPrice,
    size,
    pnl: parseFloat(pnl.toFixed(2)),
    status,
    confidence,
    edge,
    latency,
    gapSize,
    kellyFraction: parseFloat(randRange(rng, 0.1, 0.5).toFixed(2)),
    version: `v${Math.floor(randRange(rng, 1, 8))}`,
    timestamp: randDate(rng, Math.max(0, dayOffset + 1), Math.max(0, dayOffset)),
  }
}

let _cache = {}

export function getMockTrades(strategyId, mode) {
  const key = `${strategyId}-${mode}`
  if (_cache[key]) return _cache[key]

  const rng = createRng(strategyId.length * 1000 + (mode === 'paper' ? 1 : 2) * 7777)
  const count = mode === 'paper' ? 600 : 220
  const trades = []
  for (let i = 0; i < count; i++) {
    const dayOffset = (i / count) * 365
    trades.push(generateTrade(rng, strategyId, mode, i, dayOffset))
  }
  trades.sort((a, b) => b.timestamp - a.timestamp)
  _cache[key] = trades
  return trades
}

export function getAllTrades(mode) {
  return STRATEGIES.flatMap(s => getMockTrades(s.id, mode)).sort((a, b) => b.timestamp - a.timestamp)
}

export const TIME_RANGES = [
  { id: 'today', label: 'Today', days: 1 },
  { id: 'yesterday', label: 'Yesterday', days: 2, offsetStart: 1 },
  { id: '7d', label: 'Last 7 Days', days: 7 },
  { id: '15d', label: 'Last 15 Days', days: 15 },
  { id: '1m', label: 'Last 1 Month', days: 30 },
  { id: '3m', label: 'Last 3 Months', days: 90 },
  { id: '6m', label: 'Last 6 Months', days: 180 },
  { id: '12m', label: 'Last 12 Months', days: 365 },
  { id: 'all', label: 'Overall', days: Infinity },
]

export function filterTradesByRange(trades, rangeId) {
  const range = TIME_RANGES.find(r => r.id === rangeId) || TIME_RANGES[8]
  if (range.days === Infinity) return trades
  const now = Date.now()
  const offsetStart = range.offsetStart || 0
  const start = now - range.days * 86400000
  const end = offsetStart ? now - offsetStart * 86400000 : now
  return trades.filter(t => t.timestamp >= start && t.timestamp <= end)
}

export function getTradeStats(trades) {
  const resolved = trades.filter(t => t.status !== TRADE_STATUS.PENDING)
  const wins = resolved.filter(t => t.status === TRADE_STATUS.WON)
  const totalPnl = resolved.reduce((sum, t) => sum + t.pnl, 0)
  const avgPnl = resolved.length ? totalPnl / resolved.length : 0
  const avgLatency = trades.length ? trades.reduce((s, t) => s + t.latency, 0) / trades.length : 0
  const avgEdge = trades.length ? trades.reduce((s, t) => s + t.edge, 0) / trades.length : 0
  const avgKelly = trades.length ? trades.reduce((s, t) => s + t.kellyFraction, 0) / trades.length : 0

  return {
    totalTrades: trades.length,
    resolvedTrades: resolved.length,
    wins: wins.length,
    losses: resolved.length - wins.length,
    winRate: resolved.length ? (wins.length / resolved.length) * 100 : 0,
    totalPnl,
    avgPnl,
    avgLatency: Math.round(avgLatency),
    avgEdge: parseFloat((avgEdge * 100).toFixed(1)),
    avgKelly: parseFloat((avgKelly * 100).toFixed(1)),
    bestTrade: resolved.length ? Math.max(...resolved.map(t => t.pnl)) : 0,
    worstTrade: resolved.length ? Math.min(...resolved.map(t => t.pnl)) : 0,
    pendingTrades: trades.filter(t => t.status === TRADE_STATUS.PENDING).length,
  }
}
