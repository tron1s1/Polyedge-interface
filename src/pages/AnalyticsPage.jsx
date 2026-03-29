import { useCallback } from 'react'
import { useMode } from '../context/ModeContext'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/formatters'
import { AlertCircle, AlertTriangle, Info, TrendingUp, TrendingDown, Activity, Target, Zap } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie, Legend
} from 'recharts'

const CATEGORY_COLORS = { A: '#1D9E75', B: '#185FA5', C: '#EF9F27', D: '#E24B4A' }

const IMPROVEMENT_ICON = {
  critical: { icon: AlertCircle, color: '#FF002B' },
  warning:  { icon: AlertTriangle, color: '#EF9F27' },
  info:     { icon: Info, color: '#185FA5' },
}

function StatBox({ label, value, sub, color, icon: Icon }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <div className="flex items-center justify-between mb-1">
        <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">{label}</div>
        {Icon && <Icon size={13} className="text-[var(--color-muted-foreground)]" />}
      </div>
      <div className="mono text-[22px] font-medium" style={{ color }}>{value}</div>
      {sub && <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{sub}</div>}
    </div>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-[var(--color-card)] border border-[var(--color-border)] px-3 py-2 text-[10px]">
      <div className="text-[var(--color-muted-foreground)] mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }} className="mono">
          {p.name}: {typeof p.value === 'number' && p.value >= 0 ? '+' : ''}
          {typeof p.value === 'number' ? `$${p.value.toFixed(2)}` : p.value}
        </div>
      ))}
    </div>
  )
}

export default function AnalyticsPage() {
  const { isPaper } = useMode()
  const mode = isPaper ? 'paper' : 'live'

  const { data, loading } = usePolling(
    useCallback(() => api.getAnalytics(mode), [mode]),
    15000
  )

  if (loading) return <div className="p-6 text-[11px] text-[var(--color-muted-foreground)]">Loading analytics...</div>

  const summary = data?.summary || {}
  const pnlSeries = data?.pnl_series || []
  const breakdown = data?.strategy_breakdown || []
  const improvements = data?.improvements || []

  const totalPnl = summary.total_pnl || 0
  const winRate = summary.win_rate || 0
  const profitFactor = summary.profit_factor || 0
  const hasData = (summary.total_trades || 0) > 0

  const pieData = [
    { name: 'Wins', value: summary.wins || 0, color: '#1D9E75' },
    { name: 'Losses', value: summary.losses || 0, color: '#E24B4A' },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">Analytics</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper Trading' : 'Live Trading'}</Badge>
        <span className="text-[11px] text-[var(--color-muted-foreground)]">
          In-depth performance analysis · auto-refreshes every 15s
        </span>
      </div>

      {/* Top stats row */}
      <div className="grid grid-cols-6 gap-3">
        <StatBox
          label="Total P&L"
          value={`${totalPnl >= 0 ? '+' : ''}$${Math.abs(totalPnl).toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          color={totalPnl >= 0 ? '#1D9E75' : '#E24B4A'}
          icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
        />
        <StatBox
          label="Win Rate"
          value={`${winRate.toFixed(1)}%`}
          sub={`${summary.wins || 0}W / ${summary.losses || 0}L`}
          color={winRate >= 60 ? '#1D9E75' : winRate >= 45 ? '#EF9F27' : '#E24B4A'}
          icon={Target}
        />
        <StatBox
          label="Total Trades"
          value={String(summary.total_trades || 0)}
          sub={`${summary.long_trades || 0} long · ${summary.short_trades || 0} short`}
          icon={Activity}
        />
        <StatBox
          label="Profit Factor"
          value={profitFactor > 0 ? profitFactor.toFixed(2) : '—'}
          sub="gross wins ÷ losses"
          color={profitFactor >= 1.5 ? '#1D9E75' : profitFactor >= 1 ? '#EF9F27' : '#E24B4A'}
          icon={Zap}
        />
        <StatBox
          label="Avg Win"
          value={summary.avg_win > 0 ? `+$${summary.avg_win.toFixed(2)}` : '—'}
          color="#1D9E75"
          icon={TrendingUp}
        />
        <StatBox
          label="Avg Loss"
          value={summary.avg_loss > 0 ? `-$${summary.avg_loss.toFixed(2)}` : '—'}
          color="#E24B4A"
          icon={TrendingDown}
        />
      </div>

      {!hasData ? (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-12 text-center">
          <div className="text-[13px] font-medium mb-2">No trade data yet</div>
          <div className="text-[11px] text-[var(--color-muted-foreground)]">
            {isPaper
              ? 'Enable strategies and allocate paper capital to start generating trades. The scanner will record paper trades automatically.'
              : 'No live trades recorded. Switch to Paper mode to start testing strategies first.'}
          </div>
        </div>
      ) : (
        <>
          {/* Cumulative P&L chart */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-4">
              Cumulative P&L Over Time
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={pnlSeries} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1D9E75" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#1D9E75" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--color-muted-foreground)' }} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: 'var(--color-muted-foreground)' }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="cumulative" name="Cumulative P&L" stroke="#1D9E75" strokeWidth={2} fill="url(#pnlGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Daily P&L + Win/Loss pie */}
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2 border border-[var(--color-border)] bg-[var(--color-card)] p-4">
              <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-4">Daily P&L</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={pnlSeries} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--color-muted-foreground)' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: 'var(--color-muted-foreground)' }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="daily_pnl" name="Daily P&L" radius={[2, 2, 0, 0]}>
                    {pnlSeries.map((entry, i) => (
                      <Cell key={i} fill={entry.daily_pnl >= 0 ? '#1D9E75' : '#E24B4A'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
              <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-4">Win / Loss Split</div>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={45} outerRadius={70} dataKey="value" paddingAngle={3}>
                    {pieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Legend iconSize={8} formatter={v => <span style={{ fontSize: 10 }}>{v}</span>} />
                  <Tooltip formatter={v => [`${v} trades`]} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Per-strategy breakdown */}
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
              Strategy Performance Breakdown
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-[var(--color-border)]">
                  {['Strategy', 'Trades', 'W', 'L', 'Win Rate', 'P&L', 'Bar'].map(h => (
                    <th key={h} className={cn(
                      'py-2 px-2 text-[9px] uppercase text-[var(--color-muted-foreground)]',
                      ['Trades', 'W', 'L', 'Win Rate', 'P&L'].includes(h) ? 'text-right' : 'text-left'
                    )}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {breakdown.map(s => {
                  const color = CATEGORY_COLORS[s.category?.[0]] || '#555'
                  const pnlColor = s.pnl > 0 ? '#1D9E75' : s.pnl < 0 ? '#E24B4A' : 'var(--color-muted-foreground)'
                  const maxPnl = Math.max(...breakdown.map(x => Math.abs(x.pnl)), 1)
                  return (
                    <tr key={s.strategy_id} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                          <div>
                            <div className="font-medium">{s.display_name || s.strategy_id}</div>
                            <div className="mono text-[9px] text-[var(--color-muted-foreground)]">{s.strategy_id}</div>
                          </div>
                        </div>
                      </td>
                      <td className="py-2.5 px-2 mono text-right">{s.trades}</td>
                      <td className="py-2.5 px-2 mono text-right text-[#1D9E75]">{s.wins}</td>
                      <td className="py-2.5 px-2 mono text-right text-[#E24B4A]">{s.losses}</td>
                      <td className="py-2.5 px-2 mono text-right" style={{ color: s.win_rate >= 60 ? '#1D9E75' : s.win_rate >= 45 ? '#EF9F27' : '#E24B4A' }}>
                        {s.win_rate.toFixed(1)}%
                      </td>
                      <td className="py-2.5 px-2 mono text-right font-medium" style={{ color: pnlColor }}>
                        {s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-2 w-[120px]">
                        <div className="w-full h-1.5 bg-[var(--color-muted)]">
                          <div className="h-full" style={{ width: `${Math.abs(s.pnl) / maxPnl * 100}%`, backgroundColor: pnlColor }} />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Recommendations */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
          Recommendations &amp; What to Improve
        </div>
        <div className="space-y-2">
          {improvements.map((item, i) => {
            const cfg = IMPROVEMENT_ICON[item.type] || IMPROVEMENT_ICON.info
            const Icon = cfg.icon
            return (
              <div key={i} className="flex items-start gap-3 px-3 py-2.5 border"
                style={{ borderColor: `${cfg.color}30`, backgroundColor: `${cfg.color}08` }}>
                <Icon size={14} style={{ color: cfg.color, marginTop: 1, flexShrink: 0 }} />
                <div>
                  <div className="text-[11px] font-medium" style={{ color: cfg.color }}>{item.title}</div>
                  <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5 leading-relaxed">{item.detail}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
