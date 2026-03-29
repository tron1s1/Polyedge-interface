import { useNavigate } from 'react-router-dom'
import { useMode } from '../../context/ModeContext'
import { getMockTrades, getTradeStats } from '../../data/mockTrades'
import { getSparklineData } from '../../data/mockAnalytics'
import { getActiveVersion } from '../../data/mockVersions'
import Badge from '../ui/Badge'
import SparklineChart from '../charts/SparklineChart'
import { formatCurrency, formatPercent, formatRelativeTime } from '../../utils/formatters'

export default function StrategyCard({ strategy }) {
  const { mode, isPaper } = useMode()
  const navigate = useNavigate()
  const trades = getMockTrades(strategy.id, mode)
  const stats = getTradeStats(trades)
  const version = getActiveVersion(strategy.id)
  const sparkData = getSparklineData(strategy.id, mode)
  const todayTrades = trades.filter(t => Date.now() - new Date(t.timestamp).getTime() < 86400000)
  const todayPnl = todayTrades.reduce((s, t) => s + t.pnl, 0)
  const lastTrade = trades[0]

  return (
    <div
      className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 cursor-pointer hover:bg-[var(--color-muted)]/30 transition-colors"
      style={{ borderLeft: `3px solid ${strategy.color}` }}
      onClick={() => navigate(`/strategies/${strategy.id}`)}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium">{strategy.shortName}</span>
          <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper' : 'Live'}</Badge>
          <span className="mono text-[10px] text-[var(--color-muted-foreground)]">{version.name}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-3">
        <div>
          <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase tracking-wider">Win Rate</div>
          <div className="mono text-[20px] font-medium">{formatPercent(stats.winRate)}</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase tracking-wider">P&L Today</div>
          <div className="mono text-[14px] font-medium" style={{ color: todayPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
            {formatCurrency(todayPnl)}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase tracking-wider">Trades Today</div>
          <div className="mono text-[14px] font-medium">{todayTrades.length}</div>
        </div>
      </div>

      <SparklineChart data={sparkData} color={strategy.color} height={50} />

      <div className="flex items-center justify-between mt-2">
        <span className="text-[11px] text-[var(--color-muted-foreground)]">
          {lastTrade ? `Last trade ${formatRelativeTime(lastTrade.timestamp)}` : 'No trades yet'}
        </span>
        <span className="text-[11px] text-[var(--color-accent)] font-medium">View Details →</span>
      </div>
    </div>
  )
}
