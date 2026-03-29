import { useCallback, useState, useEffect } from 'react'
import { useMode } from '../context/ModeContext'
import { REGIME_COLORS, CATEGORY_MAP, NODE_MAP } from '../utils/constants'
import { formatUSD } from '../utils/formatters'
import { api } from '../lib/api'
import { usePolling, useRealtimeTable } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { Activity, Radio, Play, TrendingUp } from 'lucide-react'

// ── System Status Bar ────────────────────────────────────────────────────────

function SystemStatusBar({ nodes, regime, kelly }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-2.5 flex items-center gap-6 text-[11px]">
      {nodes.map(node => (
        <div key={node.node_id} className="flex items-center gap-1.5">
          <span
            className="inline-block w-2 h-2 shrink-0"
            style={{
              backgroundColor: node.status === 'online' ? '#1D9E75' : '#6B7280',
              borderRadius: '50%',
              boxShadow: node.status === 'online' ? '0 0 6px #1D9E7580' : 'none',
            }}
          />
          <span className="text-[var(--color-muted-foreground)]">{node.display_name?.split('—')[1]?.trim() || node.node_id}</span>
        </div>
      ))}
      <div className="w-px h-4 bg-[var(--color-border)]" />
      <div className="flex items-center gap-1.5">
        <span className="text-[var(--color-muted-foreground)] uppercase tracking-wider">Regime</span>
        <span className="mono font-medium" style={{ color: REGIME_COLORS[regime] || '#888' }}>
          {(regime || 'UNKNOWN').replace(/_/g, ' ')}
        </span>
      </div>
      <div className="w-px h-4 bg-[var(--color-border)]" />
      <div className="flex items-center gap-1.5">
        <span className="text-[var(--color-muted-foreground)] uppercase tracking-wider">Kelly</span>
        <span className="mono font-medium">{kelly || '0.75'}x</span>
      </div>
      <div className="ml-auto flex items-center gap-1.5">
        <Activity size={12} className="text-[var(--color-muted-foreground)]" />
        <span className="text-[var(--color-muted-foreground)]">
          {nodes.filter(n => n.status === 'online').length}/{nodes.length} nodes online
        </span>
      </div>
    </div>
  )
}

// ── Strategy Row ─────────────────────────────────────────────────────────────

function StrategyPnlCell({ strategy, openPositions }) {
  const closedPnl = strategy.total_pnl_usdc ?? 0
  const stratPositions = openPositions.filter(p => p.strategy_id === strategy.strategy_id)

  const [livePnl, setLivePnl] = useState(closedPnl)

  useEffect(() => {
    if (stratPositions.length === 0) {
      setLivePnl(closedPnl)
      return
    }
    // closedPnl from API already includes open positions' collected payments (from funding_payments).
    // To avoid double-counting: subtract the already-counted collected, then add back the full
    // live accrual (collected + continuous rate × seconds since open).
    const alreadyCounted = stratPositions.reduce((s, p) => s + (p.collected_pnl || 0), 0)
    const closedOnly = closedPnl - alreadyCounted  // PnL from truly closed positions only
    const calcs = stratPositions.map(pos => {
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
  }, [strategy.strategy_id, closedPnl, stratPositions.map(p => p.id + p.collected_pnl).join(',')])

  return (
    <div className="w-[90px] shrink-0 text-right">
      <span className="mono text-[11px] font-medium tabular-nums" style={{ color: livePnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
        {livePnl >= 0 ? '+' : ''}{formatUSD(livePnl)}
      </span>
      {stratPositions.length > 0 && (
        <div className="text-[8px] text-[#EF9F27]">{stratPositions.length} open</div>
      )}
    </div>
  )
}

function StrategyRow({ strategy, openPositions }) {
  const nodeLabel = NODE_MAP[strategy.node_id]?.name?.split(' — ')[1] || strategy.node_id
  const catColor = CATEGORY_MAP[strategy.category]?.color || '#888'
  const winRate = strategy.win_rate ?? 0

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-muted)]/30">
      <span className="w-1.5 h-1.5 shrink-0 inline-block" style={{ backgroundColor: catColor, borderRadius: '50%' }} />
      <span className="mono text-[9px] font-medium px-1 py-0.5 border border-[var(--color-border)] bg-[var(--color-muted)] shrink-0 w-[110px] truncate text-center">
        {strategy.strategy_id}
      </span>
      <span className="text-[11px] font-medium truncate w-[160px] shrink-0">{strategy.display_name}</span>
      <span className="text-[10px] text-[var(--color-muted-foreground)] w-[70px] shrink-0">{nodeLabel}</span>
      <StrategyPnlCell strategy={strategy} openPositions={openPositions} />
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <div className="w-[80px] h-1.5 bg-[var(--color-muted)] shrink-0">
          <div className="h-full" style={{ width: `${Math.min(winRate, 100)}%`, backgroundColor: winRate > 85 ? '#1D9E75' : winRate > 70 ? '#EF9F27' : '#E24B4A' }} />
        </div>
        <span className="mono text-[10px] font-medium shrink-0" style={{ color: winRate > 85 ? '#1D9E75' : winRate > 70 ? '#EF9F27' : '#E24B4A' }}>
          {winRate ? `${winRate}%` : '--'}
        </span>
      </div>
      <Badge variant={strategy.enabled ? 'live' : 'paper'} className="text-[8px] shrink-0">
        {strategy.mode?.toUpperCase() || 'PAPER'}
      </Badge>
    </div>
  )
}

// ── Scanner Row ──────────────────────────────────────────────────────────────

function ScannerRow({ node }) {
  const isOnline = node.status === 'online'
  return (
    <div className="flex items-center gap-4 px-3 py-2.5 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2 w-[160px] shrink-0">
        <span className="w-2 h-2 shrink-0 inline-block" style={{ backgroundColor: isOnline ? '#1D9E75' : '#6B7280', borderRadius: '50%', boxShadow: isOnline ? '0 0 6px #1D9E7580' : 'none' }} />
        <span className="text-[11px] font-medium">{node.display_name}</span>
      </div>
      {isOnline ? (
        <>
          <div className="flex items-center gap-1 w-[120px] shrink-0">
            <span className="text-[10px] text-[var(--color-muted-foreground)]">Strategies:</span>
            <span className="mono text-[11px] font-medium">{node.strategies?.length || 0}</span>
          </div>
          <div className="flex items-center gap-1 w-[100px] shrink-0">
            <span className="text-[10px] text-[var(--color-muted-foreground)]">Exchange:</span>
            <span className="mono text-[11px] font-medium">{node.primary_exchange}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-[10px]">
              <Radio size={10} className="text-[var(--color-accent)] shrink-0" />
              <span className="text-[var(--color-muted-foreground)]">
                Slot: <span className="text-[var(--color-foreground)] font-medium">{node.slot || 'green'}</span>
              </span>
            </div>
          </div>
        </>
      ) : (
        <div className="flex items-center gap-3 flex-1">
          <span className="text-[11px] text-[var(--color-muted-foreground)]">OFFLINE</span>
          <button className="text-[10px] font-medium text-[var(--color-accent)] hover:underline flex items-center gap-1">
            <Play size={10} /> Start Node
          </button>
        </div>
      )}
    </div>
  )
}

// ── Live P&L Ticker (ticks every second based on APR × time) ─────────────────

function useLivePnl(pos) {
  const [pnl, setPnl] = useState(pos.collected_pnl || 0)

  useEffect(() => {
    const openedAt = new Date(pos.opened_at).getTime()
    const aprAbs = Math.abs(pos.entry_apr || 0) // already in %
    const perSecRate = (aprAbs / 100) / (365 * 24 * 3600) * (pos.perp_size_usdc || pos.size_usdc / 2)

    const tick = () => {
      const secondsElapsed = (Date.now() - openedAt) / 1000
      const accrued = perSecRate * secondsElapsed
      setPnl((pos.collected_pnl || 0) + accrued)
    }

    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [pos.id, pos.collected_pnl, pos.entry_apr, pos.opened_at, pos.perp_size_usdc, pos.size_usdc])

  return pnl
}

function LiveTotalPnl({ positions }) {
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
    <span className="text-[var(--color-muted-foreground)]">Live P&L: <span className="mono font-medium tabular-nums" style={{ color: total >= 0 ? '#1D9E75' : '#E24B4A' }}>{total >= 0 ? '+' : ''}{formatUSD(total)}</span></span>
  )
}

function LivePnlCell({ pos }) {
  const pnl = useLivePnl(pos)
  return (
    <div className="flex flex-col items-end flex-1">
      <span className="mono text-[11px] font-medium tabular-nums" style={{ color: pnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
        {pnl >= 0 ? '+' : ''}{formatUSD(pnl)}
      </span>
      {pos.payments_received > 0 && (
        <span className="text-[9px] text-[var(--color-muted-foreground)]">{pos.payments_received} payments</span>
      )}
    </div>
  )
}

// ── Open Positions Panel ─────────────────────────────────────────────────────

function OpenPositions({ positions, totalUnrealisedPnl, totalDeployed }) {
  if (!positions || positions.length === 0) {
    return (
      <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <TrendingUp size={14} className="text-[var(--color-accent)]" />
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Open Positions</div>
          <Badge variant="paper" className="text-[8px]">0 ACTIVE</Badge>
        </div>
        <div className="px-4 py-5 text-[11px] text-[var(--color-muted-foreground)]">No open positions yet.</div>
      </div>
    )
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-[var(--color-accent)]" />
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Open Positions</div>
          <Badge variant="live" className="text-[8px]">{positions.length} ACTIVE</Badge>
        </div>
        <div className="flex items-center gap-4 text-[11px]">
          <span className="text-[var(--color-muted-foreground)]">Deployed: <span className="mono font-medium text-[var(--color-foreground)]">{formatUSD(totalDeployed)}</span></span>
          <LiveTotalPnl positions={positions} />
        </div>
      </div>
      {/* Header row */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-muted)]/30 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        <span className="w-[110px] shrink-0">Symbol</span>
        <span className="w-[110px] shrink-0">Strategy</span>
        <span className="w-[70px] shrink-0">Direction</span>
        <span className="w-[80px] shrink-0 text-right">Size</span>
        <span className="w-[90px] shrink-0 text-right">APR</span>
        <span className="w-[70px] shrink-0 text-right">Held</span>
        <span className="flex-1 text-right">Live P&L</span>
      </div>
      {positions.map(pos => (
        <div key={pos.id} className="flex items-center gap-3 px-3 py-2 border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-muted)]/20">
          <span className="mono text-[11px] font-medium w-[110px] shrink-0">{pos.symbol}</span>
          <span className="text-[10px] text-[var(--color-muted-foreground)] w-[110px] shrink-0 truncate">{pos.strategy_id}</span>
          <span className="text-[10px] w-[70px] shrink-0 uppercase" style={{ color: pos.direction?.toLowerCase().includes('neg') || pos.direction?.toLowerCase().includes('short') ? '#EF9F27' : '#1D9E75' }}>
            {pos.direction?.replace(/_/g, ' ') || '—'}
          </span>
          <span className="mono text-[11px] w-[80px] shrink-0 text-right">{formatUSD(pos.size_usdc)}</span>
          <span className="mono text-[11px] w-[90px] shrink-0 text-right" style={{ color: pos.entry_apr < 0 ? '#EF9F27' : '#1D9E75' }}>
            {pos.entry_apr !== 0 ? `${pos.entry_apr.toFixed(2)}%` : '—'}
          </span>
          <span className="mono text-[10px] text-[var(--color-muted-foreground)] w-[70px] shrink-0 text-right">{pos.hours_held}h</span>
          <LivePnlCell pos={pos} />
        </div>
      ))}
    </div>
  )
}

// ── Main Dashboard Page ──────────────────────────────────────────────────────

export default function DashboardPage() {
  const { isPaper } = useMode()

  const mode = isPaper ? 'paper' : 'live'
  const { data: overview } = usePolling(useCallback(() => api.getOverview(mode), [mode]), 5000)
  const { data: stratData } = usePolling(useCallback(() => api.getStrategies(), []), 10000)
  const { data: posData } = usePolling(useCallback(() => api.getPositions(mode), [mode]), 10000)

  // Realtime: update on new scanner cycles and node heartbeats
  useRealtimeTable('scanner_cycles', {
    onInsert: () => {} // triggers re-render via polling
  })
  useRealtimeTable('nodes', {
    onUpdate: () => {}
  })

  const nodes = overview?.nodes || []
  const pools = overview?.capital_pools || []
  const regime = overview?.regime || 'UNKNOWN'
  const todayPnl = overview?.today_pnl_usdc || 0
  const todayTrades = overview?.today_trades || 0
  const strategies = stratData?.strategies || []
  const totalUsdc = overview?.total_capital_usdc || pools.reduce((s, p) => s + (p.current_balance || 0), 0)
  const positions = posData?.positions || []
  const totalUnrealisedPnl = posData?.total_unrealised_pnl || 0
  const totalDeployed = posData?.total_deployed_usdc || 0

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3">
        <Badge variant={isPaper ? 'paper' : 'live'} className="text-[12px] px-3 py-1">
          {isPaper ? 'Paper Trading Mode' : 'Live Trading Mode'}
        </Badge>
        <span className="text-[11px] text-[var(--color-muted-foreground)]">
          {isPaper ? 'All trades are simulated. No real capital at risk.' : 'Real funds are being deployed. Kill switches active.'}
        </span>
      </div>

      <SystemStatusBar nodes={nodes} regime={regime} />

      {/* Total Portfolio + Today's PnL */}
      <div className="grid grid-cols-2 gap-4">
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">{isPaper ? 'Paper Capital' : 'Total Portfolio'}</div>
          <div className="flex items-baseline gap-3">
            <span className="mono text-[28px] font-medium">{formatUSD(totalUsdc)}</span>
            <span className="text-[14px] text-[var(--color-muted-foreground)]">USDC</span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-[var(--color-muted-foreground)]">
            <span>Pools: <span className="mono font-medium text-[var(--color-foreground)]">{pools.length}</span></span>
          </div>
        </div>

        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Today's PnL</div>
          <div className="flex items-baseline gap-3">
            <span className="mono text-[28px] font-medium" style={{ color: todayPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
              {todayPnl >= 0 ? '+' : ''}{formatUSD(todayPnl)}
            </span>
          </div>
          <div className="text-[11px] text-[var(--color-muted-foreground)]">
            Trades today: <span className="mono font-medium text-[var(--color-foreground)]">{todayTrades}</span>
          </div>
        </div>
      </div>

      {/* Open Positions */}
      <OpenPositions positions={positions} totalUnrealisedPnl={totalUnrealisedPnl} totalDeployed={totalDeployed} />

      {/* Active Strategies */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Strategies</div>
            <Badge variant="paper" className="text-[8px]">{strategies.length} REGISTERED</Badge>
          </div>
          <span className="text-[10px] text-[var(--color-muted-foreground)]">
            Live data from Supabase strategy_plugins table
          </span>
        </div>
        <div className="flex items-center gap-3 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-muted)]/30 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          <span className="w-1.5 shrink-0" />
          <span className="w-[110px] shrink-0 text-center">ID</span>
          <span className="w-[180px] shrink-0">Name</span>
          <span className="w-[70px] shrink-0">Node</span>
          <span className="w-[90px] shrink-0 text-right">Live P&L</span>
          <span className="flex-1">Win Rate</span>
          <span className="w-[58px] shrink-0 text-center">Mode</span>
        </div>
        <div className="max-h-[400px] overflow-y-auto">
          {strategies.map(s => <StrategyRow key={s.strategy_id} strategy={s} openPositions={positions} />)}
        </div>
      </div>

      {/* Scanner Live Feed (nodes) */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <Radio size={14} className="text-[var(--color-accent)]" />
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Node Status</div>
        </div>
        {nodes.map(node => <ScannerRow key={node.node_id} node={node} />)}
      </div>
    </div>
  )
}
