import { cn } from '../../utils/formatters'

export default function MetricCard({ label, value, detail, valueColor, className }) {
  return (
    <div className={cn('border border-[var(--color-border)] bg-[var(--color-card)] p-4', className)}>
      <div className="text-[11px] font-medium tracking-wider uppercase text-[var(--color-muted-foreground)]">
        {label}
      </div>
      <div
        className="mono text-[28px] font-medium mt-1"
        style={{ color: valueColor || 'var(--color-foreground)' }}
      >
        {value}
      </div>
      {detail && (
        <div className="text-[11px] text-[var(--color-muted-foreground)] mt-1">{detail}</div>
      )}
    </div>
  )
}
