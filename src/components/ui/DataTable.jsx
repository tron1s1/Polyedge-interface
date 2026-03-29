import { useState, useMemo } from 'react'
import { cn } from '../../utils/formatters'

export default function DataTable({ columns, data, pageSize = 20, onRowClick, emptyMessage = 'No data' }) {
  const [sortKey, setSortKey] = useState(null)
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(0)

  const sorted = useMemo(() => {
    if (!sortKey) return data
    return [...data].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [data, sortKey, sortDir])

  const totalPages = Math.ceil(sorted.length / pageSize)
  const pageData = sorted.slice(page * pageSize, (page + 1) * pageSize)

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (!data.length) {
    return <div className="text-center py-8 text-[var(--color-muted-foreground)] text-[13px]">{emptyMessage}</div>
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  onClick={() => col.sortable !== false && handleSort(col.key)}
                  className={cn(
                    'text-left font-medium text-[var(--color-muted-foreground)] px-2 py-2 border-b border-[var(--color-border)] uppercase tracking-wider text-[10px]',
                    col.sortable !== false && 'cursor-pointer hover:text-[var(--color-foreground)]'
                  )}
                  style={{ minWidth: col.width }}
                >
                  {col.label}
                  {sortKey === col.key && (sortDir === 'asc' ? ' ↑' : ' ↓')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageData.map((row, i) => (
              <tr
                key={row.id || i}
                onClick={() => onRowClick?.(row)}
                className={cn(
                  'border-b border-[var(--color-border)] hover:bg-[var(--color-muted)]/50',
                  onRowClick && 'cursor-pointer'
                )}
              >
                {columns.map(col => (
                  <td key={col.key} className="px-2 py-2 text-[var(--color-foreground)]">
                    {col.render ? col.render(row[col.key], row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-[11px] text-[var(--color-muted-foreground)]">
          <span>{sorted.length} total</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-2 py-1 border border-[var(--color-border)] disabled:opacity-30 hover:bg-[var(--color-muted)]">Prev</button>
            <span className="px-2 py-1 mono">{page + 1}/{totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1} className="px-2 py-1 border border-[var(--color-border)] disabled:opacity-30 hover:bg-[var(--color-muted)]">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
