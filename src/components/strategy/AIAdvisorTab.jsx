import { Zap, TrendingUp, TrendingDown, Target } from 'lucide-react'
import { useMode } from '../../context/ModeContext'
import { STRATEGY_MAP } from '../../utils/constants'
import { getMockTrades, getTradeStats } from '../../data/mockTrades'
import { getActiveVersion } from '../../data/mockVersions'

export default function AIAdvisorTab({ strategyId }) {
  const { mode } = useMode()
  const strategy = STRATEGY_MAP[strategyId]
  const stats = getTradeStats(getMockTrades(strategyId, mode))
  const version = getActiveVersion(strategyId)

  const analyses = {
    'latency-arb': {
      grade: 'A-', gradeColor: '#1D9E75',
      strengths: [
        `Win rate of ${stats.winRate.toFixed(1)}% exceeds the 90% baseline target`,
        'Average latency of 142ms is competitive — top-layer pre-signing is working',
        `Kelly fraction producing good risk-adjusted returns (Sharpe ${version.sharpe})`,
      ],
      weaknesses: [
        'Gap threshold at 25% may be filtering out profitable 15-25% opportunities',
        'Oracle staleness guard at 90s is conservative — 82% of missed trades had oracle age 60-89s',
        'Flash crash guard triggered 4 false positives in last 50 trades',
      ],
      recommendations: [
        { param: 'Gap threshold', from: '25%', to: '18%', impact: '+12 trades/week at 76% win rate' },
        { param: 'Oracle staleness', from: '90s', to: '65s', impact: '+8 captures/week' },
        { param: 'Flash crash threshold', from: '2%', to: '3%', impact: '-60% false positives' },
      ],
    },
    'negrisk-arb': {
      grade: 'A+', gradeColor: '#1D9E75',
      strengths: ['100% win rate — mathematically guaranteed', 'Batch API reducing scan time by 40%', 'Catching 85% of available opportunities'],
      weaknesses: ['Some gaps close before all legs fill', 'Liquidity limits position size on smaller markets', 'Scan interval could be shorter during events'],
      recommendations: [
        { param: 'Scan interval', from: '60s', to: '30s', impact: 'Catch 15% more short-lived gaps' },
        { param: 'Min gap', from: '4%', to: '3%', impact: '+5 opportunities/day' },
      ],
    },
    'ai-news': {
      grade: 'B+', gradeColor: '#EF9F27',
      strengths: [`Win rate of ${stats.winRate.toFixed(1)}% with feedback loop active`, 'Superforecaster prompt outperforming basic prompt by 12%', 'Claude streaming cutting latency to 1.8s avg'],
      weaknesses: ['Overconfident on 80%+ calls (actual win rate 67%)', 'Social sentiment-only trades losing 8/9', 'Crypto category underperforming politics by 11%'],
      recommendations: [
        { param: 'Confidence multiplier', from: '1.0', to: '0.85', impact: 'Better calibration on high-confidence calls' },
        { param: 'Social-only blacklist', from: 'Off', to: 'On', impact: 'Eliminate worst losing pattern' },
        { param: 'Min edge', from: '15%', to: '12%', impact: '+8 trades/week with 72% win rate' },
      ],
    },
    'market-making': {
      grade: 'B', gradeColor: '#EF9F27',
      strengths: ['Spread capture consistent at 1.8% daily on deployed', 'Both-sides arb adding 30% to total returns', 'Kill switch preventing runaway inventory'],
      weaknesses: ['Inventory imbalance during news spikes', 'Missing opportunities on thin markets', 'Rebalance timing too slow during events'],
      recommendations: [
        { param: 'Rebalance interval', from: '30s', to: '15s', impact: '-40% inventory risk during spikes' },
        { param: 'Min spread', from: '2¢', to: '1.5¢', impact: '+20% more markets eligible' },
      ],
    },
  }

  const analysis = analyses[strategyId] || analyses['latency-arb']

  return (
    <div className="space-y-4">
      {/* Grade */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-6 flex items-center gap-6">
        <div className="text-[48px] font-medium mono" style={{ color: analysis.gradeColor }}>{analysis.grade}</div>
        <div>
          <div className="text-[14px] font-medium">AI Analysis — {version.name}</div>
          <div className="text-[12px] text-[var(--color-muted-foreground)] mt-1">Based on {stats.totalTrades} trades over the last 30 days</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Strengths */}
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} style={{ color: '#1D9E75' }} />
            <span className="text-[11px] font-medium uppercase tracking-wider text-[#1D9E75]">Strengths</span>
          </div>
          <ul className="space-y-2">
            {analysis.strengths.map((s, i) => (
              <li key={i} className="text-[12px] text-[var(--color-foreground)] flex items-start gap-2">
                <span className="text-[#1D9E75] mt-0.5">+</span> {s}
              </li>
            ))}
          </ul>
        </div>

        {/* Weaknesses */}
        <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown size={14} style={{ color: '#E24B4A' }} />
            <span className="text-[11px] font-medium uppercase tracking-wider text-[#E24B4A]">Weaknesses</span>
          </div>
          <ul className="space-y-2">
            {analysis.weaknesses.map((w, i) => (
              <li key={i} className="text-[12px] text-[var(--color-foreground)] flex items-start gap-2">
                <span className="text-[#E24B4A] mt-0.5">-</span> {w}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Recommendations */}
      <div className="border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Target size={14} style={{ color: '#185FA5' }} />
          <span className="text-[11px] font-medium uppercase tracking-wider text-[#185FA5]">Recommendations</span>
        </div>
        <div className="space-y-2">
          {analysis.recommendations.map((r, i) => (
            <div key={i} className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0">
              <div className="flex-1">
                <div className="text-[12px]">
                  Change <span className="font-medium">{r.param}</span> from <span className="mono">{r.from}</span> to <span className="mono font-medium" style={{ color: '#185FA5' }}>{r.to}</span>
                </div>
                <div className="text-[11px] text-[var(--color-muted-foreground)] mt-0.5">Expected: {r.impact}</div>
              </div>
              <button className="px-3 py-1.5 text-[10px] font-medium uppercase border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-white transition-colors">
                Apply
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Auto-enhance */}
      <button className="w-full flex items-center justify-center gap-2 py-3 bg-[var(--color-accent)] text-white text-[13px] font-medium hover:opacity-90 transition-opacity">
        <Zap size={16} /> AI Auto-Enhance — Apply All Recommendations
      </button>
    </div>
  )
}
