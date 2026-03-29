import { cn } from '../../utils/formatters'

export default function TabBar({ tabs, active, onChange, className }) {
  return (
    <div className={cn('flex gap-0 border-b border-[var(--color-border)]', className)}>
      {tabs.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            'px-4 py-2.5 text-[12px] font-medium transition-colors relative',
            active === tab.id
              ? 'text-[var(--color-foreground)] after:absolute after:bottom-0 after:left-0 after:right-0 after:h-[2px] after:bg-[var(--color-accent)]'
              : 'text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
