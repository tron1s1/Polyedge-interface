import { useState, useCallback } from 'react'
import { useMode } from '../context/ModeContext'
import { REGIME_COLORS, REGIMES } from '../utils/constants'
import { formatDate, cn } from '../utils/formatters'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { ShieldAlert, CircleOff, ChevronDown, Activity, Zap } from 'lucide-react'

export default function RiskPage() {
  const { isPaper } = useMode()
  const { data, refetch } = usePolling(useCallback(() => api.getRiskCurrent(), []), 5000)
  const [overrideOpen, setOverrideOpen] = useState(false)

  const regime = data?.regime || 'UNKNOWN'
  const snapshot = data?.snapshot || {}
  const killActive = data?.kill_switch_active || false
  const regimeHistory = data?.regime_history || []
  const regimeColor = REGIME_COLORS[regime] || '#6B7280'

  const handleKillSwitch = async () => {
    if (killActive) {
      await api.releaseKillSwitch()
    } else {
      await api.triggerKillSwitch()
    }
    refetch()
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">Risk Monitor</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper' : 'Live'}</Badge>
        <span className="text-[11px] text-[var(--color-muted-foreground)]">Live from Supabase</span>
      </div>

      {/* Current Market Regime */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-5">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-4">
          Current Market Regime
        </div>
        <div className="mono text-[32px] font-bold mb-4" style={{ color: regimeColor }}>
          {regime}
        </div>

        <div className="grid grid-cols-4 gap-4">
          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Capital</div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-muted-foreground)]">Total</span>
              <span className="mono text-[12px] font-medium">${(snapshot.total_capital_usdc || 0).toFixed(2)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-muted-foreground)]">Peak</span>
              <span className="mono text-[12px] font-medium">${(snapshot.peak_capital_usdc || 0).toFixed(2)}</span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Drawdown</div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-muted-foreground)]">Current</span>
              <span className="mono text-[12px] font-medium" style={{ color: (snapshot.drawdown_pct || 0) > 10 ? '#E24B4A' : '#1D9E75' }}>
                {(snapshot.drawdown_pct || 0).toFixed(1)}%
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Kelly</div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-muted-foreground)]">Multiplier</span>
              <span className="mono text-[12px] font-medium">{(snapshot.kelly_multiplier || 0.75).toFixed(2)}x</span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Daily PnL</div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-muted-foreground)]">Today</span>
              <span className="mono text-[12px] font-medium" style={{ color: (snapshot.daily_pnl_usdc || 0) >= 0 ? '#1D9E75' : '#E24B4A' }}>
                ${(snapshot.daily_pnl_usdc || 0).toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Circuit Breakers / Kill Switch */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="flex items-center gap-2 mb-4">
          <ShieldAlert className="w-4 h-4 text-[var(--color-muted-foreground)]" />
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Kill Switch & Circuit Breakers
          </div>
        </div>

        {snapshot.circuit_breakers_active && snapshot.circuit_breakers_active.length > 0 && (
          <div className="mb-4 p-3 border border-[#E24B4A]/30 bg-[#E24B4A]/5">
            <div className="text-[11px] font-medium text-[#E24B4A] mb-1">Active Circuit Breakers:</div>
            <div className="flex flex-wrap gap-1.5">
              {snapshot.circuit_breakers_active.map(cb => (
                <span key={cb} className="mono text-[9px] px-1.5 py-0.5 bg-[#E24B4A]/10 text-[#E24B4A] border border-[#E24B4A]/20">
                  {cb}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 pt-3 border-t border-[var(--color-border)]">
          <button
            onClick={handleKillSwitch}
            className={cn(
              'flex items-center gap-2 px-4 py-2 text-[11px] font-medium uppercase tracking-wider border-2 transition-colors cursor-pointer',
              killActive
                ? 'border-[#E24B4A] bg-[#E24B4A] text-white'
                : 'border-[#E24B4A] text-[#E24B4A] hover:bg-[#E24B4A]/10'
            )}
          >
            <CircleOff className="w-3.5 h-3.5" />
            Global Kill Switch: {killActive ? 'ACTIVE' : 'OFF'}
          </button>
        </div>
      </div>

      {/* Regime History */}
      {regimeHistory.length > 0 && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
            Regime History
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-[var(--color-border)]">
                {['Regime', 'BTC 1h', 'BTC 4h', 'Fear/Greed', 'Kelly', 'Time'].map(h => (
                  <th key={h} className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {regimeHistory.map((entry, i) => (
                <tr key={i} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="py-2 px-2">
                    <span className="mono font-medium" style={{ color: REGIME_COLORS[entry.regime] || '#888' }}>{entry.regime}</span>
                  </td>
                  <td className="py-2 px-2 mono" style={{ color: (entry.btc_change_1h || 0) >= 0 ? '#1D9E75' : '#E24B4A' }}>
                    {(entry.btc_change_1h || 0).toFixed(1)}%
                  </td>
                  <td className="py-2 px-2 mono" style={{ color: (entry.btc_change_4h || 0) >= 0 ? '#1D9E75' : '#E24B4A' }}>
                    {(entry.btc_change_4h || 0).toFixed(1)}%
                  </td>
                  <td className="py-2 px-2 mono">{entry.fear_greed_index || '--'}</td>
                  <td className="py-2 px-2 mono">{(entry.kelly_multiplier || 0).toFixed(2)}x</td>
                  <td className="py-2 px-2 mono text-[var(--color-muted-foreground)]">
                    {entry.created_at ? new Date(entry.created_at).toLocaleString() : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
