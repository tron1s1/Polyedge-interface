import { createRng, randRange, randPick } from '../utils/seedRandom'
import { ALL_STRATEGIES, CATEGORIES, CATEGORY_MAP } from '../utils/constants'

// Generate mock performance data for each strategy
export function getStrategyPerformance(mode) {
  const rng = createRng(mode === 'live' ? 4401 : 4402)
  return ALL_STRATEGIES.map(s => {
    const winRate = Math.round(randRange(rng, 65, 100) * 10) / 10
    const trades = Math.round(randRange(rng, 0, 180))
    const pnl = Math.round(randRange(rng, -50, 400) * 100) / 100
    const todayPnl = Math.round(randRange(rng, -10, 50) * 100) / 100
    const streak = Math.round(randRange(rng, 0, 25))
    const last5 = Array.from({ length: 5 }, () => randPick(rng, ['won', 'won', 'won', 'won', 'lost', 'pending']))
    return {
      ...s,
      mode: 'paper', // all start in paper
      enabled: false,
      winRate,
      totalTrades: trades,
      totalPnl: pnl,
      todayPnl,
      streak,
      allocatedPct: Math.round(s.maxCapPct * 100),
      last5,
      version: `v1`,
      paperGatePct: Math.min(100, Math.round((trades / 50) * 100)),
      categoryColor: CATEGORY_MAP[s.category]?.color || '#888',
      categoryLabel: CATEGORY_MAP[s.category]?.label || s.category,
      categoryCode: CATEGORY_MAP[s.category]?.code || '?',
    }
  })
}

// Group strategies by category
export function getStrategiesByCategory(mode) {
  const strategies = getStrategyPerformance(mode)
  return CATEGORIES.map(cat => ({
    ...cat,
    strategies: strategies.filter(s => s.category === cat.key),
  }))
}

// Get active (live mode) strategies only
export function getActiveStrategies(mode) {
  return getStrategyPerformance(mode).filter(s => s.mode === 'live')
}
