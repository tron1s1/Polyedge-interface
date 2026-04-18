import { useState, useEffect } from 'react'
import Badge from '../ui/Badge'
import { TrendingUp, CheckCircle, Activity, WifiOff } from 'lucide-react'
import { api } from '../../lib/api'

export default function TriangleScannerTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      const result = await api.getTriangleScannerData(50)
      if (mounted && result) setData(result)
      setLoading(false)
    }
    poll()
    const interval = setInterval(poll, 5000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  const stats = data?.graph_stats || {}
  const status = data?.status || 'offline'
  const isLive = status === 'running'
  const pairs = stats.total_pairs || 0
  const triangles = stats.total_triangles || 0
  const currencies = stats.total_currencies || 0
  const bestProfit = stats.best_profit_pct ?? null
  const bestTriangle = stats.best_triangle || ''
  const checked = stats.checked_count || 0
  const feedConnected = stats.feed_connected ?? false
  const graphBuilt = stats.graph_built_at || ''

  const feePct = stats.fee_per_leg_pct ?? 0.075
  const minProfit = stats.min_net_profit_pct ?? 0.02
  const totalFees = (feePct * 3).toFixed(3)

  return (
    <div className="space-y-5">
      {/* Status Banner */}
      {isLive ? (
        <div className="flex items-center gap-2 p-3 border border-[#1D9E75] bg-[#1D9E75]/10 rounded">
          <Activity size={16} className="text-[#1D9E75] animate-pulse" />
          <span className="text-[11px] font-medium text-[#1D9E75]">
            Scanner is LIVE and evaluating triangles in real-time
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-3 border border-[var(--color-border)] bg-[var(--color-muted)] rounded">
          <WifiOff size={16} className="text-[var(--color-muted-foreground)]" />
          <span className="text-[11px] font-medium text-[var(--color-muted-foreground)]">
            Scanner is offline. Start the scanner to see live data.
          </span>
        </div>
      )}

      {/* Graph Statistics */}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3 font-medium">
          Graph Statistics
        </div>
        <div className="grid grid-cols-4 gap-3">
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Pairs</div>
            <div className="mono text-[20px] font-medium mt-1" style={{ color: '#1D9E75' }}>
              {pairs || '--'}
            </div>
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Currencies</div>
            <div className="mono text-[20px] font-medium mt-1" style={{ color: '#1D9E75' }}>
              {currencies || '--'}
            </div>
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Triangles</div>
            <div className="mono text-[20px] font-medium mt-1" style={{ color: '#1D9E75' }}>
              {triangles || '--'}
            </div>
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-3">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">Feed Status</div>
            <div className="text-[12px] font-medium mt-1" style={{ color: feedConnected ? '#1D9E75' : '#E24B4A' }}>
              {feedConnected ? '✓ Connected' : '✗ Offline'}
            </div>
          </div>
        </div>
      </div>

      {/* Best Edge */}
      {bestProfit !== null && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] font-medium">
            Best Edge (Real-time)
          </div>
          <div className="flex items-baseline gap-3">
            <span className="mono text-[24px] font-medium" style={{ color: bestProfit > 0 ? '#1D9E75' : '#E24B4A' }}>
              {bestProfit > 0 ? '+' : ''}{bestProfit.toFixed(4)}%
            </span>
            <span className="text-[10px] text-[var(--color-muted-foreground)]">
              net after {totalFees}% fees
            </span>
          </div>
          {bestTriangle && (
            <div className="text-[10px] text-[var(--color-muted-foreground)]">
              Triangle: <span className="mono font-medium text-[var(--color-foreground)]">{bestTriangle}</span>
            </div>
          )}
          {checked > 0 && (
            <div className="text-[10px] text-[var(--color-muted-foreground)]">
              Checked: <span className="mono">{checked.toLocaleString()}</span> triangles this cycle
            </div>
          )}
        </div>
      )}

      {/* Current Status */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <CheckCircle size={14} className="text-[#1D9E75]" />
          <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Current Status
          </span>
          <Badge variant={isLive ? 'success' : 'default'} className="text-[8px]">
            {isLive ? 'LIVE' : 'OFFLINE'}
          </Badge>
        </div>
        <div className="space-y-1 text-[10px]">
          {graphBuilt && (
            <p>
              <span className="text-[var(--color-muted-foreground)]">Graph built:</span>{' '}
              <span className="mono font-medium text-[#1D9E75]">{graphBuilt}</span>
            </p>
          )}
          <p>
            <span className="text-[var(--color-muted-foreground)]">Triangles discovered:</span>{' '}
            <span className="mono font-medium text-[#1D9E75]">{triangles} valid cycles</span>
          </p>
          <p>
            <span className="text-[var(--color-muted-foreground)]">Fee per leg:</span>{' '}
            <span className="mono font-medium text-[#1D9E75]">{feePct}% ({totalFees}% total)</span>
          </p>
          <p>
            <span className="text-[var(--color-muted-foreground)]">Min profit threshold:</span>{' '}
            <span className="mono font-medium text-[#1D9E75]">{minProfit}% net</span>
          </p>
        </div>
      </div>

      {/* Instructions */}
      <div className="border border-[#EF9F27] bg-[#EF9F27]/10 p-4 space-y-2">
        <div className="text-[10px] font-medium text-[#EF9F27] uppercase tracking-wider">
          Check the "Trades" tab above
        </div>
        <div className="text-[10px] text-[#EF9F27]">
          Profitable opportunities appear here as they're executed. With {triangles || '...'} triangles
          being checked continuously, trades fire when edges exceed {minProfit}% net profit.
        </div>
      </div>
    </div>
  )
}
