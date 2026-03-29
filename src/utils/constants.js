// ── Navigation ────────────────────────────────────────────────────────────────
export const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', path: '/' },
  { id: 'nodes', label: 'Nodes', path: '/nodes' },
  { id: 'strategies', label: 'Strategies', path: '/strategies' },
  { id: 'portfolio', label: 'Portfolio', path: '/portfolio' },
  { id: 'risk', label: 'Risk', path: '/risk' },
  { id: 'tax', label: 'Tax', path: '/tax' },
  { id: 'scanner', label: 'Scanner', path: '/scanner' },
  { id: 'analytics', label: 'Analytics', path: '/analytics' },
  { id: 'settings', label: 'Settings', path: '/settings' },
]

// ── Mode ──────────────────────────────────────────────────────────────────────
export const MODE = { PAPER: 'paper', LIVE: 'live' }
export const TRADE_STATUS = { PENDING: 'pending', WON: 'won', LOST: 'lost' }
export const VERSION_STATUS = { TESTING: 'testing', WINNER: 'winner', RETIRED: 'retired', LIVE: 'live' }
export const CHART_COLORS = ['#1D9E75', '#185FA5', '#EF9F27', '#E24B4A', '#9333EA']

// ── Category definitions ──────────────────────────────────────────────────────
export const CATEGORIES = [
  { key: 'A_math',        code: 'A', label: 'Mathematical Certainty', color: '#1D9E75' },
  { key: 'B_technical',   code: 'B', label: 'Technical Speed',        color: '#185FA5' },
  { key: 'C_information', code: 'C', label: 'Information Edge',       color: '#EF9F27' },
  { key: 'D_timing',      code: 'D', label: 'Timing & Leverage',      color: '#E24B4A' },
]

export const CATEGORY_MAP = Object.fromEntries(CATEGORIES.map(c => [c.key, c]))

// ── All 28 strategies ─────────────────────────────────────────────────────────
export const ALL_STRATEGIES = [
  // A: Mathematical Certainty (9)
  { id: 'A_M2_funding_rate',   name: 'Funding Rate Harvest',         category: 'A_math',        node: 'singapore-01', subcategory: 'Delta-neutral',  maxCapPct: 0.30, kelly: 0.75 },
  { id: 'A_FL_flash_loan',     name: 'Flash Loan Arbitrage',         category: 'A_math',        node: 'useast-01',    subcategory: 'DeFi',           maxCapPct: 0.00, kelly: 1.00 },
  { id: 'A_M1_triangular_arb', name: 'Triangular Arbitrage',         category: 'A_math',        node: 'singapore-01', subcategory: 'Same-exchange',  maxCapPct: 0.20, kelly: 1.00 },
  { id: 'A_CEX_cross_arb',     name: 'Cross-Exchange CEX Arb',       category: 'A_math',        node: 'singapore-01', subcategory: 'Multi-exchange', maxCapPct: 0.20, kelly: 0.80 },
  { id: 'A_INR_lag_arb',       name: 'India INR Lag Arb',            category: 'A_math',        node: 'mumbai-01',    subcategory: 'India-specific', maxCapPct: 0.10, kelly: 0.80 },
  { id: 'A_M4_futures_basis',  name: 'Futures Basis Convergence',    category: 'A_math',        node: 'singapore-01', subcategory: 'Dated futures',  maxCapPct: 0.10, kelly: 0.90 },
  { id: 'A_M6_stat_arb',       name: 'BTC/ETH Statistical Arb',      category: 'A_math',        node: 'singapore-01', subcategory: 'Pairs trading',  maxCapPct: 0.10, kelly: 0.50 },
  { id: 'A_M5_pcp_violation',  name: 'Put-Call Parity Violation',    category: 'A_math',        node: 'mumbai-01',    subcategory: 'Options',        maxCapPct: 0.05, kelly: 0.90 },
  { id: 'A_STAB_depeg',        name: 'Stablecoin Depeg Restoration', category: 'A_math',        node: 'singapore-01', subcategory: 'Stablecoin',     maxCapPct: 0.10, kelly: 1.00 },
  // B: Technical Speed (9)
  { id: 'B_NSE_0dte',          name: 'NSE 0DTE Options Selling',     category: 'B_technical',   node: 'mumbai-01',    subcategory: 'India stocks',   maxCapPct: 0.15, kelly: 0.60 },
  { id: 'B_LIST_frontrun',     name: 'Exchange Listing Front-Run',   category: 'B_technical',   node: 'singapore-01', subcategory: 'CEX listing',    maxCapPct: 0.05, kelly: 0.70 },
  { id: 'B_M7_liquidation',    name: 'Liquidation Cascade Bot',      category: 'B_technical',   node: 'useast-01',    subcategory: 'DeFi',           maxCapPct: 0.10, kelly: 0.60 },
  { id: 'B_SPORT_score_arb',   name: 'Sports Live Score Arb',        category: 'B_technical',   node: 'useast-01',    subcategory: 'Sports',         maxCapPct: 0.08, kelly: 0.70 },
  { id: 'B_WHALE_copy',        name: 'Whale Copy Trading',           category: 'B_technical',   node: 'useast-01',    subcategory: 'On-chain',       maxCapPct: 0.05, kelly: 0.40 },
  { id: 'B_SNIPE_token',       name: 'Solana Token Sniper',          category: 'B_technical',   node: 'useast-01',    subcategory: 'DeFi launch',    maxCapPct: 0.03, kelly: 0.25 },
  { id: 'B_NFT_floor_arb',     name: 'NFT Floor Price Arb',          category: 'B_technical',   node: 'useast-01',    subcategory: 'NFT',            maxCapPct: 0.02, kelly: 0.50 },
  { id: 'B_JUP_lag_arb',       name: 'Jupiter Routing Lag Arb',      category: 'B_technical',   node: 'useast-01',    subcategory: 'Solana DEX',     maxCapPct: 0.05, kelly: 0.80 },
  { id: 'B_BYBIT_launchpool',  name: 'Bybit Launchpool Arb',         category: 'B_technical',   node: 'singapore-01', subcategory: 'CEX launchpool', maxCapPct: 0.05, kelly: 0.80 },
  // C: Information Edge (5)
  { id: 'C_AI_crypto_news',    name: 'AI Crypto News Trading',       category: 'C_information', node: 'singapore-01', subcategory: 'AI analysis',    maxCapPct: 0.15, kelly: 0.40 },
  { id: 'C_NSE_earnings_ai',   name: 'NSE Earnings AI Analysis',     category: 'C_information', node: 'mumbai-01',    subcategory: 'India stocks',   maxCapPct: 0.08, kelly: 0.40 },
  { id: 'C_TZ_india_us',       name: 'India-US Timezone Arb',        category: 'C_information', node: 'mumbai-01',    subcategory: 'India stocks',   maxCapPct: 0.08, kelly: 0.50 },
  { id: 'C_FEAR_greed',        name: 'Fear/Greed Index Reversion',   category: 'C_information', node: 'singapore-01', subcategory: 'Sentiment',      maxCapPct: 0.10, kelly: 0.40 },
  { id: 'C_WHALE2_deposit',    name: 'Whale Exchange Deposit Signal',category: 'C_information', node: 'useast-01',    subcategory: 'On-chain',       maxCapPct: 0.05, kelly: 0.35 },
  // D: Timing & Leverage (5)
  { id: 'D_SHORT_systematic',  name: 'Systematic Short Selling',     category: 'D_timing',      node: 'singapore-01', subcategory: 'Short',          maxCapPct: 0.10, kelly: 0.30 },
  { id: 'D_LEV_event_futures', name: 'Event-Driven Leveraged Futures',category: 'D_timing',     node: 'singapore-01', subcategory: 'Macro events',   maxCapPct: 0.08, kelly: 0.30 },
  { id: 'D_PAIR_long_short',   name: 'Long/Short Pair Trading',      category: 'D_timing',      node: 'singapore-01', subcategory: 'Pairs',          maxCapPct: 0.10, kelly: 0.40 },
  { id: 'D_GRID_trading',      name: 'Grid Trading Bot',             category: 'D_timing',      node: 'singapore-01', subcategory: 'Range-bound',    maxCapPct: 0.10, kelly: 0.70 },
  { id: 'D_DCA_volatility',    name: 'DCA + Volatility Harvest',     category: 'D_timing',      node: 'singapore-01', subcategory: 'DCA',            maxCapPct: 0.08, kelly: 0.60 },
]

export const STRATEGY_MAP = Object.fromEntries(ALL_STRATEGIES.map(s => [s.id, s]))

// ── Nodes ─────────────────────────────────────────────────────────────────────
export const NODES = [
  { id: 'singapore-01', name: 'Node 1 — Singapore', location: 'Singapore',     provider: 'Hetzner CX22', region: 'ap-southeast-1', exchange: 'Binance',  monthlyCost: 6 },
  { id: 'mumbai-01',    name: 'Node 2 — Mumbai',    location: 'Mumbai, India', provider: 'AWS',          region: 'ap-south-1',      exchange: 'Zerodha', monthlyCost: 15 },
  { id: 'useast-01',    name: 'Node 3 — US East',   location: 'US East',       provider: 'AWS',          region: 'us-east-1',       exchange: 'Solana',  monthlyCost: 8 },
]

export const NODE_MAP = Object.fromEntries(NODES.map(n => [n.id, n]))

// ── Regimes ───────────────────────────────────────────────────────────────────
export const REGIMES = ['BULL_TRENDING','BULL_RANGING','VOLATILE_UP','CRASH_MINOR','CRASH_MAJOR','RECOVERY','BLACK_SWAN','BEAR_FUNDED']

export const REGIME_COLORS = {
  BULL_TRENDING:'#1D9E75', BULL_RANGING:'#1D9E75', VOLATILE_UP:'#EF9F27',
  CRASH_MINOR:'#E24B4A', CRASH_MAJOR:'#E24B4A', RECOVERY:'#185FA5',
  BLACK_SWAN:'#E24B4A', BEAR_FUNDED:'#EF9F27',
}

export const KELLY_BY_REGIME = {
  BULL_TRENDING:1.0, BULL_RANGING:0.75, VOLATILE_UP:0.60, CRASH_MINOR:0.40,
  CRASH_MAJOR:0.20, RECOVERY:0.50, BLACK_SWAN:0.0, BEAR_FUNDED:0.30,
}

// ── Capital Pools ─────────────────────────────────────────────────────────────
export const CAPITAL_POOLS = [
  { id: 'crypto_sg',    name: 'Crypto — Singapore (Binance/Bybit)', currency: 'USDC', exchange: 'Binance' },
  { id: 'crypto_def',   name: 'Crypto — DeFi (Solana/ETH)',        currency: 'USDC', exchange: 'Solana' },
  { id: 'india_stocks', name: 'India Stocks (Zerodha NSE)',         currency: 'INR',  exchange: 'Zerodha' },
  { id: 'india_crypto', name: 'India Crypto (CoinDCX INR)',         currency: 'INR',  exchange: 'CoinDCX' },
  { id: 'tax_reserve',  name: 'India Tax Reserve (30%+1% TDS)',     currency: 'INR',  exchange: 'Manual' },
  { id: 'emergency',    name: 'Emergency Reserve (never trade)',    currency: 'USDC', exchange: 'Cold' },
]
