export function getApiConnections() {
  return {
    infrastructure: [
      { service: 'supabase_db',      name: 'Supabase',        envVar: 'SUPABASE_URL',        testUrl: null,                                         rateLimit: null, notes: 'Primary database. All nodes read/write here.' },
      { service: 'redis_cache',      name: 'Redis',           envVar: 'REDIS_URL',           testUrl: null,                                         rateLimit: null, notes: 'In-memory cache L2 layer.' },
      { service: 'anthropic_claude', name: 'Anthropic Claude',envVar: 'ANTHROPIC_API_KEY',   testUrl: null,                                         rateLimit: 50,   notes: 'Claude Sonnet for AI news analysis.' },
      { service: 'telegram_bot',     name: 'Telegram Bot',    envVar: 'TELEGRAM_BOT_TOKEN',  testUrl: null,                                         rateLimit: null, notes: 'Alerts: regime change, circuit breaker, large trades.' },
    ],
    singapore: [
      { service: 'binance_spot',     name: 'Binance Spot',    envVar: 'BINANCE_API_KEY',     testUrl: 'https://api.binance.com/api/v3/ping',        rateLimit: 1200, notes: 'Primary crypto CEX. BTC/ETH/altcoins spot + futures.' },
      { service: 'binance_futures',  name: 'Binance Futures', envVar: 'BINANCE_API_KEY',     testUrl: 'https://fapi.binance.com/fapi/v1/ping',      rateLimit: 1200, notes: 'Perpetual futures.' },
      { service: 'binance_ws',       name: 'Binance WS',      envVar: 'BINANCE_API_KEY',     testUrl: null,                                         rateLimit: null, notes: 'Real-time price feed WebSocket.' },
      { service: 'bybit_spot',       name: 'Bybit',           envVar: 'BYBIT_API_KEY',       testUrl: 'https://api.bybit.com/v5/market/time',       rateLimit: 600,  notes: 'Perps, funding rate harvest, launchpool.' },
      { service: 'okx_spot',         name: 'OKX',             envVar: 'OKX_API_KEY',         testUrl: null,                                         rateLimit: 300,  notes: 'Cross-exchange arb target.' },
      { service: 'kucoin_spot',      name: 'KuCoin',          envVar: 'KUCOIN_API_KEY',      testUrl: null,                                         rateLimit: 300,  notes: 'Listing front-run target, altcoins.' },
      { service: 'mexc_spot',        name: 'MEXC',            envVar: 'MEXC_API_KEY',        testUrl: null,                                         rateLimit: 500,  notes: 'New listing arb, low fees.' },
      { service: 'deribit',          name: 'Deribit',         envVar: 'DERIBIT_API_KEY',     testUrl: null,                                         rateLimit: 100,  notes: 'Crypto options — put-call parity.' },
      { service: 'twitter_x',       name: 'Twitter/X',       envVar: 'TWITTER_BEARER_TOKEN',testUrl: null,                                         rateLimit: 300,  notes: 'Listing announcements. Sentiment.' },
    ],
    mumbai: [
      { service: 'zerodha_kite',     name: 'Zerodha Kite',    envVar: 'ZERODHA_API_KEY',     testUrl: null,                                         rateLimit: 300,  notes: 'NSE/BSE. Required for Indian stocks. ₹2,000/mo.' },
      { service: 'zerodha_ws',       name: 'Zerodha WS',      envVar: 'ZERODHA_API_KEY',     testUrl: null,                                         rateLimit: null, notes: 'Live market data. Access token expires daily.' },
      { service: 'coindcx',          name: 'CoinDCX',         envVar: 'COINDCX_API_KEY',     testUrl: null,                                         rateLimit: 200,  notes: 'India FIU-registered crypto. INR lag arb target.' },
    ],
    useast: [
      { service: 'alchemy_solana',   name: 'Alchemy Solana',  envVar: 'ALCHEMY_API_KEY',     testUrl: null,                                         rateLimit: null, notes: 'Solana RPC + whale wallet tracking.' },
      { service: 'alchemy_eth',      name: 'Alchemy ETH',     envVar: 'ALCHEMY_API_KEY',     testUrl: null,                                         rateLimit: null, notes: 'Ethereum RPC for ETH DeFi.' },
      { service: 'helius_solana',    name: 'Helius',          envVar: 'HELIUS_API_KEY',      testUrl: null,                                         rateLimit: null, notes: 'Solana mempool, new token launches.' },
      { service: 'quicknode_sol',    name: 'QuickNode',       envVar: 'QUICKNODE_API_KEY',   testUrl: null,                                         rateLimit: null, notes: 'Fast Solana RPC alternative.' },
      { service: 'jito_mainnet',     name: 'JITO Bundles',    envVar: 'JITO_AUTH_KEY',       testUrl: null,                                         rateLimit: null, notes: 'Priority block inclusion. Flash loans.' },
      { service: 'solana_wallet',    name: 'Solana Wallet',   envVar: 'SOLANA_PRIVATE_KEY',  testUrl: null,                                         rateLimit: null, notes: 'NEVER commit. Use env injection only.' },
    ],
    data: [
      { service: 'newsapi',          name: 'NewsAPI',         envVar: 'NEWSAPI_KEY',         testUrl: null,                                         rateLimit: 100,  notes: 'News for AI crypto analysis.' },
      { service: 'coinglass',        name: 'Coinglass',       envVar: 'COINGLASS_API_KEY',   testUrl: null,                                         rateLimit: 60,   notes: 'Liquidation cluster data for cascade bot.' },
      { service: 'dune_analytics',   name: 'Dune Analytics',  envVar: 'DUNE_API_KEY',        testUrl: null,                                         rateLimit: 60,   notes: 'On-chain analytics, whale leaderboards.' },
      { service: 'reddit_api',       name: 'Reddit',          envVar: 'REDDIT_CLIENT_ID',    testUrl: null,                                         rateLimit: 100,  notes: 'Social sentiment lead indicator.' },
      { service: 'metaculus_signal', name: 'Metaculus',       envVar: 'METACULUS_API_KEY',   testUrl: null,                                         rateLimit: 60,   notes: 'Expert forecaster consensus signal.' },
      { service: 'birdeye_sol',      name: 'Birdeye',         envVar: 'BIRDEYE_API_KEY',     testUrl: null,                                         rateLimit: 300,  notes: 'Solana token prices, new launches.' },
      { service: 'gdelt_news',       name: 'GDELT',           envVar: null,                  testUrl: 'https://api.gdeltproject.org/api/v2/doc/doc?query=test&mode=artlist&maxrecords=1&format=json', rateLimit: null, notes: 'Free global news. 15-min lead.' },
      { service: 'espn_sports',      name: 'ESPN',            envVar: null,                  testUrl: 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard', rateLimit: null, notes: 'Free sports scores.' },
      { service: 'fear_greed_api',   name: 'Fear/Greed',      envVar: null,                  testUrl: 'https://api.alternative.me/fng/',            rateLimit: null, notes: 'Free Fear/Greed index. Daily signal.' },
      { service: 'magic_eden',       name: 'Magic Eden',      envVar: null,                  testUrl: null,                                         rateLimit: 300,  notes: 'Solana NFT floor prices.' },
      { service: 'defilama',         name: 'DefiLlama',       envVar: null,                  testUrl: 'https://api.llama.fi/protocols',             rateLimit: null, notes: 'DeFi TVL changes. Protocol monitoring.' },
    ],
  }
}
