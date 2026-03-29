import { useMode } from '../../context/ModeContext'
import { STRATEGY_MAP } from '../../utils/constants'
import { getMockTrades, getTradeStats } from '../../data/mockTrades'
import { getSparklineData } from '../../data/mockAnalytics'
import { getActiveVersion } from '../../data/mockVersions'
import SparklineChart from '../charts/SparklineChart'
import { formatCurrency, formatPercent, formatMs, formatRelativeTime } from '../../utils/formatters'

export default function OverviewTab({ strategyId }) {
  const { mode } = useMode()
  const strategy = STRATEGY_MAP[strategyId]
  const trades = getMockTrades(strategyId, mode)
  const stats = getTradeStats(trades)
  const version = getActiveVersion(strategyId)
  const sparkData = getSparklineData(strategyId, mode)
  const recentTrades = trades.slice(0, 5)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {/* P&L Chart */}
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">P&L Trend (14 days)</div>
          <SparklineChart data={sparkData} color={strategy.color} height={120} />
        </div>

        {/* Summary stats */}
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Performance Summary</div>
          <div className="space-y-2">
            {[
              ['Total P&L', formatCurrency(stats.totalPnl), stats.totalPnl >= 0 ? '#1D9E75' : '#E24B4A'],
              ['Win Rate', formatPercent(stats.winRate)],
              ['Avg P&L/Trade', formatCurrency(stats.avgPnl)],
              ['Best Trade', formatCurrency(stats.bestTrade), '#1D9E75'],
              ['Worst Trade', formatCurrency(stats.worstTrade), '#E24B4A'],
              ['Avg Latency', formatMs(stats.avgLatency)],
              ['Active Version', version.name],
              ['Version Score', version.score?.toFixed(1)],
            ].map(([label, value, color]) => (
              <div key={label} className="flex justify-between py-1 border-b border-[var(--color-border)] last:border-0">
                <span className="text-[12px] text-[var(--color-muted-foreground)]">{label}</span>
                <span className="mono text-[12px] font-medium" style={color ? { color } : {}}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent trades */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Recent Trades</div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="text-left py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Time</th>
              <th className="text-left py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Market</th>
              <th className="text-left py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Direction</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Size</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">P&L</th>
              <th className="text-right py-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Status</th>
            </tr>
          </thead>
          <tbody>
            {recentTrades.map(t => (
              <tr key={t.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="py-2 px-2 mono text-[var(--color-muted-foreground)]">{formatRelativeTime(t.timestamp)}</td>
                <td className="py-2 px-2">{t.market}</td>
                <td className="py-2 px-2 mono font-medium" style={{ color: t.direction === 'YES' ? '#1D9E75' : '#E24B4A' }}>{t.direction}</td>
                <td className="py-2 px-2 text-right mono">${t.size}</td>
                <td className="py-2 px-2 text-right mono font-medium" style={{ color: t.pnl >= 0 ? '#1D9E75' : '#E24B4A' }}>{formatCurrency(t.pnl)}</td>
                <td className="py-2 px-2 text-right">
                  <span className="text-[10px] uppercase" style={{ color: t.status === 'won' ? '#1D9E75' : t.status === 'lost' ? '#E24B4A' : '#EF9F27' }}>
                    {t.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
