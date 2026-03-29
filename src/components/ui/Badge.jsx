import { cn } from '../../utils/formatters'

const variants = {
  paper: 'border-[#1D9E75] text-[#1D9E75]',
  live: 'bg-[#FF002B] text-white border-[#FF002B]',
  testing: 'border-[#185FA5] text-[#185FA5]',
  winner: 'border-[#1D9E75] text-[#1D9E75] bg-[#1D9E75]/10',
  retired: 'border-[var(--color-border)] text-[var(--color-muted-foreground)]',
  info: 'border-[#185FA5] text-[#185FA5]',
  warning: 'border-[#EF9F27] text-[#EF9F27]',
  danger: 'border-[#E24B4A] text-[#E24B4A]',
  success: 'border-[#1D9E75] text-[#1D9E75]',
}

export default function Badge({ children, variant = 'info', className }) {
  return (
    <span className={cn(
      'inline-flex items-center text-[10px] font-medium px-2 py-0.5 border uppercase tracking-wider',
      variants[variant] || variants.info,
      className
    )}>
      {children}
    </span>
  )
}
