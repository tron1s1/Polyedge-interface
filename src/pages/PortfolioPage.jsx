import { useCallback } from 'react'
import { useMode } from '../context/ModeContext'
import { formatUSD, cn } from '../utils/formatters'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import MetricCard from '../components/ui/MetricCard'
import Badge from '../components/ui/Badge'

const CATEGORY_COLORS = {
  A: '#1D9E75',
  B: '#185FA5',
  C: '#8B5CF6',
  D: '#EF9F27',
}

function formatBalance(balance, currency) {
  if (currency === 'INR') return `₹${balance.toLocaleString('en-IN')}`
  return `$${balance.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

export default function PortfolioPage() {
  const { isPaper } = useMode()
  const mode = isPaper ? 'paper' : 'live'

  const { data: portData } = usePolling(
    useCallback(() => api.getPortfolio(mode), [mode]),
    10000
  )
  const { data: riskData } = usePolling(useCallback(() => api.getRiskCurrent(), []), 10000)
  const { data: overview } = usePolling(useCallback(() => api.getOverview(), []), 10000)

  const regime = riskData?.regime || 'UNKNOWN'
  const snapshot = riskData?.snapshot || {}
  const todayPnl = overview?.today_pnl_usdc || 0

  // ── Paper mode data ─────────────────────────────────────────────────────
  const paperStrategies = portData?.paper_strategies || []
  const summary = portData?.summary || {}
  const totalPaperCapital = summary.total_allocated_usdc || 0
  const totalPaperPnl = summary.total_pnl_usdc || 0
  const paperWinRate = summary.win_rate || 0

  // ── Live mode data ───────────────────────────────────────────────────────
  const pools = portData?.pools || []
  const totalUsdc = pools.reduce((s, p) => s + (p.current_balance || 0), 0)
  const peakUsdc = snapshot.peak_capital_usdc || totalUsdc
  const drawdownPct = snapshot.drawdown_pct || 0
  const poolsWithPct = pools.map(p => ({
    ...p,
    pct: totalUsdc > 0 ? Math.round((p.current_balance || 0) / totalUsdc * 100) : 0,
  }))

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">Portfolio</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper Trading' : 'Live Trading'}</Badge>
        <span className="text-[11px] text-[var(--color-muted-foreground)]">
          {isPaper ? 'Showing simulated paper trade data' : 'Showing live capital pools'}
        </span>
      </div>

      {/* ── PAPER MODE ─────────────────────────────────────────────────── */}
      {isPaper && (
        <>
          {/* Summary metrics */}
          <div className="grid grid-cols-4 gap-4">
            <MetricCard
              label="Total Paper Capital"
              value={`${formatUSD(totalPaperCapital)} USDC`}
            />
            <MetricCard
              label="Total Paper P&L"
              value={`${totalPaperPnl >= 0 ? '+' : ''}${formatUSD(totalPaperPnl)}`}
              valueColor={totalPaperPnl >= 0 ? '#1D9E75' : '#E24B4A'}
            />
            <MetricCard
              label="Paper Win Rate"
              value={`${paperWinRate.toFixed(1)}%`}
              valueColor={paperWinRate >= 50 ? '#1D9E75' : '#EF9F27'}
            />
            <MetricCard
              label="Paper Trades"
              value={String(summary.total_trades || 0)}
              detail={`${summary.wins || 0}W / ${summary.losses || 0}L`}
            />
          </div>

          {/* Per-strategy allocation table */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
              Strategy Allocations — Paper
            </div>
            {paperStrategies.length > 0 ? (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-[var(--color-border)]">
                    {['Strategy', 'Mode', 'Capital', 'P&L', 'Win Rate', 'Status'].map(h => (
                      <th key={h} className={cn(
                        'py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]',
                        ['Capital', 'P&L', 'Win Rate'].includes(h) ? 'text-right' : 'text-left'
                      )}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paperStrategies.map(s => {
                    const color = CATEGORY_COLORS[s.category?.[0]] || '#555'
                    const pnlColor = s.total_pnl_usdc > 0 ? '#1D9E75' : s.total_pnl_usdc < 0 ? '#E24B4A' : 'var(--color-muted-foreground)'
                    return (
                      <tr key={s.strategy_id} className="border-b border-[var(--color-border)] last:border-0">
                        <td className="py-2.5 px-2">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                            <span className="font-medium">{s.display_name || s.strategy_id}</span>
                          </div>
                          <div className="mono text-[9px] text-[var(--color-muted-foreground)] ml-4">{s.strategy_id}</div>
                        </td>
                        <td className="py-2.5 px-2">
                          <Badge variant={s.mode === 'live' ? 'live' : 'paper'}>{(s.mode || 'paper').toUpperCase()}</Badge>
                        </td>
                        <td className="py-2.5 px-2 mono text-right font-medium">
                          {s.max_capital > 0 ? `$${s.max_capital.toLocaleString()}` : <span className="text-[var(--color-muted-foreground)]">—</span>}
                        </td>
                        <td className="py-2.5 px-2 mono text-right font-medium" style={{ color: pnlColor }}>
                          {s.total_pnl_usdc !== 0 ? `${s.total_pnl_usdc >= 0 ? '+' : ''}$${s.total_pnl_usdc.toFixed(2)}` : '—'}
                        </td>
                        <td className="py-2.5 px-2 mono text-right">
                          {s.win_rate > 0 ? `${s.win_rate.toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-2.5 px-2">
                          <span className={cn(
                            'text-[9px] font-medium px-1.5 py-0.5',
                            s.enabled
                              ? 'bg-[#1D9E75]/10 text-[#1D9E75] border border-[#1D9E75]/30'
                              : 'bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border border-[var(--color-border)]'
                          )}>
                            {s.enabled ? 'Running' : 'Stopped'}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-8 text-[11px] text-[var(--color-muted-foreground)]">
                No strategies found. Add strategies and allocate paper capital via the Strategies page.
              </div>
            )}
          </div>

          {/* Regime info */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">Market Regime</div>
            <div className="text-[11px] text-[var(--color-muted-foreground)]">
              Regime: <span className="mono font-medium text-[var(--color-foreground)]">{regime}</span>
              {' · '}Kelly: <span className="mono font-medium text-[var(--color-foreground)]">{(snapshot.kelly_multiplier || 0.75).toFixed(2)}x</span>
              <span className="ml-3 text-[10px]">Paper trades follow the same regime multipliers as live.</span>
            </div>
          </div>
        </>
      )}

      {/* ── LIVE MODE ──────────────────────────────────────────────────── */}
      {!isPaper && (
        <>
          {/* Summary metrics */}
          <div className="grid grid-cols-4 gap-4">
            <MetricCard label="Total Portfolio" value={`${formatUSD(totalUsdc)} USDC`} />
            <MetricCard
              label="Today's P&L"
              value={`${todayPnl >= 0 ? '+' : ''}${formatUSD(todayPnl)}`}
              valueColor={todayPnl >= 0 ? '#1D9E75' : '#E24B4A'}
            />
            <MetricCard
              label="Drawdown"
              value={`${drawdownPct.toFixed(1)}%`}
              valueColor={drawdownPct > 5 ? '#E24B4A' : '#1D9E75'}
              detail="From all-time high"
            />
            <MetricCard label="Peak" value={formatUSD(peakUsdc)} detail="All-time high (USDC)" />
          </div>

          {/* Capital Pools table */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
              Capital Pools ({pools.length})
            </div>
            {pools.length > 0 ? (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-[var(--color-border)]">
                    {['Pool', 'Currency', 'Exchange', 'Balance', 'Allocation', '%'].map(h => (
                      <th key={h} className={cn(
                        'py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]',
                        h === 'Balance' || h === '%' ? 'text-right' : 'text-left'
                      )}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {poolsWithPct.map(pool => (
                    <tr key={pool.pool_id || pool.id} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 shrink-0 rounded-full" style={{ backgroundColor: pool.color || '#185FA5' }} />
                          <span className="text-[12px] font-medium">{pool.display_name || pool.pool_id}</span>
                        </div>
                        {pool.note && <div className="text-[10px] text-[var(--color-muted-foreground)] ml-4 mt-0.5">{pool.note}</div>}
                      </td>
                      <td className="py-2.5 px-2 mono text-[var(--color-muted-foreground)]">{pool.currency || 'USDC'}</td>
                      <td className="py-2.5 px-2 text-[var(--color-muted-foreground)]">{pool.exchange || '--'}</td>
                      <td className="py-2.5 px-2 mono text-right font-medium">{formatBalance(pool.current_balance || 0, pool.currency || 'USDC')}</td>
                      <td className="py-2.5 px-2 w-[180px]">
                        <div className="w-full h-1.5 bg-[var(--color-muted)] rounded-sm overflow-hidden">
                          <div className="h-full rounded-sm transition-all" style={{ width: `${Math.max(pool.pct, 0)}%`, backgroundColor: pool.color || '#185FA5' }} />
                        </div>
                      </td>
                      <td className="py-2.5 px-2 mono text-right text-[var(--color-muted-foreground)]">{pool.pct > 0 ? `${pool.pct}%` : '--'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-6 text-[11px] text-[var(--color-muted-foreground)]">
                No live capital pools found. Switch to Paper mode to view paper trading data.
              </div>
            )}
          </div>

          {/* Regime info */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">Current Regime</div>
            <div className="text-[11px] text-[var(--color-muted-foreground)]">
              Regime: <span className="mono font-medium text-[var(--color-foreground)]">{regime}</span>
              {' · '}Kelly: <span className="mono font-medium text-[var(--color-foreground)]">{(snapshot.kelly_multiplier || 0.75).toFixed(2)}x</span>
            </div>
            <div className="mt-2 pt-3 border-t border-[var(--color-border)] text-[10px] text-[var(--color-muted-foreground)]">
              Regime changes auto-adjust allocations — see Risk page.
            </div>
          </div>
        </>
      )}
    </div>
  )
}
