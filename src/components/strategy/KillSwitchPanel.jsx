import { Shield, AlertTriangle } from 'lucide-react'
import { STRATEGY_MAP } from '../../utils/constants'

export default function KillSwitchPanel({ strategyId }) {
  const strategy = STRATEGY_MAP[strategyId]

  const metrics = [
    { label: 'Consecutive Losses', current: 1, max: 3, status: 'ok' },
    { label: 'Daily Loss Cap Used', current: 120, max: 750, unit: '$', status: 'ok' },
    { label: 'Avg Slippage (session)', current: 1.2, unit: '¢', status: 'ok' },
    { label: 'Oracle Freshness', current: 142, unit: 's', status: 'ok' },
  ]

  return (
    <div className="space-y-4">
      {/* Status banner */}
      <div className="flex items-center gap-3 border border-[#1D9E75] bg-[#1D9E75]/5 px-4 py-3">
        <Shield size={18} style={{ color: '#1D9E75' }} />
        <div>
          <div className="text-[13px] font-medium" style={{ color: '#1D9E75' }}>ALL SYSTEMS NORMAL</div>
          <div className="text-[11px] text-[var(--color-muted-foreground)]">Kill switches armed and monitoring. No triggers activated.</div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-4">
        {metrics.map(m => (
          <div key={m.label} className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] text-[var(--color-muted-foreground)] uppercase tracking-wider mb-2">{m.label}</div>
            <div className="flex items-end gap-2">
              <span className="mono text-[20px] font-medium">{m.current}{m.unit || ''}</span>
              {m.max && <span className="mono text-[12px] text-[var(--color-muted-foreground)]">/ {m.max}{m.unit || ''}</span>}
            </div>
            {m.max && (
              <div className="w-full h-2 bg-[var(--color-muted)] mt-2">
                <div className="h-full transition-all" style={{
                  width: `${(m.current / m.max) * 100}%`,
                  backgroundColor: m.current / m.max > 0.8 ? '#E24B4A' : m.current / m.max > 0.5 ? '#EF9F27' : '#1D9E75'
                }} />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Kill switch rules */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Active Kill Switch Rules</div>
        <div className="space-y-2 text-[12px]">
          {[
            'Max slippage: If fill price is >3¢ worse than signal → cancel immediately',
            'Flash crash guard: If BTC drops >2% in 60s after fill → exit position now',
            'Consecutive loss limit: 3 losses in a row → pause strategy for 30 min',
            `Daily loss cap: If strategy loses >15% of allocated capital today → stop for 24h`,
            'Oracle freshness: Never fire if oracle was updated less than 60s ago',
          ].map((rule, i) => (
            <div key={i} className="flex items-start gap-2 py-1.5 border-b border-[var(--color-border)] last:border-0">
              <AlertTriangle size={12} className="text-[var(--color-muted-foreground)] mt-0.5 shrink-0" />
              <span className="text-[var(--color-foreground)]">{rule}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
