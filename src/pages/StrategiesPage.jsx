import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMode } from '../context/ModeContext'
import { CATEGORIES, CATEGORY_MAP, NODE_MAP } from '../utils/constants'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/formatters'
import {
  Zap, FileCode, Server, ChevronDown, ChevronUp, Settings2,
  Play, Pause, FlaskConical, Rocket, Activity, Clock, Code2, X
} from 'lucide-react'

// has_plugin is now returned by the API (scans strategies/ folder dynamically)

function StatusDot({ active, label }) {
  return (
    <span className="flex items-center gap-1 text-[9px]">
      <span
        className="w-1.5 h-1.5 inline-block"
        style={{
          backgroundColor: active ? '#1D9E75' : 'var(--color-muted-foreground)',
          borderRadius: '50%',
          opacity: active ? 1 : 0.4,
        }}
      />
      <span className={active ? 'text-[var(--color-foreground)]' : 'text-[var(--color-muted-foreground)]'}>{label}</span>
    </span>
  )
}

function StrategyCard({ strategy, onToggle, onExpand, expanded, onConfigSave, onNavigate }) {
  const node = NODE_MAP[strategy.node_id]
  const winRate = strategy.win_rate ?? 0
  const totalPnl = strategy.total_pnl_usdc ?? 0
  const closedTrades = (strategy.paper_trades_count || 0) + (strategy.live_trades_count || 0)
  const pendingTrades = strategy.pending_trades || 0
  const totalTrades = closedTrades + pendingTrades
  const hasPlugin = !!strategy.has_plugin

  const [editMode, setEditMode] = useState(null) // 'kelly' | 'cap' | 'notes'
  const [editVal, setEditVal] = useState('')

  const saveField = async (field) => {
    let value = editVal
    if (field === 'kelly_multiplier' || field === 'max_capital_pct') value = parseFloat(value) || 0
    await onConfigSave(strategy.strategy_id, { [field]: value })
    setEditMode(null)
  }

  return (
    <div className={cn(
      'border bg-[var(--color-card)] transition-all',
      hasPlugin ? 'border-[var(--color-accent)]/30' : 'border-[var(--color-border)]',
      expanded && 'ring-1 ring-[var(--color-accent)]/20'
    )}>
      {/* Header */}
      <div className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="mono text-[9px] font-medium px-1 py-0.5 border border-[var(--color-border)] bg-[var(--color-muted)] shrink-0 whitespace-nowrap">
              {strategy.strategy_id}
            </span>
            <span
            onClick={() => onNavigate(strategy.strategy_id)}
            className="text-[11px] font-medium truncate cursor-pointer hover:text-[var(--color-accent)] transition-colors"
          >
            {strategy.display_name}
          </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {hasPlugin ? (
              <span className="flex items-center gap-0.5 text-[8px] font-medium px-1 py-0.5 bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30">
                <Code2 size={8} /> BUILT
              </span>
            ) : (
              <span className="flex items-center gap-0.5 text-[8px] font-medium px-1 py-0.5 bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]">
                PLANNED
              </span>
            )}
            <Badge variant={strategy.mode === 'live' ? 'live' : 'paper'} className="text-[8px]">
              {(strategy.mode || 'paper').toUpperCase()}
            </Badge>
          </div>
        </div>

        {/* Description */}
        <p className="text-[10px] text-[var(--color-muted-foreground)] leading-relaxed">
          {strategy.description}
        </p>

        {/* Node + Category */}
        <div className="flex items-center gap-2 text-[10px] text-[var(--color-muted-foreground)]">
          {node && (
            <>
              <Server size={10} className="shrink-0 opacity-60" />
              <span className="truncate">{node.name}</span>
              <span className="opacity-40">|</span>
            </>
          )}
          <span className="truncate">{strategy.category_label}</span>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-3 text-[10px]">
          <div>
            <span className="text-[var(--color-muted-foreground)]">WR </span>
            <span className="mono font-medium" style={{ color: winRate > 85 ? '#1D9E75' : winRate > 70 ? '#EF9F27' : '#E24B4A' }}>
              {winRate ? `${winRate}%` : '--'}
            </span>
          </div>
          <div>
            <span className="text-[var(--color-muted-foreground)]">PnL </span>
            <span className="mono font-medium" style={{ color: totalPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-[var(--color-muted-foreground)]">Trades </span>
            <span className="mono font-medium">{totalTrades}</span>
            {pendingTrades > 0 && (
              <span className="ml-1 text-[9px] text-[#EF9F27]">({pendingTrades} open)</span>
            )}
          </div>
          {strategy.version_tag && (
            <div>
              <span className="text-[var(--color-muted-foreground)]">Ver </span>
              <span className="mono font-medium">{strategy.version_tag}</span>
            </div>
          )}
        </div>

        {/* Toggle + Expand */}
        <div className="pt-1.5 border-t border-[var(--color-border)] flex items-center justify-between">
          <button
            onClick={() => onToggle(strategy.strategy_id)}
            className={cn(
              'px-2.5 py-1 text-[9px] font-medium transition-colors flex items-center gap-1',
              strategy.enabled
                ? 'bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30'
                : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]'
            )}
          >
            {strategy.enabled ? <><Play size={9} /> ON</> : <><Pause size={9} /> OFF</>}
          </button>
          <button
            onClick={() => onExpand(strategy.strategy_id)}
            className="flex items-center gap-1 text-[9px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors"
          >
            <Settings2 size={10} />
            Config
            {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          </button>
        </div>
      </div>

      {/* Expanded Config Panel */}
      {expanded && (
        <div className="border-t border-[var(--color-border)] bg-[var(--color-muted)]/30 p-3 space-y-2.5 text-[10px]">
          {/* Mode toggle */}
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-muted-foreground)]">Mode</span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => onConfigSave(strategy.strategy_id, { mode: 'paper' })}
                className={cn(
                  'px-2 py-0.5 text-[9px] font-medium border transition-colors',
                  strategy.mode === 'paper'
                    ? 'bg-[#1D9E75]/10 text-[#1D9E75] border-[#1D9E75]/30'
                    : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]'
                )}
              >
                <FlaskConical size={9} className="inline mr-0.5" /> Paper
              </button>
              <button
                onClick={() => onConfigSave(strategy.strategy_id, { mode: 'live' })}
                className={cn(
                  'px-2 py-0.5 text-[9px] font-medium border transition-colors',
                  strategy.mode === 'live'
                    ? 'bg-[#FF002B]/10 text-[#FF002B] border-[#FF002B]/30'
                    : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]'
                )}
              >
                <Rocket size={9} className="inline mr-0.5" /> Live
              </button>
            </div>
          </div>

          {/* Kelly multiplier */}
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-muted-foreground)]">Kelly Multiplier</span>
            {editMode === 'kelly' ? (
              <div className="flex items-center gap-1">
                <input
                  type="number" step="0.05" min="0" max="1"
                  value={editVal}
                  onChange={e => setEditVal(e.target.value)}
                  className="w-16 px-1 py-0.5 text-[10px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                  autoFocus
                />
                <button onClick={() => saveField('kelly_multiplier')} className="text-[#1D9E75] text-[9px]">Save</button>
                <button onClick={() => setEditMode(null)} className="text-[var(--color-muted-foreground)]"><X size={10} /></button>
              </div>
            ) : (
              <button
                onClick={() => { setEditMode('kelly'); setEditVal(strategy.kelly_multiplier ?? 1) }}
                className="mono font-medium hover:text-[var(--color-accent)] transition-colors"
              >
                {strategy.kelly_multiplier ?? 1.0}
              </button>
            )}
          </div>

          {/* Max capital % */}
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-muted-foreground)]">Max Capital %</span>
            {editMode === 'cap' ? (
              <div className="flex items-center gap-1">
                <input
                  type="number" step="0.05" min="0" max="1"
                  value={editVal}
                  onChange={e => setEditVal(e.target.value)}
                  className="w-16 px-1 py-0.5 text-[10px] mono bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                  autoFocus
                />
                <button onClick={() => saveField('max_capital_pct')} className="text-[#1D9E75] text-[9px]">Save</button>
                <button onClick={() => setEditMode(null)} className="text-[var(--color-muted-foreground)]"><X size={10} /></button>
              </div>
            ) : (
              <button
                onClick={() => { setEditMode('cap'); setEditVal(strategy.max_capital_pct ?? 0) }}
                className="mono font-medium hover:text-[var(--color-accent)] transition-colors"
              >
                {((strategy.max_capital_pct ?? 0) * 100).toFixed(0)}%
              </button>
            )}
          </div>

          {/* Notes */}
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-muted-foreground)]">Notes</span>
            {editMode === 'notes' ? (
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={editVal}
                  onChange={e => setEditVal(e.target.value)}
                  className="w-40 px-1 py-0.5 text-[10px] bg-[var(--color-background)] border border-[var(--color-border)] text-[var(--color-foreground)]"
                  placeholder="Add a note..."
                  autoFocus
                />
                <button onClick={() => saveField('notes')} className="text-[#1D9E75] text-[9px]">Save</button>
                <button onClick={() => setEditMode(null)} className="text-[var(--color-muted-foreground)]"><X size={10} /></button>
              </div>
            ) : (
              <button
                onClick={() => { setEditMode('notes'); setEditVal(strategy.notes || '') }}
                className="text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors truncate max-w-[160px]"
              >
                {strategy.notes || 'Add note...'}
              </button>
            )}
          </div>

          {/* Version + timestamps */}
          <div className="pt-1.5 border-t border-[var(--color-border)] space-y-1 text-[9px] text-[var(--color-muted-foreground)]">
            <div className="flex justify-between">
              <span>Version</span>
              <span className="mono">{strategy.version_tag || 'v1'}</span>
            </div>
            <div className="flex justify-between">
              <span>File</span>
              <span className="mono">{strategy.file_name || `${strategy.strategy_id}.py`}</span>
            </div>
            <div className="flex justify-between">
              <span>Plugin Status</span>
              <span className={hasPlugin ? 'text-[#1D9E75]' : 'text-[var(--color-muted-foreground)]'}>
                {hasPlugin ? 'Loaded & Wired' : 'Not built yet'}
              </span>
            </div>
            {strategy.last_trade_at && (
              <div className="flex justify-between">
                <span>Last Trade</span>
                <span className="mono">{new Date(strategy.last_trade_at).toLocaleString()}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span>Uploaded</span>
              <span className="mono">{strategy.uploaded_at ? new Date(strategy.uploaded_at).toLocaleDateString() : '--'}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function StrategiesPage() {
  const { mode } = useMode()
  const navigate = useNavigate()
  const { data, refetch } = usePolling(useCallback(() => api.getStrategies(), []), 5000)
  const strategies = data?.strategies || []
  const [expandedId, setExpandedId] = useState(null)

  const handleToggle = async (strategyId) => {
    await api.toggleStrategy(strategyId)
    refetch()
  }

  const handleExpand = (strategyId) => {
    setExpandedId(expandedId === strategyId ? null : strategyId)
  }

  const handleConfigSave = async (strategyId, config) => {
    await api.updateStrategyConfig(strategyId, config)
    refetch()
  }

  // Group by category
  const byCategory = CATEGORIES.map(cat => ({
    ...cat,
    strategies: strategies.filter(s => s.category === cat.key),
  }))

  const builtCount = strategies.filter(s => s.has_plugin).length
  const enabledCount = strategies.filter(s => s.enabled).length
  const liveCount = strategies.filter(s => s.mode === 'live').length

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-medium">Strategy Plugins</h1>
          <p className="text-[11px] text-[var(--color-muted-foreground)] mt-1">
            Live from Supabase. Click Config to customize each strategy.
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <StatusDot active={builtCount > 0} label={`${builtCount} built`} />
          <StatusDot active={enabledCount > 0} label={`${enabledCount} enabled`} />
          <StatusDot active={liveCount > 0} label={`${liveCount} live`} />
          <span className="mono text-[var(--color-muted-foreground)]">{strategies.length} total</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-[var(--color-muted-foreground)]">
        <span className="flex items-center gap-1">
          <span className="inline-flex items-center gap-0.5 text-[8px] font-medium px-1 py-0.5 bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30">
            <Code2 size={8} /> BUILT
          </span>
          = .py plugin exists, loaded by scanner
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-flex text-[8px] font-medium px-1 py-0.5 bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]">
            PLANNED
          </span>
          = DB record only, plugin not built yet
        </span>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {byCategory.map(cat => (
          <div key={cat.key} className="space-y-3">
            <div style={{ borderTopWidth: '3px', borderTopStyle: 'solid', borderColor: cat.color }} className="pt-3">
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: cat.color }}>
                  {cat.code}
                </span>
                <span className="text-[11px] font-medium text-[var(--color-foreground)] truncate">{cat.label}</span>
              </div>
              <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">
                {cat.strategies.length} strategies
                {cat.strategies.some(s => s.has_plugin) && (
                  <span className="text-[#1D9E75]"> · {cat.strategies.filter(s => s.has_plugin).length} built</span>
                )}
              </div>
            </div>
            {cat.strategies.map(s => (
              <StrategyCard
                key={s.strategy_id}
                strategy={s}
                onToggle={handleToggle}
                onExpand={handleExpand}
                expanded={expandedId === s.strategy_id}
                onConfigSave={handleConfigSave}
                onNavigate={(id) => navigate(`/strategies/${id}`)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
