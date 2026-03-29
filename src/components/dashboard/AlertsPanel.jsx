import { useState } from 'react'
import { AlertTriangle, Info, CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { useMode } from '../../context/ModeContext'
import { generateAlerts } from '../../data/mockActivity'
import { formatRelativeTime } from '../../utils/formatters'

const icons = {
  warning: { icon: AlertTriangle, color: '#EF9F27' },
  info: { icon: Info, color: '#185FA5' },
  success: { icon: CheckCircle, color: '#1D9E75' },
  error: { icon: XCircle, color: '#E24B4A' },
}

export default function AlertsPanel() {
  const { mode } = useMode()
  const [expanded, setExpanded] = useState(true)
  const alerts = generateAlerts(mode)

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)]"
      >
        <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
          Alerts & Notifications ({alerts.length})
        </span>
        {expanded ? <ChevronUp size={14} className="text-[var(--color-muted-foreground)]" /> : <ChevronDown size={14} className="text-[var(--color-muted-foreground)]" />}
      </button>
      {expanded && (
        <div>
          {alerts.map(alert => {
            const { icon: Icon, color } = icons[alert.severity] || icons.info
            return (
              <div key={alert.id} className="flex items-start gap-3 px-4 py-2.5 border-b border-[var(--color-border)] last:border-0">
                <Icon size={14} style={{ color, marginTop: 1 }} className="shrink-0" />
                <div className="flex-1">
                  <div className="text-[12px] text-[var(--color-foreground)]">{alert.message}</div>
                  <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">{formatRelativeTime(alert.timestamp)}</div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
