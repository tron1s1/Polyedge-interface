import { useCallback } from 'react'
import { useMode } from '../context/ModeContext'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import MetricCard from '../components/ui/MetricCard'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/formatters'
import { Landmark, CalendarClock, ReceiptText, Download } from 'lucide-react'

// ── INR formatting with Indian comma grouping ────────────────────────────────

function formatINR(value) {
  if (value == null) return '₹0'
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString('en-IN')
  return `₹${formatted}`
}

function formatUSD(value, decimals = 2) {
  if (value == null) return '$0'
  return `$${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
}

// ── Main Tax Page ────────────────────────────────────────────────────────────

export default function TaxPage() {
  const { isPaper } = useMode()
  const { data } = usePolling(useCallback(() => api.getTaxSummary(), []), 30000)

  const byFy = data?.by_financial_year || {}
  const allEvents = data?.all_events || []

  // Use latest FY or fallback
  const fyKeys = Object.keys(byFy).sort().reverse()
  const currentFy = fyKeys[0] || '2025-26'
  const fySummary = byFy[currentFy] || { gains: 0, losses: 0, tax_reserved: 0, tds: 0, events: [] }

  const netTaxable = Math.max(fySummary.gains - fySummary.losses, 0)
  const tax30 = Math.round(netTaxable * 0.312) // 30% + 4% cess
  const remainingTax = Math.max(tax30 - fySummary.tds - fySummary.tax_reserved, 0)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">India Tax Engine</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper' : 'Live'}</Badge>
        <span className="text-[11px] text-[var(--color-muted-foreground)]">
          FY {currentFy} — Section 115BBH (30% flat on VDA)
        </span>
      </div>

      {/* ─── SECTION 1: Financial Year Summary ─── */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Landmark size={16} className="text-[var(--color-accent)]" />
          <span className="text-[15px] font-medium">Financial Year Summary</span>
          <span className="mono text-[11px] text-[var(--color-muted-foreground)]">FY {currentFy}</span>
        </div>

        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="space-y-0">
            {[
              { label: 'Total gains (crypto + stocks)', value: formatUSD(fySummary.gains), color: '#1D9E75' },
              { label: 'Total losses', value: formatUSD(fySummary.losses), color: '#E24B4A' },
              { label: 'Net taxable amount', value: formatUSD(netTaxable), color: 'var(--color-foreground)', bold: true },
              { label: 'Tax @ 30% + 4% cess', value: formatUSD(tax30), color: '#EF9F27' },
              { label: 'TDS auto-deducted (1% on sell)', value: formatUSD(fySummary.tds), color: '#185FA5', note: 'credit' },
              { label: 'Tax reserved', value: formatUSD(fySummary.tax_reserved), color: '#1D9E75' },
              { label: 'Remaining tax liability', value: formatUSD(remainingTax), color: '#E24B4A' },
            ].map((row, i) => (
              <div key={i} className="flex items-center justify-between py-2.5 border-b border-[var(--color-border)] last:border-0">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-[var(--color-muted-foreground)]">{row.label}</span>
                  {row.note && (
                    <span className="text-[9px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-muted-foreground)] uppercase tracking-wider">
                      {row.note}
                    </span>
                  )}
                </div>
                <span className={cn('mono text-[14px]', row.bold && 'font-medium')} style={{ color: row.color }}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ─── SECTION 2: Tax Events ─── */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <ReceiptText size={16} className="text-[var(--color-accent)]" />
          <span className="text-[15px] font-medium">Tax Events</span>
          <span className="mono text-[11px] text-[var(--color-muted-foreground)]">
            {allEvents.length} total events
          </span>
        </div>

        <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
          {allEvents.length > 0 ? (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-[var(--color-border)]">
                  {['Date', 'Strategy', 'Profit (USDC)', 'Tax Reserved (INR)', 'TDS (INR)', 'FY'].map(h => (
                    <th key={h} className="text-left py-2.5 px-4 text-[10px] uppercase text-[var(--color-muted-foreground)] font-medium tracking-wider">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allEvents.slice(0, 50).map((ev, i) => (
                  <tr key={i} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-2.5 px-4 mono text-[var(--color-muted-foreground)]">
                      {ev.created_at ? new Date(ev.created_at).toLocaleDateString() : '--'}
                    </td>
                    <td className="py-2.5 px-4 font-medium">{ev.strategy_id || '--'}</td>
                    <td className="py-2.5 px-4 mono" style={{ color: (ev.profit_usdc || 0) >= 0 ? '#1D9E75' : '#E24B4A' }}>
                      ${(ev.profit_usdc || 0).toFixed(2)}
                    </td>
                    <td className="py-2.5 px-4 mono">{formatINR(ev.tax_reserved_inr || 0)}</td>
                    <td className="py-2.5 px-4 mono">{formatINR(ev.tds_inr || 0)}</td>
                    <td className="py-2.5 px-4 mono text-[var(--color-muted-foreground)]">{ev.financial_year || '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-4 py-6 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No tax events recorded yet. Events are created when trades close with PnL.
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] text-[11px] font-medium hover:bg-[var(--color-muted)] transition-colors">
          <Download size={13} />
          Export CSV for CA
        </button>
        <button className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] text-[11px] font-medium hover:bg-[var(--color-muted)] transition-colors">
          <Download size={13} />
          Download ITR-ready PDF
        </button>
      </div>
    </div>
  )
}
