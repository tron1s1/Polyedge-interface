import { useState } from 'react'
import { GitBranch } from 'lucide-react'
import { getVersions } from '../../data/mockVersions'
import { VERSION_STATUS } from '../../utils/constants'
import Badge from '../ui/Badge'
import { formatPercent, formatMs, formatCurrency } from '../../utils/formatters'

const statusVariant = {
  [VERSION_STATUS.TESTING]: 'testing',
  [VERSION_STATUS.WINNER]: 'winner',
  [VERSION_STATUS.RETIRED]: 'retired',
  [VERSION_STATUS.LIVE]: 'live',
}

export default function VersionsTab({ strategyId }) {
  const versions = getVersions(strategyId)
  const [compareA, setCompareA] = useState(null)
  const [compareB, setCompareB] = useState(null)

  return (
    <div className="space-y-6">
      {/* Leaderboard */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Version Leaderboard</div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Rank</th>
              <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Version</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Win Rate</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Avg P&L</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Latency</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Sharpe</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Trades</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Score</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Status</th>
            </tr>
          </thead>
          <tbody>
            {[...versions].sort((a, b) => b.score - a.score).map((v, i) => (
              <tr key={v.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-muted)]/30">
                <td className="py-2 px-2 mono text-[var(--color-muted-foreground)]">{i + 1}</td>
                <td className="py-2 px-2 font-medium">{v.name}</td>
                <td className="py-2 px-2 text-right mono">{formatPercent(v.winRate)}</td>
                <td className="py-2 px-2 text-right mono" style={{ color: '#1D9E75' }}>${v.avgPnl.toFixed(2)}</td>
                <td className="py-2 px-2 text-right mono">{formatMs(v.avgLatency)}</td>
                <td className="py-2 px-2 text-right mono">{v.sharpe.toFixed(1)}</td>
                <td className="py-2 px-2 text-right mono">
                  {v.trades}
                  {v.trades < v.tradeTarget && (
                    <span className="text-[var(--color-muted-foreground)]">/{v.tradeTarget}</span>
                  )}
                </td>
                <td className="py-2 px-2 text-right mono font-medium">{v.score}</td>
                <td className="py-2 px-2 text-right">
                  <Badge variant={statusVariant[v.status]}>{v.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Version Timeline */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-4">Version Timeline</div>
        <div className="space-y-0">
          {versions.map((v, i) => (
            <div key={v.id} className="flex gap-4">
              {/* Timeline line */}
              <div className="flex flex-col items-center">
                <div className="w-3 h-3 border-2 shrink-0" style={{
                  borderColor: v.status === VERSION_STATUS.WINNER ? '#1D9E75' : v.status === VERSION_STATUS.TESTING ? '#185FA5' : 'var(--color-border)',
                  backgroundColor: v.status === VERSION_STATUS.WINNER ? '#1D9E75' : 'transparent',
                  borderRadius: '50%'
                }} />
                {i < versions.length - 1 && <div className="w-px flex-1 bg-[var(--color-border)]" />}
              </div>
              {/* Content */}
              <div className="pb-4 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium">{v.name}</span>
                  <Badge variant={statusVariant[v.status]} className="text-[8px]">{v.status}</Badge>
                </div>
                <div className="text-[11px] text-[var(--color-muted-foreground)] mt-1">{v.changes}</div>
                <div className="flex gap-4 mt-1 text-[10px] text-[var(--color-muted-foreground)]">
                  <span>WR: <span className="mono">{formatPercent(v.winRate)}</span></span>
                  <span>P&L: <span className="mono">${v.avgPnl.toFixed(2)}</span></span>
                  <span>Latency: <span className="mono">{formatMs(v.avgLatency)}</span></span>
                  <span>{v.trades} trades</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
