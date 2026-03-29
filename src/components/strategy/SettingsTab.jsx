import { useState } from 'react'
import { Save, ChevronDown, ChevronUp } from 'lucide-react'

function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between px-4 py-3">
        <span className="text-[12px] font-medium uppercase tracking-wider">{title}</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && <div className="px-4 pb-4 space-y-3">{children}</div>}
    </div>
  )
}

function SliderParam({ label, value, min, max, step = 1, unit = '', onChange }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11px] text-[var(--color-muted-foreground)] w-40 shrink-0">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} className="flex-1 h-1 accent-[var(--color-accent)]" />
      <span className="mono text-[12px] font-medium w-16 text-right">{value}{unit}</span>
    </div>
  )
}

function ToggleParam({ label, value, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-[var(--color-muted-foreground)]">{label}</span>
      <button onClick={() => onChange(!value)} className={`w-9 h-5 relative transition-colors ${value ? 'bg-[#1D9E75]' : 'bg-[var(--color-muted)]'}`}>
        <div className="absolute top-0.5 w-4 h-4 bg-white transition-all" style={{ left: value ? '18px' : '2px' }} />
      </button>
    </div>
  )
}

export default function SettingsTab({ strategyId }) {
  const [settings, setSettings] = useState({
    gapThreshold: 20, oracleStaleness: 90, flashCrashGuard: true, flashCrashThreshold: 2,
    minSumGap: 4, minProfit: 10, scanInterval: 60,
    minEdge: 15, minConfidence: 65, promptTTL: 5,
    minSpread: 2, orderSize: 200, maxImbalance: 3,
    kellyMultiplier: 25, maxPositionSize: 500, maxDailyExposure: 2000,
    maxSlippage: 3, consecutiveLossPause: 3, pauseDuration: 30, dailyLossCap: 15,
    asyncParallel: true, redisCache: true, webSocket: true, connectionPool: true, deltaProcessing: true, priorityQueue: true,
  })

  const set = (key) => (val) => setSettings(s => ({ ...s, [key]: val }))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-medium">Strategy Configuration</div>
        <button className="flex items-center gap-2 px-4 py-2 bg-[var(--color-accent)] text-white text-[12px] font-medium hover:opacity-90">
          <Save size={14} /> Save as New Version
        </button>
      </div>

      {/* Signal detection */}
      {strategyId === 'latency-arb' && (
        <Section title="Signal Detection — Latency Arb">
          <SliderParam label="Min Gap Threshold" value={settings.gapThreshold} min={5} max={50} unit="%" onChange={set('gapThreshold')} />
          <SliderParam label="Oracle Staleness Min" value={settings.oracleStaleness} min={30} max={300} step={10} unit="s" onChange={set('oracleStaleness')} />
          <ToggleParam label="Flash Crash Guard" value={settings.flashCrashGuard} onChange={set('flashCrashGuard')} />
          {settings.flashCrashGuard && (
            <SliderParam label="Flash Crash Threshold" value={settings.flashCrashThreshold} min={1} max={10} unit="%" onChange={set('flashCrashThreshold')} />
          )}
        </Section>
      )}

      {strategyId === 'negrisk-arb' && (
        <Section title="Signal Detection — NegRisk Arb">
          <SliderParam label="Min Sum Gap" value={settings.minSumGap} min={1} max={20} unit="%" onChange={set('minSumGap')} />
          <SliderParam label="Min Profit Threshold" value={settings.minProfit} min={5} max={100} unit="$" onChange={set('minProfit')} />
          <SliderParam label="Scan Interval" value={settings.scanInterval} min={15} max={120} step={5} unit="s" onChange={set('scanInterval')} />
        </Section>
      )}

      {strategyId === 'ai-news' && (
        <Section title="Signal Detection — AI News">
          <SliderParam label="Min Edge Threshold" value={settings.minEdge} min={5} max={30} unit="%" onChange={set('minEdge')} />
          <SliderParam label="Min AI Confidence" value={settings.minConfidence} min={50} max={95} unit="%" onChange={set('minConfidence')} />
          <SliderParam label="Stale Prompt TTL" value={settings.promptTTL} min={1} max={15} unit="min" onChange={set('promptTTL')} />
        </Section>
      )}

      {strategyId === 'market-making' && (
        <Section title="Signal Detection — Market Making">
          <SliderParam label="Min Spread" value={settings.minSpread} min={1} max={10} unit="¢" onChange={set('minSpread')} />
          <SliderParam label="Order Size per Side" value={settings.orderSize} min={50} max={1000} step={50} unit="$" onChange={set('orderSize')} />
          <SliderParam label="Max Inventory Imbalance" value={settings.maxImbalance} min={2} max={10} unit="x" onChange={set('maxImbalance')} />
        </Section>
      )}

      {/* Position Sizing */}
      <Section title="Position Sizing / Kelly Criterion">
        <SliderParam label="Kelly Multiplier" value={settings.kellyMultiplier} min={10} max={100} step={5} unit="%" onChange={set('kellyMultiplier')} />
        <SliderParam label="Max Position Size" value={settings.maxPositionSize} min={50} max={5000} step={50} unit="$" onChange={set('maxPositionSize')} />
        <SliderParam label="Max Daily Exposure" value={settings.maxDailyExposure} min={100} max={10000} step={100} unit="$" onChange={set('maxDailyExposure')} />
      </Section>

      {/* Risk Management */}
      <Section title="Risk Management / Kill Switch">
        <SliderParam label="Max Slippage" value={settings.maxSlippage} min={1} max={10} unit="¢" onChange={set('maxSlippage')} />
        <SliderParam label="Consecutive Loss Pause" value={settings.consecutiveLossPause} min={1} max={10} onChange={set('consecutiveLossPause')} />
        <SliderParam label="Pause Duration" value={settings.pauseDuration} min={10} max={120} step={10} unit="min" onChange={set('pauseDuration')} />
        <SliderParam label="Daily Loss Cap" value={settings.dailyLossCap} min={5} max={50} unit="%" onChange={set('dailyLossCap')} />
      </Section>

      {/* Base Latency Layer */}
      <Section title="Base Latency Layer" defaultOpen={false}>
        <ToggleParam label="B1 — Async Parallel Processing" value={settings.asyncParallel} onChange={set('asyncParallel')} />
        <ToggleParam label="B2 — Redis In-Memory Cache" value={settings.redisCache} onChange={set('redisCache')} />
        <ToggleParam label="B3 — WebSocket over REST" value={settings.webSocket} onChange={set('webSocket')} />
        <ToggleParam label="B4 — Connection Pooling" value={settings.connectionPool} onChange={set('connectionPool')} />
        <ToggleParam label="B5 — Delta-Only Processing" value={settings.deltaProcessing} onChange={set('deltaProcessing')} />
        <ToggleParam label="B6 — Priority Queue Routing" value={settings.priorityQueue} onChange={set('priorityQueue')} />
      </Section>
    </div>
  )
}
