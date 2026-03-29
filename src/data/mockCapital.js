import { createRng, randRange } from '../utils/seedRandom'

const USD_INR = 84.0

export function getCapitalPools(mode) {
  const rng = createRng(mode === 'live' ? 5501 : 5502)
  return [
    { id: 'crypto_sg',    name: 'Crypto — Singapore',   currency: 'USDC', exchange: 'Binance',  balance: 2100,  pct: 40, color: '#1D9E75' },
    { id: 'crypto_def',   name: 'Crypto — DeFi',        currency: 'USDC', exchange: 'Solana',   balance: 1050,  pct: 20, color: '#185FA5' },
    { id: 'india_stocks', name: 'India Stocks',          currency: 'INR',  exchange: 'Zerodha',  balance: 42000, pct: 10, color: '#EF9F27', usdEquiv: 500 },
    { id: 'india_crypto', name: 'India Crypto',          currency: 'INR',  exchange: 'CoinDCX',  balance: 10500, pct: 2.5, color: '#9333EA', usdEquiv: 125 },
    { id: 'tax_reserve',  name: 'Tax Reserve',           currency: 'INR',  exchange: 'Manual',   balance: 24780, pct: 6, color: '#E24B4A', usdEquiv: 295, neverInvest: true },
    { id: 'emergency',    name: 'Emergency Reserve',     currency: 'USDC', exchange: 'Cold',     balance: 525,   pct: 10, color: '#6B7280', neverInvest: true },
    { id: 'flash_loans',  name: 'Flash Loans',           currency: 'USDC', exchange: 'Solana',   balance: 0,     pct: 0, color: '#14B8A6', note: 'Earns $84/day via borrowed capital' },
  ]
}

export function getPortfolioSummary(mode) {
  const rng = createRng(mode === 'live' ? 6601 : 6602)
  return {
    totalUsdc: 5240,
    totalInr: 85000,
    totalUsdEquiv: 5240 + Math.round(85000 / USD_INR),
    peakUsdc: 5240,
    drawdownPct: 0,
    todayCryptoPnl: Math.round(randRange(rng, 80, 180) * 100) / 100,
    todayIndiaPnl: Math.round(randRange(rng, 1500, 3000)),
    todayFlashPnl: Math.round(randRange(rng, 50, 120) * 100) / 100,
    todayTaxReserved: Math.round(randRange(rng, 30, 60) * 100) / 100,
    usdInrRate: USD_INR,
  }
}

export function getAllocationByStrategy(mode) {
  const rng = createRng(mode === 'live' ? 7701 : 7702)
  return [
    { id: 'A_M2_funding_rate',   name: 'Funding Rate',   pct: 30 },
    { id: 'A_FL_flash_loan',     name: 'Flash Loan',     pct: 0, note: 'No capital needed' },
    { id: 'A_M1_triangular_arb', name: 'Triangular Arb', pct: 20 },
    { id: 'D_GRID_trading',      name: 'Grid Bot',       pct: 20 },
    { id: 'C_AI_crypto_news',    name: 'AI News',        pct: 15 },
    { id: 'reserve',             name: 'Reserve',        pct: 15 },
  ]
}
