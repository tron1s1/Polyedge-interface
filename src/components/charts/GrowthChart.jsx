import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export default function GrowthChart({ data, height = 280 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis dataKey="month" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} />
        <YAxis tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
        <Tooltip contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-border)', fontSize: 11, borderRadius: 0 }} formatter={v => [`$${v.toLocaleString()}`, '']} />
        <Line type="monotone" dataKey="actual" stroke="#1D9E75" strokeWidth={2} dot={false} name="Actual" />
        <Line type="monotone" dataKey="projected" stroke="#EF9F27" strokeWidth={1} strokeDasharray="4 4" dot={false} name="Projected" />
      </LineChart>
    </ResponsiveContainer>
  )
}
