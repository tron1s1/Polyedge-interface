import { useState } from 'react'
import { useMode } from '../../context/ModeContext'
import { getMockTrades, getTradeStats } from '../../data/mockTrades'
import DataTable from '../ui/DataTable'
import MetricCard from '../ui/MetricCard'
import { formatCurrency, formatPercent, formatMs, formatRelativeTime } from '../../utils/formatters'

export default function TradesTab({ strategyId }) {
  const { mode, isPaper } = useMode()
  const [filter, setFilter] = useState('all')
  const allTrades = getMockTrades(strategyId, mode)
  const stats = getTradeStats(allTrades)

  const filtered = filter === 'all' ? allTrades :
    filter === 'wins' ? allTrades.filter(t => t.status === 'won') :
    filter === 'losses' ? allTrades.filter(t => t.status === 'lost') :
    allTrades.filter(t => t.status === 'pending')

  const columns = [
    { key: 'timestamp', label: 'Time', width: 90, render: (v) => <span className="mono text-[var(--color-muted-foreground)]">{formatRelativeTime(v)}</span> },
    { key: 'market', label: 'Market', width: 180 },
    { key: 'direction', label: 'Dir', width: 50, render: (v) => <span className="mono font-medium" style={{ color: v === 'YES' ? '#1D9E75' : '#E24B4A' }}>{v}</span> },
    { key: 'entryPrice', label: 'Entry', width: 60, render: (v) => <span className="mono">${v}</span> },
    { key: 'size', label: 'Size', width: 70, render: (v) => <span className="mono">${v}</span> },
    ...(strategyId === 'ai-news' ? [{ key: 'confidence', label: 'AI Conf', width: 70, render: (v) => v ? <span className="mono">{v}</span> : '—' }] : []),
    { key: 'edge', label: 'Edge', width: 60, render: (v) => <span className="mono">{(v * 100).toFixed(0)}%</span> },
    { key: 'latency', label: 'Latency', width: 70, render: (v) => <span className="mono">{formatMs(v)}</span> },
    { key: 'pnl', label: 'P&L', width: 80, render: (v) => <span className="mono font-medium" style={{ color: v >= 0 ? '#1D9E75' : '#E24B4A' }}>{formatCurrency(v)}</span> },
    { key: 'status', label: 'Status', width: 70, render: (v) => <span className="uppercase text-[10px]" style={{ color: v === 'won' ? '#1D9E75' : v === 'lost' ? '#E24B4A' : '#EF9F27' }}>{v}</span> },
    { key: 'version', label: 'Ver', width: 50, render: (v) => <span className="mono text-[var(--color-muted-foreground)]">{v}</span> },
  ]

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-5 gap-3">
        <MetricCard label="Total P&L" value={formatCurrency(stats.totalPnl)} valueColor={stats.totalPnl >= 0 ? '#1D9E75' : '#E24B4A'} className="!p-3" />
        <MetricCard label="Win Rate" value={formatPercent(stats.winRate)} className="!p-3" />
        <MetricCard label="Total Trades" value={String(stats.totalTrades)} className="!p-3" />
        <MetricCard label="Best Trade" value={formatCurrency(stats.bestTrade)} valueColor="#1D9E75" className="!p-3" />
        <MetricCard label="Worst Trade" value={formatCurrency(stats.worstTrade)} valueColor="#E24B4A" className="!p-3" />
      </div>

      {/* Filter */}
      <div className="flex gap-2">
        {['all', 'wins', 'losses', 'pending'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-[11px] font-medium uppercase tracking-wider border transition-colors ${
              filter === f
                ? 'bg-[var(--color-foreground)] text-[var(--color-background)] border-[var(--color-foreground)]'
                : 'border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
            }`}
          >
            {f} {f !== 'all' && `(${f === 'wins' ? stats.wins : f === 'losses' ? stats.losses : stats.pendingTrades})`}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <DataTable columns={columns} data={filtered} pageSize={15} />
      </div>
    </div>
  )
}
