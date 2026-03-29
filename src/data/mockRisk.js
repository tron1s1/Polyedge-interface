import { createRng, randRange, randPick } from '../utils/seedRandom'

export function getCurrentRegime() {
  return {
    regime: 'BULL_RANGING',
    btc1h: 0.3, btc4h: 0.8, btc24h: 1.2,
    fundingRate: 0.018,
    fearGreed: 62, fearGreedLabel: 'Greed',
    atr: 0.8,
    kellyMultiplier: 0.75,
    bearStrategies: 'OFF',
    crashReservePct: 15,
  }
}

export function getCircuitBreakers() {
  return [
    { id: 'CB1', name: 'Daily Loss (10%)',       status: 'armed', detail: 'Today: +$154, Safe',              color: '#1D9E75' },
    { id: 'CB2', name: 'Strategy Loss (25%)',     status: 'armed', detail: 'All strategies in tolerance',     color: '#1D9E75' },
    { id: 'CB3', name: 'Drawdown 15%/25%',       status: 'armed', detail: 'Drawdown: 0%',                    color: '#1D9E75' },
    { id: 'CB4', name: 'Consecutive Loss',        status: 'armed', detail: 'Max streak: 1 loss',              color: '#1D9E75' },
    { id: 'CB5', name: 'API Error Rate',          status: 'armed', detail: 'Error rate: 0.2%',                color: '#1D9E75' },
    { id: 'CB6', name: 'Volatility (BTC +/-5%)',  status: 'armed', detail: 'BTC 15min: +0.1%',                color: '#1D9E75' },
    { id: 'CB7', name: 'Flash Loan Failures',     status: 'armed', detail: '0 consecutive failures',          color: '#1D9E75' },
  ]
}

export function getBearEngineStatus() {
  return {
    bearStrategies: 'INACTIVE',
    reason: 'bull regime',
    crashReserve: 787.50,
    crashReserveNote: '15% of crypto pool — earning funding rate',
    shortStatus: 'STANDBY (RSI signals only)',
    liquidationBot: 'WATCHING',
    nearestCluster: 'BTC $58,200 (-13% away)',
    stablecoins: [
      { name: 'USDC', price: 1.000, ok: true },
      { name: 'USDT', price: 0.999, ok: true },
      { name: 'DAI',  price: 1.001, ok: true },
    ],
  }
}

export function getRegimeHistory() {
  const rng = createRng(8801)
  const regimes = ['BULL_TRENDING', 'VOLATILE_UP', 'BULL_RANGING', 'BULL_TRENDING', 'CRASH_MINOR', 'RECOVERY', 'BULL_RANGING']
  const now = Date.now()
  return regimes.map((regime, i) => ({
    regime,
    startedAt: new Date(now - (regimes.length - i) * 4 * 86400000).toISOString(),
    endedAt: i < regimes.length - 1 ? new Date(now - (regimes.length - i - 1) * 4 * 86400000).toISOString() : null,
    durationDays: Math.round(randRange(rng, 2, 6)),
    kellyUsed: { BULL_TRENDING: 1.0, BULL_RANGING: 0.75, VOLATILE_UP: 0.6, CRASH_MINOR: 0.4, RECOVERY: 0.5 }[regime] || 0.5,
  }))
}
