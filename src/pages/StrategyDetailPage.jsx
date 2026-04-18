import { useState, useCallback, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMode } from '../context/ModeContext'
import { CATEGORY_MAP, NODE_MAP } from '../utils/constants'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/formatters'
import TriangleScannerTab from '../components/strategy/TriangleScannerTab'
import ExecutionRealityTab from '../components/strategy/ExecutionRealityTab'
import PromotionGatesTab from '../components/strategy/PromotionGatesTab'
import {
  ArrowLeft, Play, Pause, FlaskConical, Rocket, Settings2,
  TrendingUp, TrendingDown, Activity, Clock, Save, DollarSign,
  Code2, Layers, ChevronDown, ChevronUp, X, Plus
} from 'lucide-react'

// has_plugin comes from API (scans strategies/ folder on every request)

function useLivePnl(pos) {
  const [pnl, setPnl] = useState(pos.collected_pnl || 0)
  useEffect(() => {
    const openedAt = new Date(pos.opened_at).getTime()
    const aprAbs = Math.abs(pos.entry_apr || 0)
    const perSecRate = (aprAbs / 100) / (365 * 24 * 3600) * (pos.perp_size_usdc || pos.size_usdc / 2)
    const tick = () => setPnl((pos.collected_pnl || 0) + perSecRate * ((Date.now() - openedAt) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [pos.id, pos.collected_pnl, pos.entry_apr, pos.opened_at, pos.perp_size_usdc, pos.size_usdc])
  return pnl
}

function LivePnlCell({ pos }) {
  const pnl = useLivePnl(pos)
  return (
    <span className="mono font-medium flex-1 text-right tabular-nums" style={{color: pnl >= 0 ? '#1D9E75' : '#E24B4A'}}>
      {pnl >= 0 ? '+' : ''}${Math.abs(pnl).toFixed(4)}
    </span>
  )
}

function LiveTotalHeader({ positions }) {
  const [total, setTotal] = useState(0)
  useEffect(() => {
    const calcs = positions.map(pos => {
      const openedAt = new Date(pos.opened_at).getTime()
      const aprAbs = Math.abs(pos.entry_apr || 0)
      const perSecRate = (aprAbs / 100) / (365 * 24 * 3600) * (pos.perp_size_usdc || pos.size_usdc / 2)
      return { openedAt, perSecRate, collected: pos.collected_pnl || 0 }
    })
    const tick = () => setTotal(calcs.reduce((sum, c) => sum + c.collected + c.perSecRate * ((Date.now() - c.openedAt) / 1000), 0))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [positions.map(p => p.id + p.collected_pnl).join(',')])
  return (
    <span className="text-[var(--color-muted-foreground)]">Live P&L: <span className="mono font-medium tabular-nums" style={{color: total >= 0 ? '#1D9E75' : '#E24B4A'}}>{total >= 0 ? '+' : ''}${Math.abs(total).toFixed(4)}</span></span>
  )
}

function MetricBox({ label, value, sub, color }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">{label}</div>
      <div className="mono text-[20px] font-medium mt-1" style={{ color }}>{value}</div>
      {sub && <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{sub}</div>}
    </div>
  )
}

// Live-ticking Total P&L box: avoids double-counting by subtracting open positions'
// already-counted collected payments before adding full client-side accrual.
function LivePnlMetricBox({ stats, openPositions }) {
  const closedOnly = (stats.total_pnl_usdc ?? 0) - (stats.open_collected_usdc ?? 0)
  const [livePnl, setLivePnl] = useState(stats.total_pnl_usdc ?? 0)

  useEffect(() => {
    if (!openPositions || openPositions.length === 0) {
      setLivePnl(stats.total_pnl_usdc ?? 0)
      return
    }
    const calcs = openPositions.map(pos => {
      const openedAt = new Date(pos.opened_at).getTime()
      const aprAbs = Math.abs(pos.entry_apr || 0)
      const perSecRate = (aprAbs / 100) / (365 * 24 * 3600) * (pos.perp_size_usdc || pos.size_usdc / 2)
      return { openedAt, perSecRate, collected: pos.collected_pnl || 0 }
    })
    const tick = () => setLivePnl(
      closedOnly + calcs.reduce((sum, c) => sum + c.collected + c.perSecRate * ((Date.now() - c.openedAt) / 1000), 0)
    )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [closedOnly, openPositions?.map(p => p.id + p.collected_pnl).join(',')])

  const color = livePnl >= 0 ? '#1D9E75' : '#E24B4A'
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Total P&L</div>
      <div className="mono text-[20px] font-medium mt-1 tabular-nums" style={{ color }}>
        {livePnl >= 0 ? '+' : ''}${Math.abs(livePnl).toFixed(2)}
      </div>
      {openPositions?.length > 0 && (
        <div className="text-[9px] text-[#EF9F27] mt-0.5">{openPositions.length} open pos</div>
      )}
    </div>
  )
}

export default function StrategyDetailPage() {
  const { strategyId } = useParams()
  const navigate = useNavigate()
  const { isPaper } = useMode()

  const { data, loading, refetch } = usePolling(
    useCallback(() => api.getStrategyDetail(strategyId), [strategyId]),
    5000
  )
  const mode = isPaper ? 'paper' : 'live'
  const { data: posData } = usePolling(
    useCallback(() => api.getPositions(mode).then(r => r ? { ...r, positions: (r.positions || []).filter(p => p.strategy_id === strategyId) } : null), [strategyId, mode]),
    8000
  )

  const [activeTab, setActiveTab] = useState('overview')
  const [showAllocate, setShowAllocate] = useState(false)
  const [allocAmount, setAllocAmount] = useState('10000')
  const [allocating, setAllocating] = useState(false)
  const [allocSuccess, setAllocSuccess] = useState(false)
  const [versionTag, setVersionTag] = useState('')
  const [versionNotes, setVersionNotes] = useState('')
  const [showSaveVersion, setShowSaveVersion] = useState(false)
  const [versionSaving, setVersionSaving] = useState(false)
  const [versionError, setVersionError] = useState('')
  const [versionSuccess, setVersionSuccess] = useState(false)
  const [editField, setEditField] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [saveError, setSaveError] = useState('')
  const [saveSuccess, setSaveSuccess] = useState('')
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [resetResult, setResetResult] = useState(null)
  const [resetError, setResetError] = useState('')
  const [toggling, setToggling] = useState(false)
  const [localEnabled, setLocalEnabled] = useState(null)
  useEffect(() => {
    if (data?.strategy) setLocalEnabled(data.strategy.enabled)
  }, [data?.strategy?.enabled])

  if (loading) {
    return (
      <div className="p-6 text-[11px] text-[var(--color-muted-foreground)]">
        Loading strategy detail...
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-6">
        <button onClick={() => navigate('/strategies')} className="flex items-center gap-1 text-[11px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] mb-4">
          <ArrowLeft size={14} /> Back to Strategies
        </button>
        <div className="text-[11px] text-[var(--color-muted-foreground)]">
          Could not load strategy — API server may be offline. Start the FastAPI server (<span className="mono">python api.py</span>) and refresh.
        </div>
      </div>
    )
  }

  const { strategy, trades, stats, versions } = data
  if (!strategy) {
    return (
      <div className="p-6">
        <button onClick={() => navigate('/strategies')} className="flex items-center gap-1 text-[11px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] mb-4">
          <ArrowLeft size={14} /> Back to Strategies
        </button>
        <div className="text-[var(--color-muted-foreground)]">Strategy not found</div>
      </div>
    )
  }

  const cat = CATEGORY_MAP[strategy.category]
  const node = NODE_MAP[strategy.node_id]
  const hasPlugin = !!strategy.has_plugin
  const paperCapital = strategy.max_capital || 0
  // Effective capital compounds in real-time: base pool + all realised P&L since last reset
  const effectiveCapital = paperCapital + (stats?.total_pnl_usdc || 0)

  const handleAllocate = async () => {
    setAllocating(true)
    const res = await api.allocateCapital(strategyId, parseFloat(allocAmount) || 0)
    setAllocating(false)
    if (res) {
      setAllocSuccess(true)
      setShowAllocate(false)
      refetch()
      setTimeout(() => setAllocSuccess(false), 3000)
    }
  }

  const isEnabled = localEnabled ?? data?.strategy?.enabled ?? false

  const handleToggle = async () => {
    if (toggling) return
    setToggling(true)
    const next = !isEnabled
    setLocalEnabled(next)  // optimistic
    try {
      const res = await api.toggleStrategy(strategyId)
      if (!res) {
        setLocalEnabled(!next)  // revert on failure
      } else {
        refetch()
      }
    } catch {
      setLocalEnabled(!next)  // revert on error
    } finally {
      setToggling(false)
    }
  }

  const handleModeChange = async (mode) => {
    await api.updateStrategyConfig(strategyId, { mode })
    refetch()
  }

  const handleConfigSave = async (field) => {
    let value = editVal
    if (field === 'kelly_multiplier' || field === 'max_capital_pct') value = parseFloat(value) || 0
    setSaveError('')
    const res = await api.updateStrategyConfig(strategyId, { [field]: value })
    if (res?.error) {
      setSaveError(res.detail || 'Save failed')
    } else {
      setEditField(null)
      setSaveSuccess(field)
      setTimeout(() => setSaveSuccess(''), 2000)
      refetch()
    }
  }

  const handleSaveVersion = async () => {
    setVersionSaving(true)
    setVersionError('')
    const tag = versionTag || `v${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`
    try {
      const res = await api.saveStrategyVersion(strategyId, tag, versionNotes)
      if (res && !res.error) {
        setShowSaveVersion(false)
        setVersionTag('')
        setVersionNotes('')
        setVersionSuccess(true)
        setTimeout(() => setVersionSuccess(false), 3000)
        refetch()
      } else {
        setVersionError(res?.detail || 'Save failed — check that strategy_versions table exists in Supabase.')
      }
    } catch (e) {
      setVersionError('API error — make sure the FastAPI server is running.')
    } finally {
      setVersionSaving(false)
    }
  }

  const handleResetAllocate = async () => {
    setResetting(true)
    setResetError('')
    try {
      const res = await api.resetAndAllocate(strategyId, mode)
      if (res && !res.error) {
        setResetResult(res)
        setShowResetConfirm(false)
        refetch()
      } else {
        setResetError(res?.detail || 'Reset failed — check API server and Supabase connection.')
      }
    } catch (e) {
      setResetError(e.message || 'Reset failed — unexpected error.')
    } finally {
      setResetting(false)
    }
  }

  const baseTabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'trades', label: `Trades (${trades.length})` },
    { id: 'gates', label: 'Promotion Gates' },
    { id: 'config', label: 'Config' },
    { id: 'versions', label: `Versions (${versions.length})` },
  ]

  // Add triangle scanner + execution reality tabs for A_M1
  const tabs = strategyId === 'A_M1_triangular_arb'
    ? [
        { id: 'scanner', label: 'Triangle Scanner' },
        { id: 'execution_reality', label: 'Execution Reality' },
        ...baseTabs,
      ]
    : baseTabs

  return (
    <div className="p-6 space-y-5">
      {/* Back + Header */}
      <div>
        <button onClick={() => navigate('/strategies')} className="flex items-center gap-1 text-[11px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] mb-3 transition-colors">
          <ArrowLeft size={14} /> All Strategies
        </button>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {cat && <span className="w-3 h-3 inline-block" style={{ backgroundColor: cat.color, borderRadius: '50%' }} />}
            <h1 className="text-[20px] font-medium">{strategy.display_name}</h1>
            <span className="mono text-[10px] px-1.5 py-0.5 bg-[var(--color-muted)] border border-[var(--color-border)]">
              {strategy.strategy_id}
            </span>
            {hasPlugin ? (
              <span className="flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.5 bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30">
                <Code2 size={9} /> BUILT
              </span>
            ) : (
              <span className="text-[9px] font-medium px-1.5 py-0.5 bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]">
                PLANNED
              </span>
            )}
            <Badge variant={strategy.mode === 'live' ? 'live' : 'paper'}>{(strategy.mode || 'paper').toUpperCase()}</Badge>
            {strategy.version_tag && <span className="mono text-[11px] text-[var(--color-muted-foreground)]">{strategy.version_tag}</span>}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleToggle}
              disabled={toggling}
              className={cn(
                'px-3 py-1.5 text-[10px] font-medium flex items-center gap-1 transition-colors disabled:opacity-50',
                isEnabled
                  ? 'bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30'
                  : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]'
              )}
            >
              {toggling ? '...' : isEnabled ? <><Play size={10} /> Running</> : <><Pause size={10} /> Stopped</>}
            </button>
          </div>
        </div>
        <p className="text-[11px] text-[var(--color-muted-foreground)] mt-1.5">
          {strategy.description}
          {node && <span> · {node.name}</span>}
          {cat && <span> · {cat.label}</span>}
        </p>
      </div>

      {/* Capital Warning / Success */}
      {allocSuccess && (
        <div className="border border-[#1D9E75]/30 bg-[#1D9E75]/5 px-4 py-3 text-[11px] text-[#1D9E75]">
          Capital allocated successfully — this strategy can now paper trade.
        </div>
      )}
      {!allocSuccess && paperCapital === 0 && (
        <div className="border border-[#EF9F27]/30 bg-[#EF9F27]/5 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-[11px]" style={{ color: '#EF9F27' }}>
            <DollarSign size={14} />
            <span>No paper trading capital allocated. This strategy can't trade without capital.</span>
          </div>
          <button
            onClick={() => setShowAllocate(true)}
            className="px-3 py-1 text-[10px] font-medium bg-[#EF9F27]/10 text-[#EF9F27] border border-[#EF9F27]/30 hover:bg-[#EF9F27]/20 transition-colors"
          >
            Allocate Capital
          </button>
        </div>
      )}

      {/* Allocate Capital Modal */}
      {showAllocate && (
        <div className="border border-[var(--color-accent)] bg-[var(--color-card)] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium">Allocate Paper Trading Capital</span>
            <button onClick={() => setShowAllocate(false)}><X size={14} className="text-[var(--color-muted-foreground)]" /></button>
          </div>
          <p className="text-[10px] text-[var(--color-muted-foreground)]">
            Set how much USDC is available for paper trading across all strategies in the crypto_sg pool.
          </p>
          <div className="flex items-center gap-2">
            {[1000, 5000, 10000, 50000].map(amt => (
              <button
                key={amt}
                onClick={() => setAllocAmount(String(amt))}
                className={cn(
                  'px-2 py-1 text-[10px] mono border transition-colors',
                  allocAmount === String(amt)
                    ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent)]/10'
                    : 'border-[var(--color-border)] text-[var(--color-muted-foreground)]'
                )}
              >
                ${amt.toLocaleString()}
              </button>
            ))}
            <input
              type="number"
              value={allocAmount}
              onChange={e => setAllocAmount(e.target.value)}
              className="w-24 px-2 py-1 text-[10px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
            />
            <span className="text-[10px] text-[var(--color-muted-foreground)]">USDC</span>
          </div>
          <button
            onClick={handleAllocate}
            disabled={allocating}
            className="px-4 py-1.5 text-[10px] font-medium bg-[var(--color-accent)]/10 text-[var(--color-accent)] border border-[var(--color-accent)]/30 hover:bg-[var(--color-accent)]/20 transition-colors disabled:opacity-50"
          >
            {allocating ? 'Allocating...' : `Allocate $${parseFloat(allocAmount || 0).toLocaleString()} USDC`}
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-7 gap-3">
        <MetricBox label="Win Rate" value={stats.win_rate ? `${stats.win_rate}%` : '--'} color={stats.win_rate > 70 ? '#1D9E75' : '#EF9F27'} />
        <LivePnlMetricBox stats={stats} openPositions={posData?.positions || []} />
        <MetricBox label="Total Trades" value={String(stats.total_trades)} sub={`${stats.paper_trades}p / ${stats.live_trades}l`} />
        <MetricBox label="Wins" value={String(stats.wins)} color="#1D9E75" />
        <MetricBox label="Losses" value={String(stats.losses)} color="#E24B4A" />
        <MetricBox label="Kelly" value={strategy.kelly_multiplier ?? '1.0'} />
        <MetricBox
          label="Capital Pool"
          value={`$${effectiveCapital.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
          sub={paperCapital > 0 ? `Base $${paperCapital.toLocaleString()} + $${(stats?.total_pnl_usdc || 0).toFixed(2)} P&L` : 'Not allocated'}
          color={paperCapital > 0 ? '#1D9E75' : '#EF9F27'}
        />
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-0.5 border-b border-[var(--color-border)]">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-3 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-[1px]',
              activeTab === tab.id
                ? 'text-[var(--color-foreground)] border-[var(--color-accent)]'
                : 'text-[var(--color-muted-foreground)] border-transparent hover:text-[var(--color-foreground)]'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'scanner' && (
        <TriangleScannerTab />
      )}

      {activeTab === 'execution_reality' && (
        <ExecutionRealityTab strategyId={strategyId} />
      )}

      {activeTab === 'overview' && (
        <div className="space-y-4">
          {/* Strategy Info */}
          <div className="grid grid-cols-2 gap-4">
            <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-2">
              <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Strategy Info</div>
              {[
                ['Category', cat?.label || strategy.category],
                ['Node', node?.name || strategy.node_id],
                ['File', strategy.file_name || `${strategyId}.py`],
                ['Plugin', hasPlugin ? 'Loaded & Wired' : 'Not built yet'],
                ['Status', isEnabled ? 'Running' : 'Stopped'],
                ['Mode', (strategy.mode || 'paper').toUpperCase()],
                ['Version', strategy.version_tag || 'v1'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--color-muted-foreground)]">{k}</span>
                  <span className={cn('mono', k === 'Plugin' && hasPlugin && 'text-[#1D9E75]')}>{v}</span>
                </div>
              ))}
            </div>
            <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-2">
              <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Configuration</div>
              {[
                ['Kelly Multiplier', strategy.kelly_multiplier ?? 1.0],
                ['Max Capital %', `${((strategy.max_capital_pct || 0) * 100).toFixed(0)}%`],
                ['Max Allocation', paperCapital > 0 ? `$${(paperCapital * (strategy.max_capital_pct || 0)).toFixed(0)} USDC` : 'No capital'],
                ['Notes', strategy.notes || '—'],
                ['Uploaded', strategy.uploaded_at ? new Date(strategy.uploaded_at).toLocaleDateString() : '—'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--color-muted-foreground)]">{k}</span>
                  <span className="mono">{v}</span>
                </div>
              ))}
              {paperCapital === 0 && (
                <button
                  onClick={() => setShowAllocate(true)}
                  className="w-full mt-2 px-3 py-1.5 text-[10px] font-medium text-[#EF9F27] bg-[#EF9F27]/10 border border-[#EF9F27]/30"
                >
                  <DollarSign size={10} className="inline mr-1" /> Allocate Paper Capital
                </button>
              )}
            </div>
          </div>

          {/* Open Positions (Live P&L) */}
          {(() => {
            const openPos = posData?.positions || []
            const totalPnl = posData?.total_unrealised_pnl || 0
            const totalDep = posData?.total_deployed_usdc || 0
            if (openPos.length === 0) return null
            return (
              <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
                <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TrendingUp size={13} className="text-[#1D9E75]" />
                    <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Open Positions</span>
                    <span className="text-[9px] px-1.5 py-0.5 bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/20">{openPos.length} ACTIVE</span>
                  </div>
                  <div className="flex items-center gap-4 text-[10px]">
                    <span className="text-[var(--color-muted-foreground)]">Deployed: <span className="mono font-medium text-[var(--color-foreground)]">${totalDep.toLocaleString(undefined,{minimumFractionDigits:2})}</span></span>
                    <LiveTotalHeader positions={openPos} />
                  </div>
                </div>
                <div className="flex items-center gap-3 px-4 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-muted)]/20 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  <span className="w-[100px] shrink-0">Symbol</span>
                  <span className="w-[80px] shrink-0">Direction</span>
                  <span className="w-[80px] shrink-0 text-right">Size</span>
                  <span className="w-[90px] shrink-0 text-right">Entry APR</span>
                  <span className="w-[60px] shrink-0 text-right">Held</span>
                  <span className="w-[70px] shrink-0 text-right">Payments</span>
                  <span className="flex-1 text-right">Live P&L</span>
                </div>
                {openPos.map(pos => (
                  <div key={pos.id} className="flex items-center gap-3 px-4 py-2 border-b border-[var(--color-border)] last:border-0 text-[10px]">
                    <span className="mono font-medium w-[100px] shrink-0">{pos.symbol}</span>
                    <span className="w-[80px] shrink-0 uppercase" style={{color: pos.direction?.includes('neg') ? '#EF9F27' : '#1D9E75'}}>
                      {pos.direction?.replace(/_/g,' ') || '—'}
                    </span>
                    <span className="mono w-[80px] shrink-0 text-right">${(pos.size_usdc||0).toFixed(2)}</span>
                    <span className="mono w-[90px] shrink-0 text-right" style={{color:'#EF9F27'}}>{pos.entry_apr?.toFixed(2)}%</span>
                    <span className="mono w-[60px] shrink-0 text-right text-[var(--color-muted-foreground)]">{pos.hours_held}h</span>
                    <span className="mono w-[70px] shrink-0 text-right text-[var(--color-muted-foreground)]">{pos.payments_received ?? 0}</span>
                    <LivePnlCell pos={pos} />
                  </div>
                ))}
              </div>
            )
          })()}

          {/* Recent Activity */}
          {trades.length > 0 ? (
            <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
              <div className="px-4 py-2.5 border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
                Recent Trades
              </div>
              {trades.slice(0, 10).map((t, i) => (
                <div key={t.id || (t.triangle_id ? `${t.triangle_id}-${t.created_at}` : i)} className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-border)] last:border-0 text-[10px]">
                  <span className="mono w-[130px] shrink-0 text-[var(--color-muted-foreground)]">
                    {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                  </span>
                  <span className="mono font-medium w-[100px] shrink-0">{t.symbol}</span>
                  <span className="w-[50px] shrink-0" style={{ color: t.direction === 'BUY' ? '#1D9E75' : '#E24B4A' }}>
                    {t.direction}
                  </span>
                  <span className="mono w-[80px] shrink-0">${(t.size_usdc || 0).toFixed(2)}</span>
                  <span className={cn('mono w-[60px] shrink-0', t.outcome === 'won' ? 'text-[#1D9E75]' : t.outcome === 'lost' ? 'text-[#E24B4A]' : 'text-[var(--color-muted-foreground)]')}>
                    {t.outcome || 'pending'}
                  </span>
                  <span className="mono text-[var(--color-muted-foreground)]">{t.is_paper ? 'Paper' : 'Live'}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-8 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No trades yet. {!isEnabled && 'Enable the strategy and allocate capital to start paper trading.'}
              {isEnabled && paperCapital === 0 && 'Allocate capital to start paper trading.'}
              {isEnabled && paperCapital > 0 && !hasPlugin && 'Strategy plugin is not built yet.'}
              {isEnabled && paperCapital > 0 && hasPlugin && 'Waiting for market signals...'}
            </div>
          )}
        </div>
      )}

      {activeTab === 'trades' && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
          <div className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-muted)]/30 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            <span className="w-[130px] shrink-0">Time</span>
            <span className="w-[100px] shrink-0">Symbol</span>
            <span className="w-[50px] shrink-0">Side</span>
            <span className="w-[80px] shrink-0">Size</span>
            <span className="w-[80px] shrink-0">Entry</span>
            <span className="w-[60px] shrink-0">Outcome</span>
            <span className="w-[60px] shrink-0">Edge</span>
            <span className="w-[60px] shrink-0">Mode</span>
            <span className="flex-1">Reasoning</span>
          </div>
          {trades.length > 0 ? trades.map((t, i) => (
            <div key={t.id || t.triangle_id ? `${t.triangle_id}-${t.created_at}` : i} className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-border)] last:border-0 text-[10px]">
              <span className="mono w-[130px] shrink-0 text-[var(--color-muted-foreground)]">
                {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
              </span>
              <span className="mono font-medium w-[100px] shrink-0">{t.symbol}</span>
              <span className="w-[50px] shrink-0" style={{ color: t.direction === 'BUY' ? '#1D9E75' : '#E24B4A' }}>
                {t.direction}
              </span>
              <span className="mono w-[80px] shrink-0">${(t.size_usdc || 0).toFixed(2)}</span>
              <span className="mono w-[80px] shrink-0">${(t.entry_price || 0).toFixed(4)}</span>
              <span className={cn('mono w-[60px] shrink-0', t.outcome === 'won' ? 'text-[#1D9E75]' : t.outcome === 'lost' ? 'text-[#E24B4A]' : '')}>
                {t.outcome || 'pending'}
              </span>
              <span className="mono w-[60px] shrink-0">{t.edge_detected ? `${t.edge_detected}%` : '—'}</span>
              <span className="mono w-[60px] shrink-0 text-[var(--color-muted-foreground)]">{t.is_paper ? 'Paper' : 'Live'}</span>
              <span className="text-[9px] text-[var(--color-muted-foreground)] truncate flex-1">{t.ai_reasoning || '—'}</span>
            </div>
          )) : (
            <div className="px-4 py-8 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No trades recorded yet.
            </div>
          )}
        </div>
      )}

      {activeTab === 'gates' && (
        <PromotionGatesTab strategyId={strategyId} />
      )}

      {activeTab === 'config' && (
        <div className="space-y-4">
          {/* Mode */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Trading Mode</div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleModeChange('paper')}
                className={cn(
                  'px-4 py-2 text-[11px] font-medium border flex items-center gap-2 transition-colors',
                  strategy.mode === 'paper'
                    ? 'bg-[#1D9E75]/10 text-[#1D9E75] border-[#1D9E75]/30'
                    : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]'
                )}
              >
                <FlaskConical size={14} /> Paper Trading
              </button>
              <button
                onClick={() => handleModeChange('live')}
                className={cn(
                  'px-4 py-2 text-[11px] font-medium border flex items-center gap-2 transition-colors',
                  strategy.mode === 'live'
                    ? 'bg-[#FF002B]/10 text-[#FF002B] border-[#FF002B]/30'
                    : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]'
                )}
              >
                <Rocket size={14} /> Live Trading
              </button>
            </div>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">
              {strategy.mode === 'paper'
                ? 'Paper mode: trades are simulated. No real funds used.'
                : 'Live mode: real funds will be deployed. Ensure risk limits are set.'}
            </p>
          </div>

          {/* Parameters */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Parameters</div>
            {[
              { field: 'kelly_multiplier', label: 'Kelly Multiplier', value: strategy.kelly_multiplier ?? 1.0, desc: 'Position sizing multiplier (0-1). Lower = more conservative.' },
              { field: 'max_capital_pct', label: 'Max Capital %', value: strategy.max_capital_pct ?? 0, desc: 'Maximum % of pool capital this strategy can use.' },
              { field: 'notes', label: 'Notes', value: strategy.notes || '', desc: 'Internal notes for tracking changes.' },
            ].map(({ field, label, value, desc }) => (
              <div key={field} className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0">
                <div>
                  <div className="text-[11px] font-medium">{label}</div>
                  <div className="text-[9px] text-[var(--color-muted-foreground)]">{desc}</div>
                </div>
                {editField === field ? (
                  <div className="flex items-center gap-1">
                    <input
                      type={field === 'notes' ? 'text' : 'number'}
                      step={field === 'notes' ? undefined : '0.05'}
                      value={editVal}
                      onChange={e => setEditVal(e.target.value)}
                      className="w-28 px-2 py-1 text-[11px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                      autoFocus
                    />
                    <button onClick={() => handleConfigSave(field)} className="px-2 py-1 text-[10px] text-[#1D9E75] border border-[#1D9E75]/30 bg-[#1D9E75]/10">Save</button>
                    <button onClick={() => setEditField(null)} className="text-[var(--color-muted-foreground)]"><X size={12} /></button>
                  </div>
                ) : (
                  <button
                    onClick={() => { setEditField(field); setEditVal(field === 'max_capital_pct' ? (value * 100).toFixed(0) : value) }}
                    className="mono text-[11px] px-2 py-1 border border-[var(--color-border)] hover:border-[var(--color-accent)] transition-colors"
                  >
                    {field === 'max_capital_pct' ? `${(value * 100).toFixed(0)}%` : value || '—'}
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Dynamic strategy-specific config — works for every plugin automatically */}
          {(() => {
            const cfg = strategy.strategy_config || {}
            const defaults = strategy.default_config || {}
            const allKeys = Object.keys(defaults)
            if (allKeys.length === 0) return null

            // Split keys by value type
            const numericKeys = allKeys.filter(k => typeof defaults[k] === 'number')
            const stringKeys = allKeys.filter(k => typeof defaults[k] === 'string')
            const listKeys = allKeys.filter(k => Array.isArray(defaults[k]))

            const formatVal = (key, val) => {
              const v = parseFloat(val)
              if (key === 'perp_leverage') return `${v}x`
              if (key.includes('open') && !key.includes('apr')) return String(Math.round(v))
              if (key.includes('pct') || key.includes('apr') || key.includes('threshold') || key.includes('delta') || (key.includes('rate') && !key.includes('funding'))) {
                return `${(v * 100).toFixed(3)}%`
              }
              if (key.includes('usdc') || key.includes('size') || key.includes('deployed') || key.includes('capital')) {
                return `$${v.toLocaleString()}`
              }
              if (key.includes('hours') || key.includes('hold')) return `${v}h`
              return String(val ?? '—')
            }

            const labelFor = (key) =>
              key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

            const handlePluginSave = async (key) => {
              const raw = editVal
              const num = parseFloat(raw)
              const val = isNaN(num) ? raw : num
              setSaveError('')
              const res = await api.updateStrategyConfig(strategyId, { strategy_config: { [key]: val } })
              if (res?.error) {
                setSaveError(res.detail || 'Save failed')
              } else {
                setEditField(null)
                setSaveSuccess(key)
                setTimeout(() => setSaveSuccess(''), 2000)
                refetch()
              }
            }

            // A_M1 triangle set toggles
            const TRIANGLE_SET_KEYS = ['BTC_ETH_USDT', 'BNB_BTC_USDT', 'SOL_BTC_USDT', 'LINK_BTC_USDT', 'XRP_BTC_USDT', 'LTC_BTC_USDT']
            const activeTriangles = cfg.active_triangle_sets || TRIANGLE_SET_KEYS
            const toggleTriangle = async (setKey) => {
              const current = cfg.active_triangle_sets || TRIANGLE_SET_KEYS
              const next = current.includes(setKey) ? current.filter(k => k !== setKey) : [...current, setKey]
              await api.updateStrategyConfig(strategyId, { strategy_config: { active_triangle_sets: next } })
              refetch()
            }

            return (
              <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
                {saveError && (
                  <div className="px-3 py-2 text-[10px] bg-[#E24B4A]/10 border border-[#E24B4A]/30 text-[#E24B4A]">
                    Save failed: {saveError}
                  </div>
                )}
                {saveSuccess && (
                  <div className="px-3 py-2 text-[10px] bg-[#1D9E75]/10 border border-[#1D9E75]/30 text-[#1D9E75]">
                    Saved — scanner picks up in &lt;30s
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
                    {strategy.display_name} — Strategy Config
                  </div>
                  <span className="text-[9px] px-1.5 py-0.5 bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/20">
                    LIVE PARAMS · scanner picks up in &lt;30s
                  </span>
                </div>

                {/* Editable numeric params */}
                {numericKeys.map(key => {
                  const current = cfg[key] ?? defaults[key]
                  const fieldId = `plugin_${key}`
                  return (
                    <div key={key} className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0">
                      <div>
                        <div className="text-[11px] font-medium">{labelFor(key)}</div>
                        <div className="text-[9px] text-[var(--color-muted-foreground)] mono">
                          default: {formatVal(key, defaults[key])}
                        </div>
                      </div>
                      {editField === fieldId ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="number" step="any" value={editVal}
                            onChange={e => setEditVal(e.target.value)}
                            className="w-28 px-2 py-1 text-[11px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                            autoFocus
                          />
                          <button onClick={() => handlePluginSave(key)} className="px-2 py-1 text-[10px] text-[#1D9E75] border border-[#1D9E75]/30 bg-[#1D9E75]/10">Save</button>
                          <button onClick={() => setEditField(null)} className="text-[var(--color-muted-foreground)]"><X size={12} /></button>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setEditField(fieldId); setEditVal(String(current)) }}
                          className="mono text-[11px] px-2 py-1 border border-[var(--color-border)] hover:border-[#1D9E75] transition-colors"
                        >
                          {formatVal(key, current)}
                        </button>
                      )}
                    </div>
                  )
                })}

                {/* Read-only string params */}
                {stringKeys.length > 0 && (
                  <div className="pt-1 space-y-1">
                    <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">Exchange Settings</div>
                    {stringKeys.map(key => (
                      <div key={key} className="flex items-center justify-between text-[10px]">
                        <span className="text-[var(--color-muted-foreground)]">{labelFor(key)}</span>
                        <span className="mono">{cfg[key] ?? defaults[key]}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* List params — A_M1 triangle toggles, others show count */}
                {listKeys.map(key => {
                  if (key === 'active_triangle_sets') return (
                    <div key={key} className="pt-1">
                      <div className="text-[10px] text-[var(--color-muted-foreground)] mb-2">
                        Active Triangle Sets ({activeTriangles.length}/{TRIANGLE_SET_KEYS.length})
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {TRIANGLE_SET_KEYS.map(setKey => {
                          const active = activeTriangles.includes(setKey)
                          return (
                            <button
                              key={setKey}
                              onClick={() => toggleTriangle(setKey)}
                              className={cn(
                                'px-2.5 py-1 text-[10px] font-mono border transition-colors',
                                active
                                  ? 'bg-[#1D9E75]/10 text-[#1D9E75] border-[#1D9E75]/30'
                                  : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]'
                              )}
                            >
                              {setKey.replace(/_/g, '/')}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )
                  const list = cfg[key] ?? defaults[key] ?? []
                  const listFieldId = `list_${key}`
                  return (
                    <div key={key} className="pt-2 border-t border-[var(--color-border)]">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-[var(--color-muted-foreground)]">{labelFor(key)}</span>
                        <span className="text-[9px] text-[var(--color-muted-foreground)]">{list.length} symbols</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5 mb-2">
                        {list.map(sym => (
                          <span key={sym} className="flex items-center gap-1 px-2 py-0.5 text-[10px] mono bg-[var(--color-muted)] border border-[var(--color-border)]">
                            {sym}
                            <button
                              onClick={async () => {
                                const next = list.filter(s => s !== sym)
                                setSaveError('')
                                const res = await api.updateStrategyConfig(strategyId, { strategy_config: { [key]: next } })
                                if (res?.error) setSaveError(res.detail || 'Save failed')
                                else { setSaveSuccess(key); setTimeout(() => setSaveSuccess(''), 2000); refetch() }
                              }}
                              className="text-[var(--color-muted-foreground)] hover:text-[#E24B4A] ml-0.5"
                            >×</button>
                          </span>
                        ))}
                      </div>
                      {editField === listFieldId ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="text" value={editVal} placeholder="e.g. NTRNUSDT"
                            onChange={e => setEditVal(e.target.value.toUpperCase())}
                            onKeyDown={async e => {
                              if (e.key === 'Enter' && editVal.trim()) {
                                const sym = editVal.trim().toUpperCase()
                                if (!list.includes(sym)) {
                                  const next = [...list, sym]
                                  setSaveError('')
                                  const res = await api.updateStrategyConfig(strategyId, { strategy_config: { [key]: next } })
                                  if (res?.error) setSaveError(res.detail || 'Save failed')
                                  else { setEditField(null); setEditVal(''); setSaveSuccess(key); setTimeout(() => setSaveSuccess(''), 2000); refetch() }
                                }
                              }
                              if (e.key === 'Escape') { setEditField(null); setEditVal('') }
                            }}
                            className="w-32 px-2 py-1 text-[11px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                            autoFocus
                          />
                          <button
                            onClick={async () => {
                              const sym = editVal.trim().toUpperCase()
                              if (sym && !list.includes(sym)) {
                                const next = [...list, sym]
                                setSaveError('')
                                const res = await api.updateStrategyConfig(strategyId, { strategy_config: { [key]: next } })
                                if (res?.error) setSaveError(res.detail || 'Save failed')
                                else { setEditField(null); setEditVal(''); setSaveSuccess(key); setTimeout(() => setSaveSuccess(''), 2000); refetch() }
                              }
                            }}
                            className="px-2 py-1 text-[10px] text-[#1D9E75] border border-[#1D9E75]/30 bg-[#1D9E75]/10"
                          >Add</button>
                          <button onClick={() => { setEditField(null); setEditVal('') }} className="text-[10px] text-[var(--color-muted-foreground)]">Cancel</button>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setEditField(listFieldId); setEditVal('') }}
                          className="text-[10px] text-[#1D9E75] border border-[#1D9E75]/30 px-2 py-0.5 hover:bg-[#1D9E75]/10"
                        >+ Add Symbol</button>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })()}

          {/* Capital */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Paper Capital Pool</div>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-[var(--color-muted-foreground)]">Effective Pool (base + P&L)</span>
              <span className="mono font-medium" style={{ color: paperCapital > 0 ? '#1D9E75' : '#EF9F27' }}>
                ${effectiveCapital.toFixed(2)} USDC
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-[var(--color-muted-foreground)]">Base $${paperCapital.toLocaleString()} + P&L ${(stats?.total_pnl_usdc || 0) >= 0 ? '+' : ''}${(stats?.total_pnl_usdc || 0).toFixed(2)}</span>
              <span className="mono font-medium">
                ${(effectiveCapital * (strategy.max_capital_pct || 0)).toFixed(0)} USDC ({((strategy.max_capital_pct || 0) * 100).toFixed(0)}%)
              </span>
            </div>
            <button
              onClick={() => setShowAllocate(true)}
              className="px-3 py-1.5 text-[10px] font-medium text-[var(--color-accent)] bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/30"
            >
              <DollarSign size={10} className="inline mr-1" /> Change Pool Balance
            </button>
          </div>

          {/* Reset + Allocate (Compound) */}
          <div className="border border-[#E24B4A]/30 bg-[var(--color-card)] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-wider text-[#E24B4A]">Reset + Compound</div>
              <button
                onClick={() => { setShowResetConfirm(true); setResetResult(null) }}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-[#E24B4A] bg-[#E24B4A]/10 border border-[#E24B4A]/30 hover:bg-[#E24B4A]/20"
              >
                ↺ Reset & Allocate
              </button>
            </div>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">
              Compound realised P&L into the capital pool, then clear trade history for a fresh start. New pool = current pool + all profits.
            </p>
            <div className="flex gap-4 text-[10px]">
              <span className="text-[var(--color-muted-foreground)]">
                Current pool: <span className="mono font-medium text-[#1D9E75]">${effectiveCapital.toFixed(2)}</span>
              </span>
              <span className="text-[var(--color-muted-foreground)]">
                Since reset P&L: <span className="mono font-medium" style={{color: (stats?.total_pnl_usdc || 0) >= 0 ? '#1D9E75' : '#E24B4A'}}>
                  {(stats?.total_pnl_usdc || 0) >= 0 ? '+' : ''}${(stats?.total_pnl_usdc || 0).toFixed(2)}
                </span>
              </span>
              <span className="text-[var(--color-muted-foreground)]">
                Next reset pool: <span className="mono font-medium text-[#1D9E75]">${effectiveCapital.toFixed(2)}</span>
              </span>
            </div>

            {/* Confirm dialog */}
            {showResetConfirm && (
              <div className="p-3 bg-[#E24B4A]/10 border border-[#E24B4A]/40 space-y-3">
                <div className="text-[10px] font-medium text-[#E24B4A]">Confirm Reset & Compound</div>
                <div className="text-[10px] text-[var(--color-muted-foreground)] space-y-1">
                  <div>• <span className="text-[var(--color-foreground)]">{stats?.total_trades || trades.length} trades</span> will be permanently deleted</div>
                  <div>• Current effective pool <span className="mono font-medium text-[#1D9E75]">${effectiveCapital.toFixed(2)}</span> becomes new base</div>
                  <div>• P&L counter resets to <span className="mono font-medium">$0</span> — fresh tracking from ${effectiveCapital.toFixed(2)}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleResetAllocate}
                    disabled={resetting}
                    className="px-3 py-1.5 text-[10px] font-medium bg-[#E24B4A] text-white border border-[#E24B4A] disabled:opacity-50"
                  >
                    {resetting ? 'Resetting...' : 'Confirm Reset'}
                  </button>
                  <button
                    onClick={() => { setShowResetConfirm(false); setResetError('') }}
                    className="px-3 py-1.5 text-[10px] font-medium text-[var(--color-muted-foreground)] border border-[var(--color-border)]"
                  >
                    Cancel
                  </button>
                </div>
                {resetError && (
                  <div className="text-[10px] text-[#E24B4A] mt-1">{resetError}</div>
                )}
              </div>
            )}

            {/* Success result */}
            {resetResult && (
              <div className="p-3 bg-[#1D9E75]/10 border border-[#1D9E75]/30 space-y-1 text-[10px]">
                <div className="font-medium text-[#1D9E75]">Reset complete</div>
                <div className="text-[var(--color-muted-foreground)]">
                  Compounded <span className="mono text-[var(--color-foreground)]">+${resetResult.pnl_compounded?.toFixed(2)}</span> →
                  New pool: <span className="mono font-medium text-[#1D9E75]">${resetResult.new_capital?.toFixed(2)}</span> •
                  Cleared <span className="mono text-[var(--color-foreground)]">{resetResult.trades_cleared}</span> trades
                </div>
              </div>
            )}
          </div>

          {/* Save Version */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Version Snapshot</div>
              <button
                onClick={() => setShowSaveVersion(!showSaveVersion)}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-[var(--color-accent)] bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/30"
              >
                <Save size={10} /> Save Current Config as Version
              </button>
            </div>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">
              Save a snapshot of current settings for A/B comparison. Track which config produces the best results.
            </p>
            {versionSuccess && (
              <div className="text-[10px] text-[#1D9E75] bg-[#1D9E75]/10 border border-[#1D9E75]/30 px-3 py-2">
                Version saved successfully — check the Versions tab.
              </div>
            )}
            {versionError && (
              <div className="text-[10px] text-[#E24B4A] bg-[#E24B4A]/10 border border-[#E24B4A]/30 px-3 py-2">
                {versionError}
              </div>
            )}
            {showSaveVersion && (
              <div className="p-3 bg-[var(--color-muted)]/30 border border-[var(--color-border)] space-y-2">
                <input
                  type="text"
                  value={versionTag}
                  onChange={e => setVersionTag(e.target.value)}
                  placeholder="Version tag (e.g. v2-aggressive)"
                  className="w-full px-2 py-1.5 text-[11px] bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                />
                <input
                  type="text"
                  value={versionNotes}
                  onChange={e => setVersionNotes(e.target.value)}
                  placeholder="Notes (e.g. increased kelly from 0.5 to 1.0)"
                  className="w-full px-2 py-1.5 text-[11px] bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                />
                <button
                  onClick={handleSaveVersion}
                  disabled={versionSaving}
                  className="px-4 py-1.5 text-[10px] font-medium bg-[var(--color-accent)]/10 text-[var(--color-accent)] border border-[var(--color-accent)]/30 disabled:opacity-50"
                >
                  {versionSaving ? 'Saving...' : 'Save Version'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'versions' && (
        <div className="space-y-3">
          {versions.length > 0 ? versions.map((v, i) => {
            const snap = v.config_snapshot || {}
            const cfg = snap.strategy_config || {}
            const cfgKeys = Object.keys(cfg)
            return (
              <div key={i} className="border border-[var(--color-border)] bg-[var(--color-card)]">
                {/* Version header */}
                <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-muted)]/30">
                  <span className="mono font-medium text-[11px]">{v.version_tag}</span>
                  <span className="text-[9px] text-[var(--color-muted-foreground)]">
                    {v.created_at ? new Date(v.created_at).toLocaleString() : '—'}
                  </span>
                  <span className="text-[9px] text-[var(--color-muted-foreground)] ml-auto italic">{v.notes || ''}</span>
                </div>
                {/* Performance at save */}
                <div className="flex gap-6 px-4 py-2 border-b border-[var(--color-border)] text-[10px]">
                  <span className="text-[var(--color-muted-foreground)]">Mode: <span className="mono text-[var(--color-foreground)]">{snap.mode || '—'}</span></span>
                  <span className="text-[var(--color-muted-foreground)]">Kelly: <span className="mono text-[var(--color-foreground)]">{snap.kelly_multiplier ?? '—'}</span></span>
                  <span className="text-[var(--color-muted-foreground)]">Max Cap: <span className="mono text-[var(--color-foreground)]">{snap.max_capital_pct != null ? `${(snap.max_capital_pct * 100).toFixed(0)}%` : '—'}</span></span>
                  <span className="text-[var(--color-muted-foreground)]">WR: <span className="mono text-[var(--color-foreground)]">{snap.win_rate_at_save != null ? `${snap.win_rate_at_save}%` : '—'}</span></span>
                  <span className="text-[var(--color-muted-foreground)]">PnL: <span className="mono" style={{ color: (snap.pnl_at_save || 0) >= 0 ? '#1D9E75' : '#E24B4A' }}>${(snap.pnl_at_save || 0).toFixed(2)}</span></span>
                  <span className="text-[var(--color-muted-foreground)]">Trades: <span className="mono text-[var(--color-foreground)]">{snap.trades_at_save ?? '—'}</span></span>
                </div>
                {/* Strategy-specific config params */}
                {cfgKeys.length > 0 ? (
                  <div className="px-4 py-3 grid grid-cols-2 gap-x-8 gap-y-1">
                    {cfgKeys.map(k => (
                      <div key={k} className="flex items-center justify-between text-[10px]">
                        <span className="text-[var(--color-muted-foreground)] capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className="mono text-[var(--color-foreground)]">{String(cfg[k])}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="px-4 py-2 text-[10px] text-[var(--color-muted-foreground)] italic">No strategy-specific config captured</div>
                )}
              </div>
            )
          }) : (
            <div className="border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-8 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No versions saved yet. Go to Config tab and save a version snapshot to start tracking changes.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
