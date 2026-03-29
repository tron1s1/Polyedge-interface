export default function AllocationBar({ data, total }) {
  const undeployed = total - data.reduce((s, d) => s + d.amount, 0)
  return (
    <div>
      <div className="flex h-10 overflow-hidden">
        {data.map(d => (
          <div
            key={d.id}
            className="flex items-center justify-center text-[10px] font-medium text-white"
            style={{ width: `${d.percent}%`, backgroundColor: d.color }}
          >
            {d.percent >= 12 && `${d.name} ${d.percent}%`}
          </div>
        ))}
      </div>
      <div className="text-[11px] text-[var(--color-muted-foreground)] mt-2">
        Undeployed: ${undeployed.toLocaleString()} ({((undeployed / total) * 100).toFixed(1)}%)
        <span className="ml-3 text-[10px] italic">Allocation is dynamically managed based on market conditions</span>
      </div>
    </div>
  )
}
