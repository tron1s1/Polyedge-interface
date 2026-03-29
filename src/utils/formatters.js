export function formatCurrency(value, decimals = 2) {
  if (value == null) return '$0.00'
  const sign = value < 0 ? '-' : value > 0 ? '+' : ''
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`
  return `${sign}$${abs.toFixed(decimals)}`
}

export function formatUSD(value, decimals = 2) {
  if (value == null) return '$0.00'
  return `$${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
}

export function formatPercent(value, decimals = 1) {
  if (value == null) return '0%'
  return `${value.toFixed(decimals)}%`
}

export function formatMs(value) {
  if (value == null) return '0ms'
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.round(value)}ms`
}

export function formatTimestamp(date) {
  if (!date) return ''
  const d = new Date(date)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatDate(date) {
  if (!date) return ''
  const d = new Date(date)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatRelativeTime(date) {
  if (!date) return ''
  const diff = Date.now() - new Date(date).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function cn(...classes) {
  return classes.filter(Boolean).join(' ')
}
