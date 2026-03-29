import { createRng, randRange } from '../utils/seedRandom'
import { ALL_STRATEGIES, NODES } from '../utils/constants'

export function getNodeStatuses() {
  const rng = createRng(7701)
  return NODES.map(node => {
    const strategies = ALL_STRATEGIES.filter(s => s.node === node.id)
    const isOnline = node.id === 'singapore-01' // only SG online initially
    return {
      ...node,
      status: isOnline ? 'online' : 'offline',
      slot: 'green',
      strategies,
      strategyCount: strategies.length,
      uptime: isOnline ? (99 + rng()).toFixed(1) : 0,
      lastHeartbeat: isOnline ? new Date(Date.now() - Math.round(randRange(rng, 1000, 5000))).toISOString() : null,
      latencyMs: isOnline ? Math.round(randRange(rng, 2, 8)) : null,
      todayPnl: isOnline ? Math.round(randRange(rng, 80, 200) * 100) / 100 : 0,
      todayTrades: isOnline ? Math.round(randRange(rng, 20, 60)) : 0,
      winRate: isOnline ? Math.round(randRange(rng, 88, 98) * 10) / 10 : 0,
    }
  })
}
