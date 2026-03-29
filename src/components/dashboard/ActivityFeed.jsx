import { useMode } from '../../context/ModeContext'
import { generateActivityFeed } from '../../data/mockActivity'
import { STRATEGY_MAP } from '../../utils/constants'
import { formatTimestamp, formatCurrency } from '../../utils/formatters'
import StatusDot from '../ui/StatusDot'

export default function ActivityFeed() {
  const { mode } = useMode()
  const feed = generateActivityFeed(mode, 30)

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
      <div className="px-4 py-2.5 border-b border-[var(--color-border)]">
        <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">Live Activity</span>
      </div>
      <div className="max-h-[400px] overflow-y-auto">
        {feed.map(entry => {
          const strategy = STRATEGY_MAP[entry.strategyId]
          return (
            <div key={entry.id} className="flex items-start gap-2 px-4 py-2 border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-muted)]/30">
              <StatusDot color={strategy?.color} size={6} />
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-[var(--color-foreground)] leading-tight">{entry.text}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="mono text-[10px] text-[var(--color-muted-foreground)]">{formatTimestamp(entry.timestamp)}</span>
                  <span className="mono text-[10px] font-medium" style={{ color: entry.pnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
                    {formatCurrency(entry.pnl)}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
