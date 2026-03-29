import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

export default function WinRateChart({ data, height = 250 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => v.slice(5)} />
        <YAxis domain={[50, 100]} tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} tickFormatter={v => `${v}%`} />
        <Tooltip contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-border)', fontSize: 11, borderRadius: 0 }} />
        <ReferenceLine y={60} stroke="var(--color-muted-foreground)" strokeDasharray="4 4" label={{ value: '60% target', fontSize: 10, fill: 'var(--color-muted-foreground)' }} />
        <Area type="monotone" dataKey="combined" stroke="var(--color-accent)" fill="rgba(255,0,43,0.05)" strokeWidth={2} dot={false} name="Combined" />
      </AreaChart>
    </ResponsiveContainer>
  )
}
