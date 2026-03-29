import { useState } from 'react'
import { Activity, Zap, TrendingUp, ChevronDown, ChevronUp, Save, Clock, BarChart3 } from 'lucide-react'
import { getMethodsForStrategy, getMethodPerformance, getMethodVersions } from '../../data/mockLatencyMethods'
import { TIME_RANGES } from '../../data/mockTrades'
import { formatMs } from '../../utils/formatters'
import Badge from '../ui/Badge'

function MethodCard({ method, strategyId, timeRange, expanded, onToggle }) {
  const perf = getMethodPerformance(strategyId, method.id, timeRange)
  const [vA, vB] = perf.versions
  const statusColor = perf.status === 'winner' ? '#1D9E75' : '#EF9F27'
  const statusLabel = perf.status === 'winner' ? 'Winner' : 'Testing'

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)]">
      {/* Header — always visible */}
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left">
        <span className="mono text-[11px] font-medium px-1.5 py-0.5 border border-[var(--color-border)] bg-[var(--color-muted)]">{method.id}</span>
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-medium">{method.name}</div>
          <div className="text-[10px] text-[var(--color-muted-foreground)] truncate">{method.description}</div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {/* Quick stats */}
          <div className="text-right">
            <div className="mono text-[11px] font-medium" style={{ color: '#1D9E75' }}>-{perf.latencyImprovement}%</div>
            <div className="text-[9px] text-[var(--color-muted-foreground)]">latency</div>
          </div>
          <div className="text-right">
            <div className="mono text-[11px] font-medium">{vA.winRate}%</div>
            <div className="text-[9px] text-[var(--color-muted-foreground)]">win rate</div>
          </div>
          <div className="text-right">
            <div className="mono text-[11px] font-medium" style={{ color: vA.totalPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>
              ${vA.totalPnl.toFixed(0)}
            </div>
            <div className="text-[9px] text-[var(--color-muted-foreground)]">P&L</div>
          </div>
          <Badge variant={perf.status === 'winner' ? 'winner' : 'testing'} className="text-[9px]">
            {statusLabel}
          </Badge>
          {/* Sample progress */}
          <div className="w-16">
            <div className="text-[9px] text-[var(--color-muted-foreground)] text-right">{vA.trades}/50</div>
            <div className="w-full h-1 bg-[var(--color-muted)] mt-0.5">
              <div className="h-full" style={{ width: `${perf.sampleProgress}%`, backgroundColor: perf.sampleSufficient ? '#1D9E75' : '#EF9F27' }} />
            </div>
          </div>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* Expanded A/B comparison */}
      {expanded && (
        <div className="border-t border-[var(--color-border)] px-4 py-4 space-y-4">
          {/* A/B comparison table */}
          <div>
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">A/B Performance Comparison</div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-[var(--color-border)]">
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Version</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Trades</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Avg Latency</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">P50</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">P95</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">P99</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Win Rate</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Avg P&L</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Edge</th>
                  <th className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">Cost/Trade</th>
                </tr>
              </thead>
              <tbody>
                {[vA, vB].map(v => {
                  const isWinner = v.id === 'A'
                  return (
                    <tr key={v.id} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="py-2 px-2 font-medium">
                        <span className="flex items-center gap-1.5">
                          <span className="w-2 h-2 inline-block" style={{ backgroundColor: isWinner ? '#1D9E75' : 'var(--color-muted-foreground)', borderRadius: '50%' }} />
                          {v.label}
                        </span>
                      </td>
                      <td className="py-2 px-2 mono">{v.trades}</td>
                      <td className="py-2 px-2 mono" style={{ color: isWinner ? '#1D9E75' : '#E24B4A' }}>{v.avgLatency}ms</td>
                      <td className="py-2 px-2 mono">{v.p50Latency}ms</td>
                      <td className="py-2 px-2 mono">{v.p95Latency}ms</td>
                      <td className="py-2 px-2 mono">{v.p99Latency}ms</td>
                      <td className="py-2 px-2 mono" style={{ color: v.winRate > 80 ? '#1D9E75' : '#EF9F27' }}>{v.winRate}%</td>
                      <td className="py-2 px-2 mono" style={{ color: v.avgPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>${v.avgPnl}</td>
                      <td className="py-2 px-2 mono">{v.edgeCaptured}%</td>
                      <td className="py-2 px-2 mono">${v.costPerTrade}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Delta summary */}
          <div className="grid grid-cols-4 gap-3">
            <div className="bg-[var(--color-muted)] p-3">
              <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase">Latency Delta</div>
              <div className="mono text-[14px] font-medium mt-1" style={{ color: '#1D9E75' }}>-{perf.latencyDelta}ms</div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">{perf.latencyImprovement}% faster</div>
            </div>
            <div className="bg-[var(--color-muted)] p-3">
              <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase">Win Rate Delta</div>
              <div className="mono text-[14px] font-medium mt-1" style={{ color: vA.winRate > vB.winRate ? '#1D9E75' : '#E24B4A' }}>
                {vA.winRate > vB.winRate ? '+' : ''}{(vA.winRate - vB.winRate).toFixed(1)}%
              </div>
            </div>
            <div className="bg-[var(--color-muted)] p-3">
              <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase">P&L Delta</div>
              <div className="mono text-[14px] font-medium mt-1" style={{ color: '#1D9E75' }}>
                +${(vA.totalPnl - vB.totalPnl).toFixed(2)}
              </div>
            </div>
            <div className="bg-[var(--color-muted)] p-3">
              <div className="text-[10px] text-[var(--color-muted-foreground)] uppercase">Sample Status</div>
              <div className="text-[14px] font-medium mt-1" style={{ color: perf.sampleSufficient ? '#1D9E75' : '#EF9F27' }}>
                {perf.sampleSufficient ? 'Sufficient' : 'Collecting'}
              </div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">{vA.trades} / 50 trades needed</div>
            </div>
          </div>

          {/* Latency distribution bars */}
          <div>
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">Latency Distribution</div>
            <div className="grid grid-cols-2 gap-4">
              {[vA, vB].map(v => (
                <div key={v.id}>
                  <div className="text-[10px] font-medium mb-2">{v.label}</div>
                  {[
                    { label: 'P50', value: v.p50Latency, max: Math.max(vA.p99Latency, vB.p99Latency) },
                    { label: 'P95', value: v.p95Latency, max: Math.max(vA.p99Latency, vB.p99Latency) },
                    { label: 'P99', value: v.p99Latency, max: Math.max(vA.p99Latency, vB.p99Latency) },
                  ].map(bar => (
                    <div key={bar.label} className="flex items-center gap-2 mb-1">
                      <span className="mono text-[9px] w-6 text-[var(--color-muted-foreground)]">{bar.label}</span>
                      <div className="flex-1 h-3 bg-[var(--color-muted)]">
                        <div className="h-full" style={{
                          width: `${(bar.value / bar.max) * 100}%`,
                          backgroundColor: v.id === 'A' ? '#1D9E75' : '#E24B4A',
                          opacity: bar.label === 'P99' ? 0.5 : bar.label === 'P95' ? 0.7 : 1,
                        }} />
                      </div>
                      <span className="mono text-[9px] w-12 text-right">{bar.value}ms</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MethodConfigEditor({ method, onSaveVersion }) {
  const [config, setConfig] = useState(() => {
    if (!method.params) return {}
    return Object.fromEntries(method.params.map(p => [p.key, p.default]))
  })

  if (!method.configurable || !method.params) return null

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
          {method.id} Configuration
        </div>
        <button
          onClick={() => onSaveVersion(method.id, config)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--color-accent)] text-white text-[11px] font-medium hover:opacity-90"
        >
          <Save size={12} /> Save as New Version
        </button>
      </div>
      <div className="space-y-3">
        {method.params.map(p => {
          if (p.type === 'toggle') {
            return (
              <div key={p.key} className="flex items-center justify-between">
                <span className="text-[11px] text-[var(--color-muted-foreground)]">{p.label}</span>
                <button
                  onClick={() => setConfig(c => ({ ...c, [p.key]: !c[p.key] }))}
                  className={`w-9 h-5 relative transition-colors ${config[p.key] ? 'bg-[#1D9E75]' : 'bg-[var(--color-muted)]'}`}
                >
                  <div className="absolute top-0.5 w-4 h-4 bg-white transition-all" style={{ left: config[p.key] ? '18px' : '2px' }} />
                </button>
              </div>
            )
          }
          if (p.type === 'select') {
            return (
              <div key={p.key} className="flex items-center gap-3">
                <span className="text-[11px] text-[var(--color-muted-foreground)] w-40 shrink-0">{p.label}</span>
                <select
                  value={config[p.key]}
                  onChange={e => setConfig(c => ({ ...c, [p.key]: e.target.value }))}
                  className="flex-1 bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-foreground)]"
                >
                  {p.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            )
          }
          if (p.type === 'text') {
            return (
              <div key={p.key} className="flex items-center gap-3">
                <span className="text-[11px] text-[var(--color-muted-foreground)] w-40 shrink-0">{p.label}</span>
                <input
                  type="text"
                  value={config[p.key]}
                  onChange={e => setConfig(c => ({ ...c, [p.key]: e.target.value }))}
                  className="flex-1 bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] mono text-[var(--color-foreground)]"
                />
              </div>
            )
          }
          // Default: slider
          return (
            <div key={p.key} className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--color-muted-foreground)] w-40 shrink-0">{p.label}</span>
              <input
                type="range"
                min={p.min}
                max={p.max}
                step={p.step}
                value={config[p.key]}
                onChange={e => setConfig(c => ({ ...c, [p.key]: Number(e.target.value) }))}
                className="flex-1 h-1 accent-[var(--color-accent)]"
              />
              <span className="mono text-[12px] font-medium w-16 text-right">{config[p.key]}{p.unit}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MethodVersionHistory({ strategyId, methodId }) {
  const versions = getMethodVersions(strategyId, methodId)
  if (!versions.length) return null

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">
        Version History — {methodId}
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[var(--color-border)]">
            {['Version', 'Created', 'Trades', 'Avg Latency', 'Win Rate', 'Avg P&L', 'Status'].map(h => (
              <th key={h} className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {versions.map(v => (
            <tr key={v.id} className="border-b border-[var(--color-border)] last:border-0">
              <td className="py-2 px-2 mono font-medium">{v.name}</td>
              <td className="py-2 px-2 mono text-[var(--color-muted-foreground)]">{v.createdAt.toLocaleDateString()}</td>
              <td className="py-2 px-2 mono">{v.trades}</td>
              <td className="py-2 px-2 mono">{v.avgLatency}ms</td>
              <td className="py-2 px-2 mono" style={{ color: v.winRate > 80 ? '#1D9E75' : '#EF9F27' }}>{v.winRate}%</td>
              <td className="py-2 px-2 mono" style={{ color: v.avgPnl >= 0 ? '#1D9E75' : '#E24B4A' }}>${v.avgPnl}</td>
              <td className="py-2 px-2">
                <Badge variant={v.status} className="text-[9px]">{v.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function LatencyLabTab({ strategyId }) {
  const [timeRange, setTimeRange] = useState('1m')
  const [expandedMethod, setExpandedMethod] = useState(null)
  const [activeSection, setActiveSection] = useState('performance') // performance | config | versions
  const methods = getMethodsForStrategy(strategyId)

  const handleSaveVersion = (methodId, config) => {
    // In real app, this would save to Supabase
    alert(`Saved new version for ${methodId} with config: ${JSON.stringify(config)}`)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap size={16} className="text-[var(--color-accent)]" />
          <span className="text-[13px] font-medium">Top Layer Latency Methods</span>
          <span className="mono text-[11px] text-[var(--color-muted-foreground)]">{methods.length} methods for this strategy</span>
        </div>
        <select
          value={timeRange}
          onChange={e => setTimeRange(e.target.value)}
          className="bg-[var(--color-input-bg)] border border-[var(--color-border)] px-3 py-1.5 text-[11px] mono text-[var(--color-foreground)] cursor-pointer"
        >
          {TIME_RANGES.map(r => (
            <option key={r.id} value={r.id}>{r.label}</option>
          ))}
        </select>
      </div>

      {/* Section tabs */}
      <div className="flex items-center gap-1 border-b border-[var(--color-border)]">
        {[
          { id: 'performance', label: 'A/B Performance', icon: BarChart3 },
          { id: 'config', label: 'Configure Methods', icon: Activity },
          { id: 'versions', label: 'Version History', icon: Clock },
        ].map(s => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium border-b-2 -mb-[1px] transition-colors ${
              activeSection === s.id
                ? 'border-[var(--color-accent)] text-[var(--color-foreground)]'
                : 'border-transparent text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
            }`}
          >
            <s.icon size={12} />
            {s.label}
          </button>
        ))}
      </div>

      {/* Info banner */}
      <div className="border border-[var(--color-border)] bg-[var(--color-muted)] px-4 py-2 text-[11px] text-[var(--color-muted-foreground)]">
        {activeSection === 'performance' && 'Each method runs an A/B test: Enabled vs Baseline. Markets are split randomly between versions. After 50 trades, the winner is auto-promoted to live.'}
        {activeSection === 'config' && 'Adjust parameters for configurable methods. Saving creates a new version that enters A/B testing automatically.'}
        {activeSection === 'versions' && 'History of all parameter versions tested. Winner versions are promoted to live trading. Retired versions are archived.'}
      </div>

      {/* Performance section — method cards */}
      {activeSection === 'performance' && (
        <div className="space-y-2">
          {methods.map(method => (
            <MethodCard
              key={method.id}
              method={method}
              strategyId={strategyId}
              timeRange={timeRange}
              expanded={expandedMethod === method.id}
              onToggle={() => setExpandedMethod(expandedMethod === method.id ? null : method.id)}
            />
          ))}
        </div>
      )}

      {/* Config section */}
      {activeSection === 'config' && (
        <div className="space-y-3">
          {methods.filter(m => m.configurable).map(method => (
            <MethodConfigEditor key={method.id} method={method} onSaveVersion={handleSaveVersion} />
          ))}
          {methods.filter(m => !m.configurable).length > 0 && (
            <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
              <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">
                Non-configurable Methods (Infrastructure)
              </div>
              <div className="space-y-2">
                {methods.filter(m => !m.configurable).map(m => (
                  <div key={m.id} className="flex items-center gap-2 py-1.5">
                    <span className="mono text-[10px] font-medium px-1.5 py-0.5 border border-[var(--color-border)] bg-[var(--color-muted)]">{m.id}</span>
                    <span className="text-[11px]">{m.name}</span>
                    <span className="text-[10px] text-[var(--color-muted-foreground)]">— {m.description}</span>
                    <Badge variant="winner" className="text-[9px] ml-auto">Always On</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Versions section */}
      {activeSection === 'versions' && (
        <div className="space-y-3">
          {methods.filter(m => m.configurable).map(method => (
            <MethodVersionHistory key={method.id} strategyId={strategyId} methodId={method.id} />
          ))}
        </div>
      )}
    </div>
  )
}
