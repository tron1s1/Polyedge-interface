import { useState, useCallback, useMemo } from 'react'
import { useMode } from '../context/ModeContext'
import { REGIME_COLORS, NODES } from '../utils/constants'
import { api } from '../lib/api'
import { usePolling, useRealtimeTable } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/formatters'
import { Radio, Activity, Server } from 'lucide-react'

function ScoreBadge({ score }) {
  const color = score >= 80 ? '#1D9E75' : score >= 60 ? '#EF9F27' : '#E24B4A'
  return (
    <span className="mono text-[10px] font-medium px-1.5 py-0.5 inline-block" style={{ backgroundColor: color + '15', color }}>
      {Math.round(score)}
    </span>
  )
}

function StrategyTag({ name }) {
  // Color by category prefix
  const color =
    name.startsWith('A_') ? '#1D9E75' :
    name.startsWith('B_') ? '#185FA5' :
    name.startsWith('C_') ? '#EF9F27' :
    name.startsWith('D_') ? '#E24B4A' : '#6B7280'

  return (
    <span
      className="mono text-[8px] font-medium px-1 py-0.5 border shrink-0"
      style={{ borderColor: color + '40', color, backgroundColor: color + '10' }}
    >
      {name}
    </span>
  )
}

function CycleRow({ cycle }) {
  return (
    <div className="flex items-center gap-4 px-3 py-2 border-b border-[var(--color-border)] last:border-b-0 text-[11px]">
      <span className="mono text-[10px] text-[var(--color-muted-foreground)] w-[140px] shrink-0">
        {new Date(cycle.cycle_at).toLocaleTimeString()}
      </span>
      <span className="mono font-medium w-[80px] shrink-0">{cycle.markets_scored} mkts</span>
      <span className="mono w-[80px] shrink-0" style={{ color: cycle.duration_ms < 500 ? '#1D9E75' : '#EF9F27' }}>
        {Math.round(cycle.duration_ms)}ms
      </span>
      <span className="mono w-[100px] shrink-0" style={{ color: REGIME_COLORS[cycle.regime] || '#888' }}>
        {cycle.regime}
      </span>
      <span className="text-[var(--color-muted-foreground)] truncate flex-1">{cycle.slot}</span>
    </div>
  )
}

export default function ScannerPage() {
  const { isPaper } = useMode()
  const [selectedNode, setSelectedNode] = useState('singapore-01')

  const fetchCycles = useCallback(() => api.getScannerLive(selectedNode), [selectedNode])
  const fetchOpps = useCallback(() => api.getScannerOpportunities(selectedNode), [selectedNode])

  const { data: scanData } = usePolling(fetchCycles, 5000)
  const { data: oppData } = usePolling(fetchOpps, 5000)
  const { data: riskData } = usePolling(useCallback(() => api.getRiskCurrent(), []), 10000)

  useRealtimeTable('scanner_cycles', { onInsert: () => {} })

  const cycles = scanData?.cycles || []
  const opportunities = oppData?.top_opportunities || []
  const regime = riskData?.regime || 'UNKNOWN'
  const latestCycle = cycles[0]

  const selectedNodeInfo = NODES.find(n => n.id === selectedNode)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">Live Scanner</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper' : 'Live'}</Badge>
        <span className="mono text-[11px] text-[var(--color-muted-foreground)]">
          Live data from scanner_cycles table · polling every 5s
        </span>
      </div>

      {/* Node Selector */}
      <div className="flex items-center gap-2">
        {NODES.map(node => (
          <button
            key={node.id}
            onClick={() => setSelectedNode(node.id)}
            className={cn(
              'flex items-center gap-2 px-4 py-2 text-[11px] font-medium border transition-colors cursor-pointer',
              selectedNode === node.id
                ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                : 'border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:border-[var(--color-muted-foreground)]'
            )}
          >
            <Server size={12} />
            {node.name}
          </button>
        ))}
      </div>

      {/* Latest Cycle Summary */}
      {latestCycle ? (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Latest Scan Cycle</div>
          <div className="grid grid-cols-5 gap-4">
            <div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">Markets Scored</div>
              <div className="mono text-[20px] font-medium mt-1">{latestCycle.markets_scored}</div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">Duration</div>
              <div className="mono text-[20px] font-medium mt-1" style={{ color: latestCycle.duration_ms < 500 ? '#1D9E75' : '#EF9F27' }}>
                {Math.round(latestCycle.duration_ms)}ms
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">Regime</div>
              <div className="mono text-[20px] font-medium mt-1" style={{ color: REGIME_COLORS[latestCycle.regime] || '#888' }}>
                {latestCycle.regime}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">Time</div>
              <div className="mono text-[20px] font-medium mt-1">
                {new Date(latestCycle.cycle_at).toLocaleTimeString()}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">Slot</div>
              <div className="mono text-[20px] font-medium mt-1">{latestCycle.slot}</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-6 text-center text-[11px] text-[var(--color-muted-foreground)]">
          No scan data for {selectedNodeInfo?.name || selectedNode}. Start the scanner to see live cycles.
        </div>
      )}

      {/* Top Opportunities */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <Radio size={14} className="text-[var(--color-accent)]" />
          <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Top Opportunities
          </span>
          <span className="text-[10px] text-[var(--color-muted-foreground)] ml-auto">
            Score = composite of 12 signals (funding, arb gap, volume, fear/greed, news, etc.)
          </span>
        </div>
        <div className="max-h-[400px] overflow-y-auto">
          {opportunities.length > 0 ? opportunities.map((opp, i) => (
            <div key={i} className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)] last:border-0 text-[11px]">
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-medium w-[100px] shrink-0">{opp.symbol || opp.market_id || `Market ${i + 1}`}</span>
                <span className="text-[var(--color-muted-foreground)] w-[60px] shrink-0">{opp.exchange}</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap justify-end">
                {(opp.suggested_strategies || []).map(s => (
                  <StrategyTag key={s} name={s} />
                ))}
                <ScoreBadge score={opp.opportunity_score || opp.score || 0} />
              </div>
            </div>
          )) : (
            <div className="px-4 py-6 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No scanner data yet for this node. Run the scanner to see live opportunities.
            </div>
          )}
        </div>
      </div>

      {/* Recent Scan Cycles */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)]">
          <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Recent Scan Cycles ({cycles.length})
          </span>
        </div>
        <div className="flex items-center gap-4 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-muted)]/30 text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          <span className="w-[140px] shrink-0">Time</span>
          <span className="w-[80px] shrink-0">Markets</span>
          <span className="w-[80px] shrink-0">Duration</span>
          <span className="w-[100px] shrink-0">Regime</span>
          <span className="flex-1">Slot</span>
        </div>
        <div className="max-h-[500px] overflow-y-auto">
          {cycles.length > 0 ? cycles.map((c, i) => <CycleRow key={i} cycle={c} />) : (
            <div className="px-4 py-6 text-center text-[11px] text-[var(--color-muted-foreground)]">
              No scan cycles recorded for {selectedNodeInfo?.name || selectedNode}.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
