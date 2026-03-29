import { createRng, randRange } from '../utils/seedRandom'
import { STRATEGIES } from '../utils/constants'

export function getDailyPnlData(mode, days = 30) {
  const rng = createRng(mode === 'paper' ? 42 : 99)
  const data = []
  const now = new Date()
  for (let i = days; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)
    const entry = { date: date.toISOString().split('T')[0] }
    let total = 0
    for (const s of STRATEGIES) {
      const base = mode === 'paper' ? 40 : 80
      const val = parseFloat(randRange(rng, -base * 0.3, base * 1.2).toFixed(2))
      entry[s.id] = val
      total += val
    }
    entry.total = parseFloat(total.toFixed(2))
    data.push(entry)
  }
  return data
}

export function getCumulativePnlData(mode, days = 30) {
  const daily = getDailyPnlData(mode, days)
  const cumulative = { 'latency-arb': 0, 'negrisk-arb': 0, 'ai-news': 0, 'market-making': 0, total: 0 }
  return daily.map(d => {
    const entry = { date: d.date }
    for (const s of STRATEGIES) {
      cumulative[s.id] += d[s.id]
      entry[s.id] = parseFloat(cumulative[s.id].toFixed(2))
    }
    cumulative.total += d.total
    entry.total = parseFloat(cumulative.total.toFixed(2))
    return entry
  })
}

export function getWinRateData(mode, days = 30) {
  const rng = createRng(mode === 'paper' ? 200 : 300)
  const data = []
  const now = new Date()
  for (let i = days; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)
    data.push({
      date: date.toISOString().split('T')[0],
      combined: parseFloat(randRange(rng, 72, 92).toFixed(1)),
      'latency-arb': parseFloat(randRange(rng, 90, 99).toFixed(1)),
      'negrisk-arb': 100,
      'ai-news': parseFloat(randRange(rng, 68, 88).toFixed(1)),
      'market-making': parseFloat(randRange(rng, 78, 92).toFixed(1)),
    })
  }
  return data
}

export function getAllocationData(mode) {
  if (mode === 'paper') {
    return [
      { id: 'latency-arb', name: 'Latency Arb', percent: 28, amount: 2800, color: '#E24B4A' },
      { id: 'negrisk-arb', name: 'NegRisk Arb', percent: 22, amount: 2200, color: '#1D9E75' },
      { id: 'ai-news', name: 'AI News', percent: 38, amount: 3800, color: '#185FA5' },
      { id: 'market-making', name: 'Market Making', percent: 12, amount: 1200, color: '#EF9F27' },
    ]
  }
  return [
    { id: 'latency-arb', name: 'Latency Arb', percent: 32, amount: 4800, color: '#E24B4A' },
    { id: 'negrisk-arb', name: 'NegRisk Arb', percent: 18, amount: 2700, color: '#1D9E75' },
    { id: 'ai-news', name: 'AI News', percent: 40, amount: 6000, color: '#185FA5' },
    { id: 'market-making', name: 'Market Making', percent: 10, amount: 1500, color: '#EF9F27' },
  ]
}

export function getLatencyData() {
  return [
    { method: 'B1 Async Parallel', status: 'ON', saved: '24,500ms', trades: 'All', winDelta: 'N/A', cost: '$0' },
    { method: 'B2 Redis Cache', status: 'ON', saved: '45ms avg', trades: 'All', winDelta: 'N/A', cost: '$0' },
    { method: 'B3 WebSocket', status: 'ON', saved: '1,200ms', trades: 'Latency, MM', winDelta: '+2.1%', cost: '$0' },
    { method: 'T1 Haiku Triage', status: 'ON', saved: '800ms', trades: 'AI News', winDelta: '-0.3%', cost: '$0.08' },
    { method: 'T5 Pre-sign', status: 'Winner', saved: '142ms', trades: 'Latency', winDelta: '+1.8%', cost: '$0' },
    { method: 'T6 Oracle Direct', status: 'Testing', saved: 'TBD', trades: 'Latency', winDelta: 'TBD', cost: '$0.01' },
    { method: 'T7 Co-location', status: 'Tokyo', saved: '87ms', trades: 'Latency', winDelta: '+3.2%', cost: '$6/mo' },
    { method: 'T11 Model Race', status: 'ON', saved: '600ms', trades: 'AI News', winDelta: '+0.7%', cost: '$0.12' },
  ]
}

export function getSparklineData(strategyId, mode) {
  const rng = createRng(strategyId.length * 100 + (mode === 'paper' ? 5 : 10))
  let val = 0
  return Array.from({ length: 14 }, (_, i) => {
    val += randRange(rng, -20, 45)
    return { day: i, value: parseFloat(val.toFixed(2)) }
  })
}

export function getGrowthData(mode) {
  const rng = createRng(mode === 'paper' ? 555 : 666)
  const startCapital = mode === 'paper' ? 10000 : 15000
  let actual = startCapital
  const monthlyReturn = 0.22
  const data = []
  const now = new Date()
  for (let i = 0; i <= 12; i++) {
    const date = new Date(now)
    date.setMonth(date.getMonth() - 12 + i)
    const projected = startCapital * Math.pow(1 + monthlyReturn, i)
    if (i > 0) actual = actual * (1 + randRange(rng, 0.05, 0.35))
    data.push({
      month: date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
      actual: Math.round(actual),
      projected: Math.round(projected),
    })
  }
  return data
}
