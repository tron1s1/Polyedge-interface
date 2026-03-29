export default function Toggle({ checked, onChange, labelOn = 'ON', labelOff = 'OFF', colorOn = '#1D9E75', colorOff = 'var(--color-muted-foreground)' }) {
  return (
    <button
      onClick={onChange}
      className="flex items-center gap-2 cursor-pointer select-none"
    >
      <div
        className="relative w-10 h-5 transition-colors"
        style={{ backgroundColor: checked ? colorOn : 'var(--color-muted)' }}
      >
        <div
          className="absolute top-0.5 w-4 h-4 bg-white transition-all"
          style={{ left: checked ? '22px' : '2px' }}
        />
      </div>
      <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: checked ? colorOn : colorOff }}>
        {checked ? labelOn : labelOff}
      </span>
    </button>
  )
}
