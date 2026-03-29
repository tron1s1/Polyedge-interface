import { useState } from 'react'
import { useMode } from '../context/ModeContext'
import { Brain, DollarSign, Cpu } from 'lucide-react'
import { getAllTrades, getTradeStats } from '../data/mockTrades'
import MetricCard from '../components/ui/MetricCard'
import Badge from '../components/ui/Badge'
import TabBar from '../components/ui/TabBar'

export default function AILabPage() {
  const { mode, isPaper } = useMode()
  const [tab, setTab] = useState('overview')
  const stats = getTradeStats(getAllTrades(mode))

  const calibrationData = [
    { bin: '50-60%', stated: 55, actual: 52, trades: 28 },
    { bin: '60-70%', stated: 65, actual: 61, trades: 45 },
    { bin: '70-80%', stated: 75, actual: 69, trades: 38 },
    { bin: '80-90%', stated: 85, actual: 72, trades: 22 },
    { bin: '90-100%', stated: 95, actual: 84, trades: 8 },
  ]

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-[20px] font-medium">AI Lab</h1>
        <Badge variant={isPaper ? 'paper' : 'live'}>{isPaper ? 'Paper' : 'Live'}</Badge>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-5 gap-3">
        <MetricCard label="Claude API Spend (mo)" value="$14.20" />
        <MetricCard label="Total Tokens Used" value="847k" />
        <MetricCard label="Avg Tokens/Trade" value="3,200" />
        <MetricCard label="Cost/Profitable Trade" value="$0.18" />
        <MetricCard label="ROI on AI Spend" value="28:1" valueColor="#1D9E75" />
      </div>

      <TabBar
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'calibration', label: 'Calibration' },
          { id: 'feedback', label: 'Feedback Loop' },
          { id: 'prompt', label: 'Prompt Workshop' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'overview' && (
        <div className="grid grid-cols-2 gap-4">
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Source Credibility Ranking</div>
            {[
              { source: 'CoinDesk', winRate: 74, trades: 42, edge: '+18%' },
              { source: 'Reuters', winRate: 71, trades: 38, edge: '+14%' },
              { source: 'Glassnode', winRate: 69, trades: 28, edge: '+12%' },
              { source: 'AP News', winRate: 65, trades: 35, edge: '+8%' },
              { source: 'Twitter/X', winRate: 48, trades: 52, edge: '-3%' },
            ].map(s => (
              <div key={s.source} className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0">
                <span className="text-[12px]">{s.source}</span>
                <div className="flex items-center gap-3">
                  <span className="mono text-[11px]">{s.winRate}% WR</span>
                  <span className="mono text-[11px] text-[var(--color-muted-foreground)]">{s.trades} trades</span>
                  <span className="mono text-[11px]" style={{ color: s.edge.startsWith('+') ? '#1D9E75' : '#E24B4A' }}>{s.edge}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">Losing Patterns Identified</div>
            <div className="space-y-3">
              {[
                { pattern: 'Trading on "general market sentiment" alone', losses: '8/9 trades lost', action: 'Blacklisted' },
                { pattern: 'Social-only sources (Twitter without confirmation)', losses: '7/11 trades lost', action: 'Weight reduced' },
                { pattern: 'High confidence (>85%) on crypto during weekends', losses: '5/7 trades lost', action: 'Flagged' },
              ].map((p, i) => (
                <div key={i} className="border border-[var(--color-border)] p-3">
                  <div className="text-[12px] font-medium">{p.pattern}</div>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[11px] text-[#E24B4A]">{p.losses}</span>
                    <Badge variant="warning" className="text-[8px]">{p.action}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'calibration' && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
            Claude Calibration — Stated Confidence vs Actual Win Rate
          </div>
          <div className="text-[11px] text-[var(--color-muted-foreground)] mb-4">
            Perfect calibration = stated equals actual. Below diagonal = overconfident.
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-[var(--color-border)]">
                {['Confidence Bin', 'Stated Avg', 'Actual Win Rate', 'Delta', 'Trades', 'Calibration'].map(h => (
                  <th key={h} className="text-left py-2 px-2 text-[10px] uppercase text-[var(--color-muted-foreground)]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {calibrationData.map(d => {
                const delta = d.actual - d.stated
                return (
                  <tr key={d.bin} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-2 px-2 font-medium">{d.bin}</td>
                    <td className="py-2 px-2 mono">{d.stated}%</td>
                    <td className="py-2 px-2 mono">{d.actual}%</td>
                    <td className="py-2 px-2 mono" style={{ color: delta >= 0 ? '#1D9E75' : '#E24B4A' }}>{delta > 0 ? '+' : ''}{delta}%</td>
                    <td className="py-2 px-2 mono">{d.trades}</td>
                    <td className="py-2 px-2">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-2 bg-[var(--color-muted)]">
                          <div className="h-full" style={{
                            width: `${Math.min(100, (d.actual / d.stated) * 100)}%`,
                            backgroundColor: Math.abs(delta) <= 5 ? '#1D9E75' : Math.abs(delta) <= 10 ? '#EF9F27' : '#E24B4A'
                          }} />
                        </div>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-4 border border-[var(--color-border)] p-3">
            <div className="text-[12px] font-medium mb-1">Auto-Calibration Factor</div>
            <div className="text-[11px] text-[var(--color-muted-foreground)]">
              Current correction: multiply stated confidence by <span className="mono font-medium text-[var(--color-accent)]">0.85</span>
              <br />Your 80% calls win 72% → systematically overconfident by ~8%. Factor applied automatically.
            </div>
          </div>
        </div>
      )}

      {tab === 'feedback' && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
            What Claude Sees — Current Feedback Context
          </div>
          <div className="font-mono text-[11px] bg-[var(--color-muted)] p-4 leading-relaxed" style={{ whiteSpace: 'pre-wrap' }}>
{`PERFORMANCE CONTEXT (last 30 days, all categories):
Win rate: ${stats.winRate.toFixed(0)}% (${stats.wins} wins / ${stats.resolvedTrades} resolved)
Calibration: Your 80% calls win 72% → multiply confidence by 0.85

BEST SOURCES:
CoinDesk (+18% edge), Glassnode (+14%), Reuters (+12%)

WORST SOURCES:
Twitter/X (-3% edge) — weight DOWN by 50%

LOSING PATTERNS (BLACKLISTED):
- DO NOT trade on "general positive market sentiment" alone
- DO NOT rely solely on social media sentiment
- DO NOT assign >85% confidence on crypto during weekends

WINNING PATTERNS:
- On-chain data + macro catalyst together: 11/12 wins
- Multiple confirmed sources agreeing: 89% win rate
- Base rate anchoring before inside view: +7% calibration

POSITION SIZING:
- Kelly multiplier currently at 0.25 (quarter Kelly)
- Scale to 0.35 only when edge > 25% AND multiple sources confirm`}
          </div>
        </div>
      )}

      {tab === 'prompt' && (
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
            Superforecaster Prompt Template
          </div>
          <textarea
            className="w-full h-64 font-mono text-[11px] bg-[var(--color-muted)] border border-[var(--color-border)] p-4 resize-y text-[var(--color-foreground)]"
            defaultValue={`You are a calibrated superforecaster. Reason in this exact order:

1. BASE RATE: How often have similar markets resolved YES historically?
   (from provided data: {base_rate_data})

2. OUTSIDE VIEW: Ignoring specifics, what does the reference class predict?

3. INSIDE VIEW: What specific evidence updates you away from base rate?
   News context: {news_summary}

4. CALIBRATION: Am I overconfident? Check my past accuracy: {performance_context}

5. FINAL: State probability as a single number 0.00–1.00.
   State your edge vs current market odds: {market_odds}
   ONLY recommend trading if edge > 0.15 and confidence > 0.65.

Return JSON: {probability, edge, trade_recommended, reasoning_summary}`}
          />
          <div className="flex items-center justify-between mt-3">
            <span className="text-[11px] text-[var(--color-muted-foreground)]">Changes will create a new prompt version for A/B testing</span>
            <button className="px-4 py-2 bg-[var(--color-foreground)] text-[var(--color-background)] text-[11px] font-medium">
              Save as New Prompt Version
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
