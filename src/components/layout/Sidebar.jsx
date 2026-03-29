import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { STRATEGIES } from '../../utils/constants'
import { useMode } from '../../context/ModeContext'
import { getActiveVersion } from '../../data/mockVersions'
import { getMockTrades, getTradeStats } from '../../data/mockTrades'
import StatusDot from '../ui/StatusDot'
import Badge from '../ui/Badge'
import { cn, formatPercent } from '../../utils/formatters'

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const { strategyId } = useParams()
  const { mode, isPaper } = useMode()

  return (
    <div className={cn(
      'shrink-0 border-r border-[var(--color-border)] bg-[var(--color-card)] flex flex-col transition-all overflow-hidden',
      collapsed ? 'w-12' : 'w-60'
    )}>
      <div className="flex-1 py-2">
        {STRATEGIES.map(s => {
          const version = getActiveVersion(s.id)
          const stats = getTradeStats(getMockTrades(s.id, mode))
          const isActive = strategyId === s.id
          return (
            <button
              key={s.id}
              onClick={() => navigate(`/strategies/${s.id}`)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors',
                isActive ? 'bg-[var(--color-muted)]' : 'hover:bg-[var(--color-muted)]/50'
              )}
            >
              <StatusDot color={s.color} />
              {!collapsed && (
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-medium text-[var(--color-foreground)] truncate">{s.shortName}</div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant={isPaper ? 'paper' : 'live'} className="text-[8px] px-1 py-0">
                      {isPaper ? 'Paper' : 'Live'}
                    </Badge>
                    <span className="mono text-[10px] text-[var(--color-muted-foreground)]">
                      {formatPercent(stats.winRate)}
                    </span>
                    <span className="mono text-[10px] text-[var(--color-muted-foreground)]">
                      {version.name}
                    </span>
                  </div>
                </div>
              )}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => setCollapsed(c => !c)}
        className="p-3 border-t border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] flex justify-center"
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>
    </div>
  )
}
