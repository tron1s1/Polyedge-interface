import { createRng, randRange, randPick } from '../utils/seedRandom'

export function getNodeScannerStatus() {
  const rng = createRng(3301)
  return [
    {
      nodeId: 'singapore-01', name: 'Node 1 — Singapore', status: 'online',
      marketsScored: 847, durationMs: 230, eventsToday: 3421,
      websockets: [
        { name: 'Binance', connected: true }, { name: 'Bybit', connected: true }, { name: 'OKX', connected: true },
      ],
      topOpportunities: [
        { market: 'BTC triangular arb', gap: '0.41%', score: 87, strategy: 'A_M1' },
        { market: 'ETH funding rate', gap: '+0.031%/8h', score: 71, strategy: 'A_M2' },
        { market: 'Raydium/Orca SOL gap', gap: '0.28%', score: 64, strategy: 'A_FL' },
      ],
    },
    {
      nodeId: 'mumbai-01', name: 'Node 2 — Mumbai', status: 'offline',
      marketsScored: 0, durationMs: 0, eventsToday: 0,
      websockets: [], topOpportunities: [],
    },
    {
      nodeId: 'useast-01', name: 'Node 3 — US East', status: 'offline',
      marketsScored: 0, durationMs: 0, eventsToday: 0,
      websockets: [], topOpportunities: [],
    },
  ]
}

export function getLoopholeStatus() {
  const rng = createRng(8801)
  return [
    { id: 'L1', name: 'Binance WS',       connected: true,  detail: `Last msg: ${randRange(rng, 0.05, 0.3).toFixed(1)}s ago` },
    { id: 'L2', name: 'Sports scores',     connected: true,  detail: 'NBA game live (Lakers vs Celtics, Q3 2:34)' },
    { id: 'L3', name: 'Funding rate',      connected: true,  detail: '+0.018%/8h (moderate)' },
    { id: 'L4', name: 'GDELT news',        connected: true,  detail: `${Math.round(randRange(rng, 30, 60))} crypto articles in last 30min` },
    { id: 'L5', name: 'Whale tracker',     connected: true,  detail: `${Math.round(randRange(rng, 1, 4))} wallets monitored, 0 signals today` },
    { id: 'L6', name: 'Low-volume',        connected: true,  detail: `${Math.round(randRange(rng, 14, 22))}% of opportunities from <$10k volume` },
    { id: 'L7', name: 'INR lag',           connected: false, detail: '0.12% avg gap today (CoinDCX vs Binance)' },
    { id: 'L8', name: 'Liquidation',       connected: true,  detail: 'Next cluster at BTC $58,200 (-13%)' },
  ]
}

export function getRegimeSignals() {
  return {
    btcPrice: 67420, ethPrice: 3580,
    fearGreed: 62, fearGreedLabel: 'Greed',
    fundingRate: 0.018,
    nearestLiquidation: { price: 58200, distance: '-13%' },
  }
}
