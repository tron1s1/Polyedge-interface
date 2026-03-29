export default function StatusDot({ color = '#1D9E75', size = 8 }) {
  return (
    <span
      className="inline-block shrink-0"
      style={{ width: size, height: size, backgroundColor: color, borderRadius: '50%' }}
    />
  )
}
