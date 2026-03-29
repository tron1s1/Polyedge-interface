-- ============================================================
-- NODE 1 SCHEMA — AlphaNode Singapore
-- Run in Supabase SQL editor
-- ============================================================

-- Deployment config
CREATE TABLE IF NOT EXISTS deployment_config (
  key         text PRIMARY KEY,
  value       text NOT NULL,
  node_id     text DEFAULT 'singapore-01',
  updated_at  timestamptz DEFAULT now()
);

INSERT INTO deployment_config (key, value) VALUES
  ('active_slot',         'green'),
  ('system_version',      '1.0.0'),
  ('kill_switch_global',  'false'),
  ('global_regime',       'BULL_RANGING'),
  ('crash_reserve_pct',   '0.15'),
  ('tax_reserve_usdc',    '0.00'),
  ('node_singapore_status', 'offline'),
  ('node_mumbai_status',  'offline'),
  ('node_useast_status',  'offline')
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- Nodes registry
-- ============================================================
CREATE TABLE IF NOT EXISTS nodes (
  node_id           text PRIMARY KEY,
  display_name      text NOT NULL,
  location          text NOT NULL,
  cloud_provider    text,
  primary_exchange  text,
  strategies        text[],
  status            text DEFAULT 'offline',
  slot              text DEFAULT 'green',
  last_heartbeat    timestamptz,
  monthly_cost_usd  float DEFAULT 6.00,
  deployed_at       timestamptz DEFAULT now()
);

INSERT INTO nodes VALUES (
  'singapore-01', 'Node 1 — Singapore', 'Singapore (Hetzner CX22)',
  'Hetzner', 'Binance',
  ARRAY['A_M2_funding_rate','A_FL_flash_loan','A_M1_triangular_arb',
        'A_CEX_cross_arb','A_M4_futures_basis','A_M6_stat_arb',
        'A_STAB_depeg','B_LIST_frontrun','B_BYBIT_launchpool',
        'C_AI_crypto_news','C_FEAR_greed','D_SHORT_systematic',
        'D_GRID_trading','D_DCA_volatility','D_PAIR_long_short'],
  'offline', 'green', null, 6.00, now()
) ON CONFLICT (node_id) DO UPDATE SET status = 'offline';

-- ============================================================
-- Strategy plugins registry
-- ============================================================
CREATE TABLE IF NOT EXISTS strategy_plugins (
  strategy_id       text PRIMARY KEY,
  display_name      text NOT NULL,
  category          text NOT NULL,
  category_label    text NOT NULL,
  description       text,
  file_name         text NOT NULL,
  node_id           text DEFAULT 'singapore-01',
  enabled           boolean DEFAULT false,
  mode              text DEFAULT 'paper',
  max_capital_pct   float DEFAULT 0.05,
  kelly_multiplier  float DEFAULT 0.25,
  live_trades_count integer DEFAULT 0,
  paper_trades_count integer DEFAULT 0,
  win_rate          float,
  total_pnl_usdc    float DEFAULT 0,
  last_trade_at     timestamptz,
  version_tag       text,
  notes             text,
  uploaded_at       timestamptz DEFAULT now()
);

INSERT INTO strategy_plugins
  (strategy_id, display_name, category, category_label, description, file_name, max_capital_pct, kelly_multiplier)
VALUES
  ('A_M2_funding_rate',   'Funding Rate Harvest',        'A_math',        'Mathematical Certainty', 'Short perps + long spot. Earn 8h funding. Risk-free.',          'A_M2_funding_rate.py',   0.30, 0.75),
  ('A_FL_flash_loan',     'Flash Loan Arbitrage',        'A_math',        'Mathematical Certainty', 'Borrow-arb-repay in 1 tx. Zero capital. Solana/ETH.',           'A_FL_flash_loan.py',     0.00, 1.00),
  ('A_M1_triangular_arb', 'Triangular Arbitrage',        'A_math',        'Mathematical Certainty', 'BTC/ETH/USDT triangle on Binance. 100% when gap exists.',       'A_M1_triangular_arb.py', 0.20, 1.00),
  ('A_CEX_cross_arb',     'Cross-Exchange CEX Arb',      'A_math',        'Mathematical Certainty', 'Same asset mispriced across Binance/OKX/KuCoin.',              'A_CEX_cross_arb.py',     0.20, 0.80),
  ('A_M4_futures_basis',  'Futures Basis Convergence',   'A_math',        'Mathematical Certainty', 'Dated futures premium converges to spot at expiry.',           'A_M4_futures_basis.py',  0.10, 0.90),
  ('A_M6_stat_arb',       'BTC/ETH Statistical Arb',     'A_math',        'Mathematical Certainty', 'Cointegrated pair. Trade ratio divergence. 95% convergence.',  'A_M6_stat_arb.py',       0.10, 0.50),
  ('A_STAB_depeg',        'Stablecoin Depeg Restore',    'A_math',        'Mathematical Certainty', 'Buy depegged stablecoin. Guaranteed return to $1.',            'A_STAB_depeg.py',        0.10, 1.00),
  ('B_LIST_frontrun',     'Exchange Listing Front-Run',  'B_technical',   'Technical Speed',        'Binance listing → buy KuCoin/MEXC before crowd. +45% avg.',    'B_LIST_frontrun.py',     0.05, 0.70),
  ('B_BYBIT_launchpool',  'Bybit Launchpool Arb',        'B_technical',   'Technical Speed',        'Stake for new token before listing. 250% avg ROI.',            'B_BYBIT_launchpool.py',  0.05, 0.80),
  ('C_AI_crypto_news',    'AI Crypto News Trading',      'C_information', 'Information Edge',       'Claude analyses breaking news → prob vs market gap.',          'C_AI_crypto_news.py',    0.15, 0.40),
  ('C_FEAR_greed',        'Fear/Greed Reversion',        'C_information', 'Information Edge',       'Buy extreme fear (<15), sell extreme greed (>85).',            'C_FEAR_greed.py',        0.10, 0.40),
  ('D_SHORT_systematic',  'Systematic Short Selling',    'D_timing',      'Timing & Leverage',      'RSI overbought + high funding + AI bearish = short. 5x max.', 'D_SHORT_systematic.py',  0.10, 0.30),
  ('D_GRID_trading',      'Grid Trading Bot',            'D_timing',      'Timing & Leverage',      'Buy/sell orders every $X up/down. Earns spread in range.',     'D_GRID_trading.py',      0.10, 0.70),
  ('D_DCA_volatility',    'DCA + Volatility Harvest',    'D_timing',      'Timing & Leverage',      'Buy every 2% dip, sell every 2% bounce. Systematic.',          'D_DCA_volatility.py',    0.08, 0.60),
  ('D_PAIR_long_short',   'Long/Short Pair Trading',     'D_timing',      'Timing & Leverage',      'Long strong, short weak correlated pair. Delta-neutral.',      'D_PAIR_long_short.py',   0.10, 0.40)
ON CONFLICT (strategy_id) DO NOTHING;

-- ============================================================
-- Strategy flags (feature flags for zero-downtime control)
-- ============================================================
CREATE TABLE IF NOT EXISTS strategy_flags (
  strategy_id    text PRIMARY KEY REFERENCES strategy_plugins(strategy_id),
  enabled        boolean DEFAULT false,
  mode           text DEFAULT 'paper',
  max_capital    float DEFAULT 0,
  kill_switch    boolean DEFAULT false,
  updated_at     timestamptz DEFAULT now()
);

INSERT INTO strategy_flags (strategy_id)
  SELECT strategy_id FROM strategy_plugins
ON CONFLICT (strategy_id) DO NOTHING;

-- ============================================================
-- Trades (all strategies, paper + live)
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
  id                  uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  strategy_id         text NOT NULL,
  version_tag         text,
  market_id           text NOT NULL,
  symbol              text NOT NULL,
  exchange            text DEFAULT 'binance',
  node_id             text DEFAULT 'singapore-01',
  pool_id             text DEFAULT 'crypto_sg',
  direction           text NOT NULL,
  entry_price         float NOT NULL,
  size_usdc           float NOT NULL,
  kelly_fraction      float,
  leverage            float DEFAULT 1.0,
  stop_loss_price     float,
  take_profit_price   float,
  ai_confidence       float,
  ai_reasoning        text,
  opportunity_score   float,
  edge_detected       float,
  regime_at_trade     text,
  bear_strategy       boolean DEFAULT false,
  gas_cost_usdc       float DEFAULT 0,
  is_paper            boolean DEFAULT true,
  slot                text DEFAULT 'green',
  latency_ms          float,
  tax_reserved_usdc   float DEFAULT 0,
  reinvested_usdc     float DEFAULT 0,
  created_at          timestamptz DEFAULT now(),
  resolved_at         timestamptz,
  outcome             text DEFAULT 'pending',
  exit_price          float,
  pnl_usdc            float
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_node ON trades(node_id);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_paper ON trades(is_paper);

-- ============================================================
-- Latency versions (A/B testing per strategy)
-- ============================================================
CREATE TABLE IF NOT EXISTS latency_versions (
  id                  uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  version_tag         text NOT NULL UNIQUE,
  strategy_id         text NOT NULL,
  node_id             text DEFAULT 'singapore-01',
  base_methods        text[] NOT NULL,
  top_methods         text[] DEFAULT '{}',
  is_paper            boolean DEFAULT true,
  is_active           boolean DEFAULT true,
  is_live             boolean DEFAULT false,
  slot                text DEFAULT 'green',
  created_at          timestamptz DEFAULT now(),
  promoted_live_at    timestamptz,
  commit_hash         text,
  total_trades        integer DEFAULT 0,
  win_rate            float,
  avg_latency_ms      float,
  avg_edge_captured   float,
  total_pnl_usdc      float DEFAULT 0
);

-- ============================================================
-- Scanner cycles log
-- ============================================================
CREATE TABLE IF NOT EXISTS scanner_cycles (
  id               uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  node_id          text DEFAULT 'singapore-01',
  cycle_at         timestamptz DEFAULT now(),
  markets_scored   integer,
  duration_ms      float,
  top_opportunities jsonb,
  regime           text,
  allocation       jsonb,
  slot             text DEFAULT 'green'
);

-- ============================================================
-- Market regime history
-- ============================================================
CREATE TABLE IF NOT EXISTS market_regime (
  id                      uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  detected_at             timestamptz DEFAULT now(),
  regime                  text NOT NULL,
  btc_change_1h           float,
  btc_change_4h           float,
  btc_change_24h          float,
  fear_greed_index        integer,
  funding_rate            float,
  market_atr              float,
  kelly_multiplier        float,
  active_strategies       text[],
  paused_strategies       text[],
  crash_reserve_deployed  float DEFAULT 0
);

-- ============================================================
-- Capital pools
-- ============================================================
CREATE TABLE IF NOT EXISTS capital_pools (
  pool_id          text PRIMARY KEY,
  display_name     text NOT NULL,
  currency         text NOT NULL,
  exchange         text,
  current_balance  float DEFAULT 0,
  peak_balance     float DEFAULT 0,
  reserved_crash   float DEFAULT 0,
  reserved_tax     float DEFAULT 0,
  reinvestable     float DEFAULT 0,
  drawdown_pct     float DEFAULT 0,
  updated_at       timestamptz DEFAULT now()
);

INSERT INTO capital_pools (pool_id, display_name, currency, exchange) VALUES
  ('crypto_sg',   'Crypto — Singapore (Binance/Bybit)',  'USDC', 'Binance'),
  ('tax_reserve', 'India Tax Reserve (30%+1% TDS)',      'INR',  'Manual'),
  ('emergency',   'Emergency Reserve (never trade)',      'USDC', 'Cold')
ON CONFLICT (pool_id) DO NOTHING;

-- ============================================================
-- Risk snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_snapshots (
  id                       uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  captured_at              timestamptz DEFAULT now(),
  node_id                  text DEFAULT 'singapore-01',
  regime                   text,
  total_capital_usdc       float,
  peak_capital_usdc        float,
  drawdown_pct             float,
  daily_pnl_usdc           float,
  winning_strategies       text[],
  losing_strategies        text[],
  circuit_breakers_active  text[],
  exchange_api_health      jsonb,
  kelly_multiplier         float,
  crash_reserve_balance    float
);

-- ============================================================
-- Correlation map (D2 chain trading)
-- ============================================================
CREATE TABLE IF NOT EXISTS correlation_map (
  id                   uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  trigger_keyword      text NOT NULL,
  correlated_markets   jsonb NOT NULL,
  category             text,
  strength             text,
  lag_minutes          integer DEFAULT 5,
  created_at           timestamptz DEFAULT now(),
  updated_at           timestamptz DEFAULT now()
);

-- ============================================================
-- API config
-- ============================================================
CREATE TABLE IF NOT EXISTS api_config (
  service          text PRIMARY KEY,
  api_key_env_var  text,
  base_url         text,
  is_connected     boolean DEFAULT false,
  last_tested_at   timestamptz,
  rate_limit_per_min integer,
  notes            text
);

INSERT INTO api_config (service, api_key_env_var, base_url, notes) VALUES
  ('binance_spot',    'BINANCE_API_KEY',    'https://api.binance.com',           'Primary CEX'),
  ('binance_futures', 'BINANCE_API_KEY',    'https://fapi.binance.com',          'Perps'),
  ('binance_ws',      'BINANCE_API_KEY',    'wss://stream.binance.com:9443/ws',  'Price feed WS'),
  ('bybit_spot',      'BYBIT_API_KEY',      'https://api.bybit.com',             'Funding rate'),
  ('bybit_ws',        'BYBIT_API_KEY',      'wss://stream.bybit.com/v5/public',  'Bybit WS'),
  ('okx_spot',        'OKX_API_KEY',        'https://www.okx.com',               'Cross-arb target'),
  ('kucoin_spot',     'KUCOIN_API_KEY',     'https://api.kucoin.com',            'Listing arb'),
  ('mexc_spot',       'MEXC_API_KEY',       'https://api.mexc.com',              'Low fees, new tokens'),
  ('fear_greed_api',  null,                 'https://api.alternative.me/fng',    'Free Fear/Greed'),
  ('twitter_x',       'TWITTER_BEARER_TOKEN','https://api.twitter.com/2',        'Listing announcements'),
  ('newsapi',         'NEWSAPI_KEY',        'https://newsapi.org/v2',            'AI crypto news'),
  ('gdelt_news',      null,                 'https://api.gdeltproject.org/api/v2', 'Free news stream'),
  ('coinglass',       'COINGLASS_API_KEY',  'https://open-api.coinglass.com',    'Liquidation data'),
  ('reddit_api',      'REDDIT_CLIENT_ID',   'https://oauth.reddit.com',          'Sentiment signal'),
  ('anthropic',       'ANTHROPIC_API_KEY',  'https://api.anthropic.com/v1',      'C_AI strategy only'),
  ('redis_cache',     'REDIS_URL',          null,                                'L2 cache'),
  ('supabase_db',     'SUPABASE_URL',       null,                                'Primary DB'),
  ('telegram_bot',    'TELEGRAM_BOT_TOKEN', 'https://api.telegram.org',          'Alerts')
ON CONFLICT (service) DO NOTHING;

-- ============================================================
-- Tax events (India 30% + 1% TDS)
-- ============================================================
CREATE TABLE IF NOT EXISTS tax_events (
  id                       uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  trade_id                 uuid REFERENCES trades(id),
  financial_year           text NOT NULL,
  event_type               text NOT NULL,
  asset                    text,
  exchange                 text,
  gross_profit_usdc        float DEFAULT 0,
  gross_profit_inr         float DEFAULT 0,
  tax_30pct_inr            float DEFAULT 0,
  tds_1pct_inr             float DEFAULT 0,
  net_tax_to_pay_inr       float DEFAULT 0,
  amount_reserved_usdc     float DEFAULT 0,
  amount_reinvested_usdc   float DEFAULT 0,
  usd_inr_rate             float DEFAULT 84.0,
  created_at               timestamptz DEFAULT now()
);
