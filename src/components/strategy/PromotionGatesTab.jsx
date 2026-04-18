import { useCallback } from 'react'
import { Check, X, Rocket, AlertCircle } from 'lucide-react'
import { api } from '../../lib/api'
import { usePolling } from '../../hooks/useLiveData'

const GATE_LABELS = {
  min_trades:                { label: 'Minimum trade count',         help: 'Need enough samples to prove the edge is real.' },
  min_win_rate:              { label: 'Minimum win rate',            help: 'A-math strategies should be near-deterministic.' },
  min_unique_triangles_used: { label: 'Triangle diversity',          help: 'Profit must come from multiple triangles, not one fluke.' },
  min_avg_net_pct:           { label: 'Minimum average net profit',  help: 'Average net edge (after fees) across paper trades.' },
  max_consecutive_losses:    { label: 'Max consecutive losses',      help: 'Protects against regime-change blowups.' },
  zero_reversal_events:      { label: 'Zero book-reversal events',   help: 'No triangles flipped negative mid-execution.' },
}

function fmtVal(key, v) {
  if (v === null || v === undefined) return '—'
  if (key === 'min_win_rate') return `${(v * 100).toFixed(1)}%`
  if (key === 'min_avg_net_pct') return `${Number(v).toFixed(4)}%`
  return String(v)
}

function fmtReq(key, v) {
  if (v === null || v === undefined) return '—'
  if (key === 'min_win_rate') return `≥ ${(v * 100).toFixed(0)}%`
  if (key === 'min_avg_net_pct') return `≥ ${Number(v).toFixed(3)}%`
  if (key === 'max_consecutive_losses') return `≤ ${v}`
  if (key === 'zero_reversal_events') return `= ${v}`
  return `≥ ${v}`
}

export default function PromotionGatesTab({ strategyId }) {
  const { data, loading } = usePolling(
    useCallback(() => api.getPromotionGates(strategyId), [strategyId]),
    10000
  )

  if (loading && !data) {
    return <div className="text-[11px] text-[var(--color-muted-foreground)]">Loading promotion gates…</div>
  }

  const gates = data?.gates || {}
  const entries = Object.entries(gates)
  const passedCount = entries.filter(([, g]) => g?.passed).length
  const totalCount = entries.length
  const allPassed = data?.all_passed === true
  const err = data?.error

  return (
    <div className="space-y-5">
      {/* Summary banner */}
      <div className={`flex items-center gap-3 p-4 border rounded ${
        allPassed
          ? 'border-[#1D9E75] bg-[#1D9E75]/10'
          : 'border-[#EF9F27] bg-[#EF9F27]/10'
      }`}>
        {allPassed ? (
          <Rocket size={18} className="text-[#1D9E75]" />
        ) : (
          <AlertCircle size={18} className="text-[#EF9F27]" />
        )}
        <div className="flex-1">
          <div className={`text-[12px] font-medium ${allPassed ? 'text-[#1D9E75]' : 'text-[#EF9F27]'}`}>
            {allPassed
              ? 'All promotion gates passed — strategy is eligible for live trading.'
              : `${passedCount} of ${totalCount} gates passed — keep paper-trading to unlock live.`}
          </div>
          <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">
            Gates re-evaluate every 10 seconds from strategy_executions history.
          </div>
        </div>
      </div>

      {err && (
        <div className="p-3 border border-[#E24B4A] bg-[#E24B4A]/10 rounded text-[11px] text-[#E24B4A]">
          Gate check error: {err}
        </div>
      )}

      {/* Gate list */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] divide-y divide-[var(--color-border)]">
        <div className="flex items-center gap-4 px-4 py-2.5 bg-[var(--color-muted)]/30 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          <span className="w-[30px] shrink-0">#</span>
          <span className="flex-1">Gate</span>
          <span className="w-[120px] text-right">Current</span>
          <span className="w-[120px] text-right">Required</span>
          <span className="w-[80px] text-right">Status</span>
        </div>
        {entries.length === 0 ? (
          <div className="px-4 py-6 text-center text-[11px] text-[var(--color-muted-foreground)]">
            No gate data yet — strategy hasn't produced enough trades for evaluation.
          </div>
        ) : entries.map(([key, g], i) => {
          const meta = GATE_LABELS[key] || { label: key, help: '' }
          const passed = g?.passed === true
          return (
            <div key={key} className="flex items-center gap-4 px-4 py-3 text-[11px]">
              <span className="w-[30px] shrink-0 mono text-[var(--color-muted-foreground)]">{i + 1}</span>
              <div className="flex-1">
                <div className="font-medium">{meta.label}</div>
                {meta.help && (
                  <div className="text-[9px] text-[var(--color-muted-foreground)] mt-0.5">{meta.help}</div>
                )}
              </div>
              <span className="w-[120px] text-right mono" style={{ color: passed ? '#1D9E75' : '#EF9F27' }}>
                {fmtVal(key, g?.value)}
              </span>
              <span className="w-[120px] text-right mono text-[var(--color-muted-foreground)]">
                {fmtReq(key, g?.required)}
              </span>
              <span className="w-[80px] flex items-center justify-end gap-1">
                {passed ? (
                  <>
                    <Check size={14} className="text-[#1D9E75]" />
                    <span className="text-[#1D9E75] uppercase text-[10px] font-medium">Pass</span>
                  </>
                ) : (
                  <>
                    <X size={14} className="text-[#EF9F27]" />
                    <span className="text-[#EF9F27] uppercase text-[10px] font-medium">Fail</span>
                  </>
                )}
              </span>
            </div>
          )
        })}
      </div>

      {data?.checked_at && (
        <div className="text-[9px] text-[var(--color-muted-foreground)] text-right">
          Last checked: <span className="mono">{new Date(data.checked_at).toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}
