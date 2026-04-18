import { useState, useEffect, useCallback } from 'react'
import { api } from '../../lib/api'
import { Activity, TrendingUp, TrendingDown, AlertTriangle, Clock, Zap, Power, Target } from 'lucide-react'

// Plain text, high-density panel matching the existing dashboard aesthetic.
// Consumes /api/strategies/<id>/execution-reality + /live-test/status.
export default function ExecutionRealityTab({ strategyId = 'A_M1_triangular_arb' }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [liveState, setLiveState] = useState(null)
  const [busy, setBusy] = useState(false)
  const [sizeInput, setSizeInput] = useState('10')
  const [lastError, setLastError] = useState(null)

  const refreshLive = useCallback(async () => {
    const res = await api.getLiveTestStatus(strategyId)
    setLiveState(res)
  }, [strategyId])

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      const res = await api.getExecutionReality(strategyId, 500)
      if (mounted) {
        setData(res)
        setLoading(false)
      }
      const live = await api.getLiveTestStatus(strategyId)
      if (mounted) setLiveState(live)
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { mounted = false; clearInterval(id) }
  }, [strategyId])

  const doArm = async (count) => {
    setBusy(true); setLastError(null)
    const size = parseFloat(sizeInput) || 10
    const res = await api.armLiveTest(strategyId, count, size)
    if (res?.error) setLastError(res.detail || 'arm failed')
    else setLiveState(res)
    setBusy(false)
  }

  const doDisarm = async () => {
    setBusy(true); setLastError(null)
    const res = await api.disarmLiveTest(strategyId)
    if (res?.error) setLastError(res.detail || 'disarm failed')
    else setLiveState(res)
    setBusy(false)
  }

  const toggleMaster = async () => {
    setBusy(true); setLastError(null)
    const next = !(liveState?.master_trading_enabled)
    const res = await api.toggleTrading(strategyId, { master_enabled: next })
    if (res?.error) setLastError(res.detail || 'toggle failed')
    else setLiveState(res)
    setBusy(false)
  }

  const toggleDryRun = async () => {
    setBusy(true); setLastError(null)
    const next = !(liveState?.dry_run_enabled)
    const res = await api.toggleTrading(strategyId, { dry_run_enabled: next })
    if (res?.error) setLastError(res.detail || 'toggle failed')
    else setLiveState(res)
    setBusy(false)
  }

  if (loading) return <div className="p-6 text-[11px] text-[var(--color-muted-foreground)]">Loading execution reality…</div>
  if (!data) return <div className="p-6 text-[11px] text-[var(--color-muted-foreground)]">No execution data yet.</div>

  const n = data.sample_size || 0
  if (n === 0) {
    return (
      <div className="p-6 space-y-4">
        <LiveTestControlPanel
          liveState={liveState}
          sizeInput={sizeInput}
          setSizeInput={setSizeInput}
          busy={busy}
          lastError={lastError}
          onArm={doArm}
          onDisarm={doDisarm}
          onToggleMaster={toggleMaster}
          onToggleDryRun={toggleDryRun}
        />
        <div className="flex items-center gap-2 p-3 border border-[var(--color-border)] bg-[var(--color-muted)] rounded">
          <AlertTriangle size={14} className="text-[var(--color-muted-foreground)]" />
          <span className="text-[11px]">
            No rich-schema executions yet. After Approach D is enabled, each paper trade stores slippage, latency, and outcome data here.
          </span>
        </div>
        {data.legacy_rows_excluded > 0 && (
          <div className="text-[10px] text-[var(--color-muted-foreground)]">
            {data.legacy_rows_excluded} legacy pre-Approach-D rows excluded from this view.
          </div>
        )}
      </div>
    )
  }

  const slipMax = Math.max(1, ...data.slippage_histogram.map(b => b.count))

  const headlineColor = (data.winrate_pct ?? 0) >= 95 ? '#1D9E75'
    : (data.winrate_pct ?? 0) >= 85 ? '#D9A62D'
    : '#E24B4A'

  return (
    <div className="space-y-5">
      {/* Live-test control panel */}
      <LiveTestControlPanel
        liveState={liveState}
        sizeInput={sizeInput}
        setSizeInput={setSizeInput}
        busy={busy}
        lastError={lastError}
        onArm={doArm}
        onDisarm={doDisarm}
        onToggleMaster={toggleMaster}
        onToggleDryRun={toggleDryRun}
      />

      {/* Headline */}
      <div className="grid grid-cols-5 gap-3">
        <MetricBox
          label="Winrate"
          value={data.winrate_pct != null ? `${data.winrate_pct}%` : '--'}
          sub={`${data.wins}W / ${data.losses + data.partial_hedged + data.failed}L`}
          color={headlineColor}
        />
        <MetricBox
          label="Sample"
          value={n.toString()}
          sub={`${data.legacy_rows_excluded} legacy excluded`}
        />
        <MetricBox
          label="Mean slip"
          value={data.mean_slippage_bps != null ? `${data.mean_slippage_bps.toFixed(1)} bps` : '--'}
          sub={data.max_slippage_bps != null ? `max ${data.max_slippage_bps.toFixed(1)} bps` : ''}
        />
        <MetricBox
          label="Latency p95"
          value={data.latency_ms_p95 != null ? `${data.latency_ms_p95} ms` : '--'}
          sub={data.latency_ms_p99 != null ? `p99 ${data.latency_ms_p99} ms` : ''}
        />
        <MetricBox
          label="Latency max"
          value={data.latency_ms_max != null ? `${data.latency_ms_max} ms` : '--'}
          sub={data.latency_ms_p50 != null ? `p50 ${data.latency_ms_p50} ms` : ''}
        />
      </div>

      {/* Outcome distribution */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2 font-medium">
          Outcome distribution
        </div>
        <div className="grid grid-cols-5 gap-2">
          {['COMPLETE','PARTIAL_HEDGED','NO_FILL','ABORTED','FAILED'].map(k => {
            const count = data.outcome_distribution?.[k] || 0
            const pct = n ? (count / n * 100).toFixed(1) : '0.0'
            const color = k === 'COMPLETE' ? '#1D9E75'
              : k === 'PARTIAL_HEDGED' ? '#E24B4A'
              : k === 'NO_FILL' ? '#8B8B8B'
              : '#D9A62D'
            return (
              <div key={k} className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
                <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">{k}</div>
                <div className="mono text-[18px] font-medium mt-1" style={{ color }}>{count}</div>
                <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{pct}%</div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Slippage histogram */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2 font-medium">
          Per-leg slippage histogram (bps)
        </div>
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-end gap-1 h-[140px]">
            {data.slippage_histogram.map(b => {
              const h = Math.max(2, (b.count / slipMax) * 130)
              // Negative = price improvement, green. Positive = worse, red.
              const isNeg = b.bucket.startsWith('-') || b.bucket === '-2..0'
              const color = isNeg ? '#1D9E75'
                : b.bucket === '0..2' ? '#7BAE8E'
                : b.bucket === '2..5' ? '#D9A62D'
                : '#E24B4A'
              return (
                <div key={b.bucket} className="flex-1 flex flex-col items-center">
                  <div className="text-[9px] mono text-[var(--color-muted-foreground)] mb-0.5">{b.count}</div>
                  <div style={{ height: `${h}px`, backgroundColor: color, width: '100%' }} />
                  <div className="text-[9px] mono mt-1 text-[var(--color-muted-foreground)]">{b.bucket}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Latency classification */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2 font-medium">
          Latency classification
        </div>
        <div className="grid grid-cols-4 gap-2">
          {['fast','normal','slow','timeout'].map(k => {
            const count = data.latency_classification?.[k] || 0
            const pct = n ? (count / n * 100).toFixed(1) : '0.0'
            const color = k === 'fast' ? '#1D9E75'
              : k === 'normal' ? '#7BAE8E'
              : k === 'slow' ? '#D9A62D'
              : '#E24B4A'
            return (
              <div key={k} className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
                <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  {k} {k === 'fast' && '(<10ms)'}{k === 'normal' && '(<20ms)'}{k === 'slow' && '(<40ms)'}{k === 'timeout' && '(>40ms)'}
                </div>
                <div className="mono text-[18px] font-medium mt-1" style={{ color }}>{count}</div>
                <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{pct}%</div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Per-triangle breakdown */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2 font-medium">
          Per-triangle performance (top {Math.min(data.per_triangle.length, 50)} by frequency)
        </div>
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] overflow-x-auto">
          <table className="w-full text-[10px] mono">
            <thead>
              <tr className="bg-[var(--color-muted)] text-[var(--color-muted-foreground)]">
                <th className="text-left p-2">Triangle</th>
                <th className="text-right p-2">N</th>
                <th className="text-right p-2">W / L</th>
                <th className="text-right p-2">Avg exp %</th>
                <th className="text-right p-2">Avg act %</th>
                <th className="text-right p-2">Edge lost bps</th>
                <th className="text-right p-2">Mean slip bps</th>
                <th className="text-right p-2">Max slip bps</th>
              </tr>
            </thead>
            <tbody>
              {data.per_triangle.map(t => (
                <tr key={t.triangle_id} className="border-t border-[var(--color-border)]">
                  <td className="p-2">{t.triangle_id}</td>
                  <td className="p-2 text-right">{t.count}</td>
                  <td className="p-2 text-right">
                    <span style={{ color: '#1D9E75' }}>{t.wins}</span>
                    <span className="text-[var(--color-muted-foreground)]"> / </span>
                    <span style={{ color: '#E24B4A' }}>{t.losses}</span>
                  </td>
                  <td className="p-2 text-right">{t.avg_expected_pct.toFixed(4)}</td>
                  <td className="p-2 text-right" style={{ color: t.avg_actual_pct >= 0 ? '#1D9E75' : '#E24B4A' }}>
                    {t.avg_actual_pct.toFixed(4)}
                  </td>
                  <td className="p-2 text-right" style={{ color: t.edge_lost_bps > 10 ? '#E24B4A' : 'inherit' }}>
                    {t.edge_lost_bps.toFixed(1)}
                  </td>
                  <td className="p-2 text-right">{t.mean_slip_bps.toFixed(1)}</td>
                  <td className="p-2 text-right" style={{ color: t.max_slip_bps > 20 ? '#E24B4A' : 'inherit' }}>
                    {t.max_slip_bps.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function MetricBox({ label, value, sub, color }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">{label}</div>
      <div className="mono text-[20px] font-medium mt-1" style={{ color: color || 'inherit' }}>{value}</div>
      {sub && <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{sub}</div>}
    </div>
  )
}


// ── Live-test controls ─────────────────────────────────────────────────────
// Renders master toggle, dry-run toggle, size input, Arm 1/5/disarm buttons,
// armed-count badge, and last fire result.
function LiveTestControlPanel({
  liveState, sizeInput, setSizeInput, busy, lastError,
  onArm, onDisarm, onToggleMaster, onToggleDryRun,
}) {
  const offline = !liveState || liveState.offline || liveState.error
  const master = !!liveState?.master_trading_enabled
  const dryRun = liveState?.dry_run_enabled !== false   // default true
  const armed = liveState?.armed_count ?? 0
  const totalFires = liveState?.total_fires ?? 0
  const cooldown = liveState?.in_cooldown
  const shouldFire = liveState?.should_fire_live
  const lastFire = liveState?.last_fire_result || null
  const currentSize = liveState?.live_test_size_usdc ?? 10
  const cooldownS = liveState?.cooldown_s ?? 30

  const armedColor = armed > 0 ? '#D9A62D' : '#8B8B8B'
  const masterColor = master ? '#1D9E75' : '#8B8B8B'
  const dryColor = dryRun ? '#7BAE8E' : '#E24B4A'

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap size={14} className="text-[var(--color-muted-foreground)]" />
          <span className="text-[11px] font-medium uppercase tracking-wider">
            Live-test controls
          </span>
          {offline && (
            <span className="text-[9px] text-[#E24B4A] mono">SCANNER OFFLINE</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[9px] mono">
          <span className="text-[var(--color-muted-foreground)]">
            TOTAL FIRES <span className="text-[var(--color-foreground)]">{totalFires}</span>
          </span>
          {cooldown && (
            <span style={{ color: '#D9A62D' }}>COOLDOWN ({cooldownS}s)</span>
          )}
          {shouldFire && (
            <span style={{ color: '#1D9E75' }}>● READY</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-[1.2fr_1fr_1fr_1.6fr] gap-3 items-stretch">
        {/* Master toggle */}
        <button
          onClick={onToggleMaster}
          disabled={busy || offline}
          className="border border-[var(--color-border)] p-3 text-left hover:bg-[var(--color-muted)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ borderColor: master ? masterColor : undefined }}
        >
          <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] flex items-center gap-1">
            <Power size={10} /> Master trading
          </div>
          <div className="mono text-[16px] font-medium mt-1" style={{ color: masterColor }}>
            {master ? 'ENABLED' : 'DISABLED'}
          </div>
          <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">
            {master ? 'click to halt' : 'click to enable'}
          </div>
        </button>

        {/* Dry-run toggle */}
        <button
          onClick={onToggleDryRun}
          disabled={busy || offline}
          className="border border-[var(--color-border)] p-3 text-left hover:bg-[var(--color-muted)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ borderColor: dryColor }}
        >
          <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Mode
          </div>
          <div className="mono text-[16px] font-medium mt-1" style={{ color: dryColor }}>
            {dryRun ? 'DRY-RUN' : 'REAL $$$'}
          </div>
          <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">
            {dryRun ? 'rejected orders, latency only' : '⚠ real capital at risk'}
          </div>
        </button>

        {/* Size input */}
        <div className="border border-[var(--color-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Size per fire (USDC)
          </div>
          <input
            type="number"
            step="1"
            min="1"
            max="100"
            value={sizeInput}
            onChange={(e) => setSizeInput(e.target.value)}
            disabled={busy || offline}
            className="mono text-[16px] font-medium mt-1 bg-transparent outline-none w-full text-[var(--color-foreground)] disabled:opacity-50"
          />
          <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">
            current: ${currentSize} • cap $100
          </div>
        </div>

        {/* Arm buttons */}
        <div className="border border-[var(--color-border)] p-3 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] flex items-center gap-1">
              <Target size={10} /> Armed queue
            </div>
            <div className="mono text-[16px] font-medium" style={{ color: armedColor }}>
              {armed}
            </div>
          </div>
          <div className="flex gap-1 mt-2">
            <ArmButton onClick={() => onArm(1)} disabled={busy || offline} label="ARM 1" />
            <ArmButton onClick={() => onArm(5)} disabled={busy || offline} label="ARM 5" />
            <button
              onClick={onDisarm}
              disabled={busy || offline || armed === 0}
              className="flex-1 border border-[var(--color-border)] text-[10px] mono py-1 hover:bg-[var(--color-muted)] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              DISARM
            </button>
          </div>
        </div>
      </div>

      {/* Last fire result */}
      {lastFire && (
        <div className="border border-[var(--color-border)] bg-[var(--color-muted)] p-2 text-[10px] mono flex items-center gap-4 flex-wrap">
          <span className="text-[var(--color-muted-foreground)] uppercase tracking-wider text-[9px]">
            Last fire
          </span>
          <span>
            outcome:{' '}
            <span style={{
              color: lastFire.outcome === 'COMPLETE' ? '#1D9E75'
                : lastFire.outcome === 'PARTIAL_HEDGED' ? '#E24B4A'
                : '#D9A62D'
            }}>
              {lastFire.outcome || '?'}
            </span>
          </span>
          {lastFire.pnl_usdc != null && (
            <span>
              pnl:{' '}
              <span style={{ color: lastFire.pnl_usdc >= 0 ? '#1D9E75' : '#E24B4A' }}>
                {lastFire.pnl_usdc >= 0 ? '+' : ''}${lastFire.pnl_usdc.toFixed(4)}
              </span>
            </span>
          )}
          {lastFire.execution_ms != null && (
            <span>latency: {lastFire.execution_ms.toFixed(1)}ms</span>
          )}
          {lastFire.ts && (
            <span className="text-[var(--color-muted-foreground)]">
              {new Date(lastFire.ts * 1000).toLocaleTimeString()}
            </span>
          )}
        </div>
      )}

      {lastError && (
        <div className="border border-[#E24B4A]/50 bg-[#E24B4A]/10 p-2 text-[10px] mono text-[#E24B4A]">
          error: {lastError}
        </div>
      )}

      {!dryRun && master && (
        <div className="border border-[#E24B4A]/40 bg-[#E24B4A]/5 p-2 text-[10px] text-[#E24B4A] flex items-center gap-2">
          <AlertTriangle size={12} />
          REAL CAPITAL AT RISK — each fire sends real orders to Binance at ${currentSize} per leg.
        </div>
      )}
    </div>
  )
}

function ArmButton({ onClick, disabled, label }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex-1 border border-[var(--color-border)] text-[10px] mono py-1 hover:bg-[var(--color-muted)] disabled:opacity-40 disabled:cursor-not-allowed"
      style={{ borderColor: disabled ? undefined : '#D9A62D' }}
    >
      {label}
    </button>
  )
}
