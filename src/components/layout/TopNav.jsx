import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Sun, Moon, Settings, Bell, AlertTriangle, AlertCircle, Info, X, ExternalLink } from 'lucide-react'
import { useTheme } from '../../context/ThemeContext'
import { useMode } from '../../context/ModeContext'
import { NAV_ITEMS } from '../../utils/constants'
import { cn } from '../../utils/formatters'
import { api } from '../../lib/api'

const TYPE_CONFIG = {
  critical: { icon: AlertCircle, color: '#FF002B', bg: 'rgba(255,0,43,0.08)', border: 'rgba(255,0,43,0.2)', label: 'CRITICAL' },
  warning:  { icon: AlertTriangle, color: '#EF9F27', bg: 'rgba(239,159,39,0.08)', border: 'rgba(239,159,39,0.2)', label: 'WARNING' },
  info:     { icon: Info, color: '#185FA5', bg: 'rgba(24,95,165,0.08)', border: 'rgba(24,95,165,0.2)', label: 'INFO' },
}

function timeAgo(isoStr) {
  if (!isoStr) return ''
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function TopNav() {
  const { theme, toggleTheme } = useTheme()
  const { isPaper, toggleMode } = useMode()
  const navigate = useNavigate()
  const location = useLocation()

  const [notifications, setNotifications] = useState([])
  const [open, setOpen] = useState(false)
  const [dismissed, setDismissed] = useState(() => {
    try { return JSON.parse(localStorage.getItem('dismissed_notifications') || '[]') } catch { return [] }
  })
  const panelRef = useRef(null)

  // Fetch notifications every 10s
  const fetchNotifications = useCallback(async () => {
    const data = await api.getNotifications()
    if (data?.notifications) setNotifications(data.notifications)
  }, [])

  useEffect(() => {
    fetchNotifications()
    const id = setInterval(fetchNotifications, 10000)
    return () => clearInterval(id)
  }, [fetchNotifications])

  // Close on outside click
  useEffect(() => {
    function handleClick(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const visible = notifications.filter(n => !dismissed.includes(n.id))
  const criticalCount = visible.filter(n => n.type === 'critical').length
  const hasWarnings = visible.some(n => n.type === 'warning')

  const dismiss = (id) => {
    const next = [...dismissed, id]
    setDismissed(next)
    localStorage.setItem('dismissed_notifications', JSON.stringify(next))
  }

  const clearAll = () => {
    const next = notifications.map(n => n.id)
    setDismissed(next)
    localStorage.setItem('dismissed_notifications', JSON.stringify(next))
    setOpen(false)
  }

  const handleAction = (action) => {
    if (action) navigate(action)
    setOpen(false)
  }

  // Badge color: red for critical, yellow for warning, blue for info-only
  const badgeColor = criticalCount > 0 ? '#FF002B' : hasWarnings ? '#EF9F27' : '#185FA5'

  const isActive = (item) => {
    if (item.id === 'dashboard') return location.pathname === '/'
    return location.pathname.startsWith(`/${item.id}`)
  }

  return (
    <nav className="fixed top-0 left-0 right-0 h-12 bg-[var(--color-card)] border-b border-[var(--color-border)] flex items-center justify-between px-4 z-50">
      {/* Left: Logo */}
      <div
        className="text-[14px] font-medium tracking-[0.1em] uppercase cursor-pointer select-none"
        onClick={() => navigate('/')}
      >
        ALPHANODE
      </div>

      {/* Center: Nav tabs */}
      <div className="flex items-center gap-0.5">
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => navigate(item.path)}
            className={cn(
              'px-2.5 py-1.5 text-[11px] font-medium transition-colors',
              isActive(item)
                ? 'text-[var(--color-foreground)] bg-[var(--color-muted)]'
                : 'text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Right: Controls */}
      <div className="flex items-center gap-3">
        {/* Paper/Live Toggle */}
        <button
          onClick={toggleMode}
          className="flex items-center gap-2 px-3 py-1.5 border text-[11px] font-medium uppercase tracking-wider transition-colors"
          style={{
            borderColor: isPaper ? '#1D9E75' : '#FF002B',
            color: isPaper ? '#1D9E75' : '#FF002B',
            backgroundColor: isPaper ? 'rgba(29,158,117,0.08)' : 'rgba(255,0,43,0.08)',
          }}
        >
          <span
            className="w-2 h-2 inline-block"
            style={{ backgroundColor: isPaper ? '#1D9E75' : '#FF002B', borderRadius: '50%' }}
          />
          {isPaper ? 'Paper' : 'Live'}
        </button>

        {/* Notification Bell */}
        <div className="relative" ref={panelRef}>
          <button
            onClick={() => setOpen(!open)}
            className={cn(
              'p-1.5 relative transition-colors',
              open ? 'text-[var(--color-foreground)]' : 'text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
            )}
          >
            <Bell size={16} />
            {visible.length > 0 && (
              <span
                className="absolute -top-0.5 -right-0.5 min-w-[14px] h-3.5 px-0.5 text-white text-[8px] flex items-center justify-center"
                style={{ backgroundColor: badgeColor, borderRadius: '50%' }}
              >
                {visible.length}
              </span>
            )}
          </button>

          {/* Dropdown Panel */}
          {open && (
            <div className="absolute top-full right-0 mt-2 w-[380px] bg-[var(--color-card)] border border-[var(--color-border)] shadow-2xl z-[100]"
              style={{ maxHeight: '480px' }}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)]">
                <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  Notifications ({visible.length})
                </span>
                {visible.length > 0 && (
                  <button
                    onClick={clearAll}
                    className="text-[10px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors"
                  >
                    Clear all
                  </button>
                )}
              </div>

              {/* List */}
              <div className="overflow-y-auto" style={{ maxHeight: '420px' }}>
                {visible.length === 0 ? (
                  <div className="px-4 py-8 text-center text-[11px] text-[var(--color-muted-foreground)]">
                    All clear — no active alerts.
                  </div>
                ) : (
                  visible.map(n => {
                    const cfg = TYPE_CONFIG[n.type] || TYPE_CONFIG.info
                    const Icon = cfg.icon
                    return (
                      <div
                        key={n.id}
                        className="px-4 py-3 border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-muted)]/30 transition-colors"
                        style={{ backgroundColor: cfg.bg }}
                      >
                        <div className="flex items-start gap-3">
                          <Icon size={14} style={{ color: cfg.color, marginTop: 2, flexShrink: 0 }} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span
                                className="text-[8px] font-medium px-1 py-0.5 uppercase tracking-wider"
                                style={{ color: cfg.color, backgroundColor: cfg.bg, border: `1px solid ${cfg.border}` }}
                              >
                                {cfg.label}
                              </span>
                              <span className="text-[9px] text-[var(--color-muted-foreground)]">{timeAgo(n.time)}</span>
                            </div>
                            <div className="text-[11px] font-medium text-[var(--color-foreground)] mb-0.5">{n.title}</div>
                            <div className="text-[10px] text-[var(--color-muted-foreground)] leading-relaxed">{n.message}</div>
                            {n.action && (
                              <button
                                onClick={() => handleAction(n.action)}
                                className="flex items-center gap-1 mt-1.5 text-[10px] font-medium transition-colors hover:underline"
                                style={{ color: cfg.color }}
                              >
                                View details <ExternalLink size={9} />
                              </button>
                            )}
                          </div>
                          <button
                            onClick={() => dismiss(n.id)}
                            className="p-0.5 text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors shrink-0"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          )}
        </div>

        <button
          onClick={toggleTheme}
          className="p-1.5 text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        <button
          onClick={() => navigate('/settings')}
          className="p-1.5 text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
        >
          <Settings size={16} />
        </button>
      </div>
    </nav>
  )
}
