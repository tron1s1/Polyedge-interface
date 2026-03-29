import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { STRATEGIES } from '../../utils/constants'

export default function CumulativePnLChart({ data, height = 300 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => v.slice(5)} />
        <YAxis tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => `$${v}`} />
        <Tooltip
          contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-border)', fontSize: 11, borderRadius: 0 }}
          formatter={(v) => [`$${v.toFixed(2)}`, '']}
        />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Line type="monotone" dataKey="total" stroke="var(--color-accent)" strokeWidth={2} dot={false} name="Total" />
        {STRATEGIES.map(s => (
          <Line key={s.id} type="monotone" dataKey={s.id} stroke={s.color} strokeWidth={1} dot={false} name={s.shortName} opacity={0.6} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
