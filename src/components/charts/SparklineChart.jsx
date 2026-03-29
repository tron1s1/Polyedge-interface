import { AreaChart, Area, ResponsiveContainer } from 'recharts'

export default function SparklineChart({ data, color = '#1D9E75', height = 60 }) {
  const isPositive = data.length > 1 && data[data.length - 1].value >= data[0].value
  const c = isPositive ? (color || '#1D9E75') : '#E24B4A'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id={`spark-${c}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={c} stopOpacity={0.15} />
            <stop offset="95%" stopColor={c} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="value" stroke={c} strokeWidth={1.5} fill={`url(#spark-${c})`} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
