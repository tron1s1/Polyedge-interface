import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { STRATEGIES } from '../../utils/constants'

export default function DailyPnLBarChart({ data, height = 250 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => v.slice(8)} />
        <YAxis tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => `$${v}`} />
        <Tooltip
          contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-border)', fontSize: 11, borderRadius: 0 }}
          formatter={(v) => [`$${v.toFixed(2)}`, '']}
        />
        {STRATEGIES.map(s => (
          <Bar key={s.id} dataKey={s.id} stackId="a" fill={s.color} name={s.shortName} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
