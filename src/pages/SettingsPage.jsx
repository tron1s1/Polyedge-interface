import { useState, useEffect, useCallback, useRef } from 'react'
import { useTheme } from '../context/ThemeContext'
import { cn } from '../utils/formatters'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import {
  Eye, EyeOff, Wifi, WifiOff, RefreshCw, Check, X,
  Moon, Sun, Download, Upload, Trash2, AlertTriangle,
  Server, Globe, Database, Shield, ChevronDown, ChevronRight,
  Info, ExternalLink
} from 'lucide-react'

// ── localStorage helpers ─────────────────────────────────────────────────────

const STORAGE_KEY = 'alphanode-settings'

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveSettings(s) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
}

function getVal(key, fallback = '') {
  return loadSettings()[key] ?? fallback
}

function setVal(key, val) {
  const s = loadSettings()
  s[key] = val
  saveSettings(s)
}

// ── Reusable Components ──────────────────────────────────────────────────────

function SectionCard({ title, subtitle, icon: Icon, children, className }) {
  return (
    <div className={cn('border border-[var(--color-border)] bg-[var(--color-card)] p-5', className)}>
      <div className="flex items-center gap-2 mb-4">
        {Icon && <Icon size={14} className="text-[var(--color-muted-foreground)]" />}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
            {title}
          </div>
          {subtitle && (
            <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">{subtitle}</div>
          )}
        </div>
      </div>
      {children}
    </div>
  )
}

function SettingRow({ label, mono: isMono, children }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--color-border)] last:border-0">
      <span className={cn(
        'text-[11px] text-[var(--color-muted-foreground)]',
        isMono && 'font-mono text-[10px]'
      )}>
        {label}
      </span>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}

function ApiKeyInput({ label, storageKey, placeholder, warning }) {
  const [show, setShow] = useState(false)
  const [value, setValue] = useState(() => getVal(storageKey, ''))
  const [flash, setFlash] = useState(false)
  const timeoutRef = useRef(null)

  const handleChange = useCallback((e) => {
    const v = e.target.value
    setValue(v)
    setVal(storageKey, v)
    setFlash(true)
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setFlash(false), 1200)
  }, [storageKey])

  useEffect(() => {
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [])

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--color-border)] last:border-0 gap-4">
      <div className="flex items-center gap-2 min-w-0 shrink-0">
        <span className="text-[11px] text-[var(--color-muted-foreground)] whitespace-nowrap">{label}</span>
        {warning && (
          <span className="flex items-center gap-1 text-[9px] text-red-400 whitespace-nowrap">
            <AlertTriangle size={10} className="text-red-400 shrink-0" />
            {warning}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type={show ? 'text' : 'password'}
          placeholder={placeholder || ''}
          value={value}
          onChange={handleChange}
          spellCheck={false}
          autoComplete="off"
          className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] font-mono w-72 text-[var(--color-foreground)] outline-none focus:border-[var(--color-accent)] transition-colors"
        />
        <button
          onClick={() => setShow(s => !s)}
          className="p-1 text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors"
          title={show ? 'Hide' : 'Show'}
        >
          {show ? <EyeOff size={13} /> : <Eye size={13} />}
        </button>
        {flash && (
          <Check size={13} className="text-emerald-500 animate-pulse" />
        )}
        {value && !flash && (
          <span
            className="w-2 h-2 rounded-full bg-emerald-500 shrink-0"
            title="Value saved"
          />
        )}
        {!value && !flash && (
          <span className="w-2 h-2 rounded-full bg-[var(--color-border)] shrink-0" />
        )}
      </div>
    </div>
  )
}

function DisplayRow({ label, value, mono: isMono }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--color-border)] last:border-0">
      <span className="text-[11px] text-[var(--color-muted-foreground)]">{label}</span>
      <span className={cn(
        'text-[11px] text-[var(--color-foreground)]',
        isMono && 'font-mono text-[10px]'
      )}>
        {value}
      </span>
    </div>
  )
}

function NoteBox({ children, variant = 'info' }) {
  const colors = {
    info: 'border-[var(--color-border)] text-[var(--color-muted-foreground)]',
    warn: 'border-amber-500/30 text-amber-400',
    danger: 'border-red-500/30 text-red-400',
    success: 'border-emerald-500/30 text-emerald-400',
  }
  return (
    <div className={cn('mt-3 px-3 py-2 border text-[10px] leading-relaxed', colors[variant])}>
      {children}
    </div>
  )
}

// ── Test Connection Row (live from /api/config/apis) ─────────────────────────

function ConnectionTestRow({ apiItem }) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)

  const hasKey = apiItem.is_connected || apiItem.has_key !== false

  const handleTest = async () => {
    setTesting(true)
    setResult(null)

    if (apiItem.test_url || apiItem.base_url) {
      const start = performance.now()
      try {
        const resp = await fetch(apiItem.test_url || apiItem.base_url, {
          method: 'GET',
          mode: 'cors',
          signal: AbortSignal.timeout(8000),
        })
        const latency = Math.round(performance.now() - start)
        setResult({ status: resp.ok ? 'pass' : 'fail', latency })
      } catch {
        const latency = Math.round(performance.now() - start)
        setResult({ status: 'cors', latency })
      }
    } else {
      await new Promise(r => setTimeout(r, 600))
      setResult({ status: hasKey ? 'configured' : 'no_key', latency: null })
    }
    setTesting(false)
  }

  const statusColor =
    result?.status === 'pass' ? '#1D9E75' :
    result?.status === 'fail' || result?.status === 'no_key' ? '#E24B4A' :
    result?.status === 'cors' ? '#EF9F27' :
    result?.status === 'configured' ? '#1D9E75' :
    'var(--color-muted-foreground)'

  const statusLabel =
    result?.status === 'pass' ? 'Pass' :
    result?.status === 'fail' ? 'Fail' :
    result?.status === 'cors' ? 'CORS' :
    result?.status === 'configured' ? 'Key saved' :
    result?.status === 'no_key' ? 'No key' :
    null

  return (
    <tr className="border-b border-[var(--color-border)] last:border-0">
      <td className="py-2 px-3">
        <span
          className="w-2 h-2 inline-block rounded-full"
          style={{ backgroundColor: hasKey ? '#1D9E75' : '#E24B4A' }}
        />
      </td>
      <td className="py-2 px-3">
        <div className="text-[11px] font-medium text-[var(--color-foreground)]">{apiItem.name || apiItem.service?.replace(/_/g, ' ')}</div>
        <div className="text-[9px] text-[var(--color-muted-foreground)]">{apiItem.notes || ''}</div>
      </td>
      <td className="py-2 px-3">
        {(apiItem.env_var || apiItem.api_key_env_var) ? (
          <span className="font-mono text-[10px] px-1.5 py-0.5 bg-[var(--color-muted)] border border-[var(--color-border)]">
            {apiItem.env_var || apiItem.api_key_env_var}
          </span>
        ) : (
          <span className="text-[10px] text-[var(--color-muted-foreground)]">none (free)</span>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-[10px] text-center text-[var(--color-muted-foreground)]">
        {(apiItem.rate_limit || apiItem.rate_limit_per_min) ? `${apiItem.rate_limit || apiItem.rate_limit_per_min}/min` : '\u2014'}
      </td>
      <td className="py-2 px-3">
        {statusLabel && (
          <span className="text-[10px] font-medium" style={{ color: statusColor }}>
            {statusLabel}
            {result?.latency != null && result.status === 'pass' && (
              <span className="font-mono text-[9px] text-[var(--color-muted-foreground)] ml-1">
                ({result.latency}ms)
              </span>
            )}
          </span>
        )}
      </td>
      <td className="py-2 px-3">
        <button
          onClick={handleTest}
          disabled={testing}
          className="flex items-center gap-1 px-2.5 py-1 text-[10px] font-medium border border-[var(--color-border)] hover:bg-[var(--color-muted)] disabled:opacity-50 transition-colors"
        >
          {testing ? (
            <><RefreshCw size={10} className="animate-spin" /> Testing</>
          ) : (
            <><Wifi size={10} /> Test</>
          )}
        </button>
      </td>
    </tr>
  )
}

function ConnectionTestTable({ apis, label }) {
  if (!apis || apis.length === 0) return null
  return (
    <div className="mt-4 pt-3 border-t border-[var(--color-border)]">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">
        {label || 'Test Connections'}
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[var(--color-border)]">
            {['', 'Service', 'Env Var', 'Rate Limit', 'Status', ''].map((h, i) => (
              <th key={i} className="text-left py-1.5 px-3 text-[9px] uppercase text-[var(--color-muted-foreground)] font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {apis.map(a => (
            <ConnectionTestRow key={a.service || a.name} apiItem={a} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main Settings Page ───────────────────────────────────────────────────────

export default function SettingsPage() {
  const { theme, toggleTheme } = useTheme()

  // Load API connections from backend
  const { data: apiConfigData } = usePolling(useCallback(() => api.getApiConfig(), []), 60000)
  const apiConnections = apiConfigData?.apis || []

  // Group by service name prefix
  const infraServices = ['supabase', 'redis', 'telegram']
  const sgServices = ['binance', 'bybit', 'okx', 'kucoin', 'mexc', 'deribit']
  const mumbaiServices = ['zerodha', 'coindcx']
  const useastServices = ['alchemy', 'helius', 'quicknode', 'jito', 'solana']

  const matchGroup = (svc, prefixes) => prefixes.some(p => svc.toLowerCase().startsWith(p))
  const infraApis = apiConnections.filter(a => matchGroup(a.service, infraServices))
  const singaporeApis = apiConnections.filter(a => matchGroup(a.service, sgServices))
  const mumbaiApis = apiConnections.filter(a => matchGroup(a.service, mumbaiServices))
  const useastApis = apiConnections.filter(a => matchGroup(a.service, useastServices))
  const dataApis = apiConnections.filter(a =>
    !matchGroup(a.service, [...infraServices, ...sgServices, ...mumbaiServices, ...useastServices])
  )

  // General settings with persistence
  const [timezone, setTimezone] = useState(() => getVal('timezone', 'UTC+5:30'))
  const [currency, setCurrency] = useState(() => getVal('currency', 'USD'))
  const [dashboardPort, setDashboardPort] = useState(() => getVal('dashboard_port', '5173'))

  const persist = (key, value, setter) => {
    setter(value)
    setVal(key, value)
  }

  // Tax settings
  const [dubaiTarget, setDubaiTarget] = useState(() => getVal('tax_dubai_target', '50000'))

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <h1 className="text-[18px] font-semibold text-[var(--color-foreground)]">Settings</h1>
      <p className="text-[11px] text-[var(--color-muted-foreground)] -mt-3">
        Multi-node crypto trading infrastructure configuration. All values persist to localStorage.
      </p>

      {/* GENERAL */}
      <SectionCard title="General" icon={Globe}>
        <SettingRow label="Theme">
          <button
            onClick={toggleTheme}
            className="flex items-center gap-2 px-3 py-1.5 text-[11px] border border-[var(--color-border)] bg-[var(--color-muted)] font-medium hover:bg-[var(--color-input-bg)] transition-colors"
          >
            {theme === 'dark' ? <Moon size={12} /> : <Sun size={12} />}
            {theme === 'dark' ? 'Dark' : 'Light'}
          </button>
        </SettingRow>
        <SettingRow label="Timezone">
          <select
            value={timezone}
            onChange={e => persist('timezone', e.target.value, setTimezone)}
            className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-foreground)] outline-none"
          >
            <option value="UTC">UTC</option>
            <option value="UTC+5:30">UTC+5:30 (IST)</option>
            <option value="UTC+8">UTC+8 (SGT)</option>
            <option value="UTC-5">UTC-5 (EST)</option>
            <option value="UTC-4">UTC-4 (EDT)</option>
            <option value="UTC-8">UTC-8 (PST)</option>
            <option value="UTC+1">UTC+1 (CET)</option>
            <option value="UTC+9">UTC+9 (JST)</option>
            <option value="UTC+0">UTC+0 (GMT)</option>
          </select>
        </SettingRow>
        <SettingRow label="Currency Display">
          <select
            value={currency}
            onChange={e => persist('currency', e.target.value, setCurrency)}
            className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-foreground)] outline-none"
          >
            <option value="USD">USD ($)</option>
            <option value="INR">INR (&#8377;)</option>
            <option value="EUR">EUR (&euro;)</option>
            <option value="GBP">GBP (&pound;)</option>
            <option value="USDT">USDT</option>
            <option value="BTC">BTC (&#8383;)</option>
          </select>
        </SettingRow>
        <SettingRow label="Dashboard Port">
          <input
            type="text"
            value={dashboardPort}
            onChange={e => persist('dashboard_port', e.target.value, setDashboardPort)}
            className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] font-mono w-24 text-[var(--color-foreground)] text-right outline-none"
          />
        </SettingRow>
      </SectionCard>

      {/* INFRASTRUCTURE */}
      <SectionCard title="Infrastructure" subtitle="Core services shared across all nodes" icon={Server}>
        <ApiKeyInput label="Supabase URL" storageKey="api_SUPABASE_URL" placeholder="https://xxx.supabase.co" />
        <ApiKeyInput label="Redis URL" storageKey="api_REDIS_URL" placeholder="redis://localhost:6379" />
        <ApiKeyInput label="Anthropic API Key" storageKey="api_ANTHROPIC_API_KEY" placeholder="sk-ant-..." />
        <ApiKeyInput label="Telegram Bot Token" storageKey="api_TELEGRAM_BOT_TOKEN" placeholder="123456:ABC-DEF..." />
        <ApiKeyInput label="Telegram Chat ID" storageKey="api_TELEGRAM_CHAT_ID" placeholder="-100..." />

        <ConnectionTestTable apis={infraApis} label="Infrastructure Connections" />
      </SectionCard>

      {/* NODE 1: SINGAPORE */}
      <SectionCard
        title="Node 1 — Singapore"
        subtitle="Crypto CEX trading — Binance, Bybit, OKX, KuCoin, MEXC, Deribit"
        icon={Globe}
      >
        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-1 mb-1 tracking-wider">Binance</div>
        <ApiKeyInput label="Binance API Key" storageKey="api_BINANCE_API_KEY" placeholder="binance api key" />
        <ApiKeyInput label="Binance API Secret" storageKey="api_BINANCE_API_SECRET" placeholder="binance secret" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">Bybit</div>
        <ApiKeyInput label="Bybit API Key" storageKey="api_BYBIT_API_KEY" placeholder="bybit api key" />
        <ApiKeyInput label="Bybit API Secret" storageKey="api_BYBIT_API_SECRET" placeholder="bybit secret" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">OKX</div>
        <ApiKeyInput label="OKX API Key" storageKey="api_OKX_API_KEY" placeholder="okx api key" />
        <ApiKeyInput label="OKX API Secret" storageKey="api_OKX_API_SECRET" placeholder="okx secret" />
        <ApiKeyInput label="OKX Passphrase" storageKey="api_OKX_PASSPHRASE" placeholder="okx passphrase" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">KuCoin</div>
        <ApiKeyInput label="KuCoin API Key" storageKey="api_KUCOIN_API_KEY" placeholder="kucoin api key" />
        <ApiKeyInput label="KuCoin API Secret" storageKey="api_KUCOIN_API_SECRET" placeholder="kucoin secret" />
        <ApiKeyInput label="KuCoin Passphrase" storageKey="api_KUCOIN_PASSPHRASE" placeholder="kucoin passphrase" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">MEXC</div>
        <ApiKeyInput label="MEXC API Key" storageKey="api_MEXC_API_KEY" placeholder="mexc api key" />
        <ApiKeyInput label="MEXC API Secret" storageKey="api_MEXC_API_SECRET" placeholder="mexc secret" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">Social</div>
        <ApiKeyInput label="Twitter Bearer Token" storageKey="api_TWITTER_BEARER_TOKEN" placeholder="AAAA..." />

        <ConnectionTestTable apis={singaporeApis} label="Singapore Node Connections" />
      </SectionCard>

      {/* NODE 2: MUMBAI */}
      <SectionCard
        title="Node 2 — Mumbai"
        subtitle="India equities (NSE/BSE) + INR crypto on-ramp"
        icon={Globe}
      >
        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-1 mb-1 tracking-wider">Zerodha Kite</div>
        <ApiKeyInput label="Zerodha API Key" storageKey="api_ZERODHA_API_KEY" placeholder="zerodha api key" />
        <ApiKeyInput label="Zerodha API Secret" storageKey="api_ZERODHA_API_SECRET" placeholder="zerodha secret" />
        <ApiKeyInput label="Zerodha Access Token" storageKey="api_ZERODHA_ACCESS_TOKEN" placeholder="expires daily" />

        <div className="text-[10px] font-semibold uppercase text-[var(--color-muted-foreground)] mt-3 mb-1 tracking-wider">CoinDCX</div>
        <ApiKeyInput label="CoinDCX API Key" storageKey="api_COINDCX_API_KEY" placeholder="coindcx api key" />
        <ApiKeyInput label="CoinDCX API Secret" storageKey="api_COINDCX_API_SECRET" placeholder="coindcx secret" />

        <NoteBox variant="warn">
          Zerodha access token expires daily &mdash; dashboard auto-reminds at market open (09:15 IST). Re-generate via Kite login flow.
        </NoteBox>

        <ConnectionTestTable apis={mumbaiApis} label="Mumbai Node Connections" />
      </SectionCard>

      {/* NODE 3: US EAST */}
      <SectionCard
        title="Node 3 — US East"
        subtitle="Solana DeFi, mempool sniping, JITO bundles, whale tracking"
        icon={Globe}
      >
        <ApiKeyInput label="Alchemy API Key" storageKey="api_ALCHEMY_API_KEY" placeholder="alchemy api key" />
        <ApiKeyInput label="Helius API Key" storageKey="api_HELIUS_API_KEY" placeholder="helius api key" />
        <ApiKeyInput label="QuickNode API Key" storageKey="api_QUICKNODE_API_KEY" placeholder="quicknode endpoint" />
        <ApiKeyInput label="JITO Auth Key" storageKey="api_JITO_AUTH_KEY" placeholder="jito auth key" />
        <ApiKeyInput
          label="Solana Wallet Private Key"
          storageKey="api_SOLANA_PRIVATE_KEY"
          placeholder="base58 private key"
          warning="STORE SAFELY — NEVER COMMIT"
        />

        <ConnectionTestTable apis={useastApis} label="US East Node Connections" />
      </SectionCard>

      {/* DATA & INTELLIGENCE */}
      <SectionCard
        title="Data & Intelligence"
        subtitle="News feeds, on-chain analytics, social sentiment"
        icon={Database}
      >
        <ApiKeyInput label="NewsAPI Key" storageKey="api_NEWSAPI_KEY" placeholder="newsapi key" />
        <ApiKeyInput label="Coinglass API Key" storageKey="api_COINGLASS_API_KEY" placeholder="coinglass key" />
        <ApiKeyInput label="Dune Analytics API Key" storageKey="api_DUNE_API_KEY" placeholder="dune api key" />
        <ApiKeyInput label="Reddit Client ID" storageKey="api_REDDIT_CLIENT_ID" placeholder="reddit client id" />
        <ApiKeyInput label="Reddit Client Secret" storageKey="api_REDDIT_CLIENT_SECRET" placeholder="reddit secret" />
        <ApiKeyInput label="Metaculus API Key" storageKey="api_METACULUS_API_KEY" placeholder="metaculus key" />
        <ApiKeyInput label="Birdeye API Key" storageKey="api_BIRDEYE_API_KEY" placeholder="birdeye key" />

        <div className="mt-4 pt-3 border-t border-[var(--color-border)]">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">
            Free APIs &mdash; No Key Required
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1">
            {[
              { name: 'ESPN', note: 'Sports scores' },
              { name: 'GDELT', note: 'Global news feed' },
              { name: 'Magic Eden', note: 'Solana NFT floors' },
              { name: 'Fear/Greed Index', note: 'Daily sentiment' },
              { name: 'DefiLlama', note: 'DeFi TVL data' },
            ].map(item => (
              <div key={item.name} className="flex items-center gap-2 py-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                <span className="text-[11px] text-[var(--color-foreground)]">{item.name}</span>
                <span className="text-[9px] text-[var(--color-muted-foreground)]">{item.note}</span>
              </div>
            ))}
          </div>
        </div>

        <ConnectionTestTable apis={dataApis} label="Data Source Connections" />
      </SectionCard>

      {/* INDIA TAX CONFIGURATION */}
      <SectionCard
        title="India Tax Configuration"
        subtitle="Crypto tax rules under Indian IT Act, Section 115BBH"
        icon={Shield}
      >
        <DisplayRow label="Crypto Tax Rate" value="30% (flat, no deductions)" />
        <DisplayRow label="TDS on Transfers" value="1% (Section 194S)" />
        <DisplayRow label="FIU-Registered Exchanges" value="CoinDCX, WazirX" />

        <div className="mt-3 pt-2 border-t border-[var(--color-border)]">
          <ApiKeyInput
            label="CA Email (for tax reports)"
            storageKey="tax_ca_email"
            placeholder="ca@example.com"
          />
          <SettingRow label="Dubai Milestone Target (USDC)">
            <input
              type="number"
              value={dubaiTarget}
              onChange={e => persist('tax_dubai_target', e.target.value, setDubaiTarget)}
              className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] font-mono w-32 text-[var(--color-foreground)] text-right outline-none"
            />
          </SettingRow>
        </div>
      </SectionCard>

      {/* DATA MANAGEMENT */}
      <SectionCard title="Data Management" icon={Database}>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => {
              const data = loadSettings()
              const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `alphanode-settings-${new Date().toISOString().slice(0, 10)}.json`
              a.click()
              URL.revokeObjectURL(url)
            }}
            className="flex items-center gap-2 px-4 py-2 text-[11px] font-medium border border-[var(--color-border)] hover:bg-[var(--color-muted)] transition-colors"
          >
            <Download size={12} />
            Export Settings JSON
          </button>

          <button
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.json'
              input.onchange = (e) => {
                const file = e.target.files?.[0]
                if (!file) return
                const reader = new FileReader()
                reader.onload = (ev) => {
                  try {
                    const data = JSON.parse(ev.target.result)
                    if (typeof data !== 'object' || Array.isArray(data)) {
                      alert('Invalid settings file: expected a JSON object.')
                      return
                    }
                    saveSettings(data)
                    window.location.reload()
                  } catch {
                    alert('Invalid JSON file')
                  }
                }
                reader.readAsText(file)
              }
              input.click()
            }}
            className="flex items-center gap-2 px-4 py-2 text-[11px] font-medium border border-[var(--color-border)] hover:bg-[var(--color-muted)] transition-colors"
          >
            <Upload size={12} />
            Import Settings
          </button>

          <button
            onClick={() => {
              if (confirm('Reset ALL settings? All API keys and preferences will be cleared.')) {
                localStorage.removeItem(STORAGE_KEY)
                window.location.reload()
              }
            }}
            className="flex items-center gap-2 px-4 py-2 text-[11px] font-medium border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <Trash2 size={12} />
            Reset All Settings
          </button>
        </div>

        <NoteBox>
          Settings are stored in browser localStorage under the key <span className="font-mono">alphanode-settings</span>.
          They are never sent to any server. The backend reads credentials from <span className="font-mono">.env</span> files on each node.
        </NoteBox>
      </SectionCard>
    </div>
  )
}
