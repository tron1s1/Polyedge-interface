import { useCallback } from 'react'
import { useMode } from '../context/ModeContext'
import { NODE_MAP } from '../utils/constants'
import { formatUSD, formatRelativeTime } from '../utils/formatters'
import { api } from '../lib/api'
import { usePolling } from '../hooks/useLiveData'
import Badge from '../components/ui/Badge'
import { Server, Cpu, Activity, Wifi, WifiOff, Settings } from 'lucide-react'

function NodeCard({ node }) {
  const isOnline = node.status === 'online'
  const staticInfo = NODE_MAP[node.node_id] || {}

  return (
    <div className={`border border-[var(--color-border)] bg-[var(--color-card)] ${!isOnline ? 'opacity-80' : ''}`}>
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 shrink-0 inline-block" style={{ backgroundColor: isOnline ? '#1D9E75' : '#6B7280', borderRadius: '50%', boxShadow: isOnline ? '0 0 8px #1D9E7580' : 'none' }} />
          <div>
            <div className="text-[14px] font-medium">{node.display_name}</div>
            <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">
              {node.cloud_provider} · {node.location}
            </div>
          </div>
        </div>
        <Badge variant={isOnline ? 'success' : 'retired'}>{isOnline ? 'ONLINE' : 'OFFLINE'}</Badge>
      </div>

      {isOnline && (
        <>
          <div className="px-4 py-3 border-b border-[var(--color-border)] grid grid-cols-4 gap-4">
            <div>
              <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">Exchange</div>
              <div className="text-[14px] font-medium">{node.primary_exchange}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">Last Heartbeat</div>
              <div className="mono text-[14px] font-medium">{formatRelativeTime(node.last_heartbeat)}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">Slot</div>
              <div className="mono text-[14px] font-medium">{node.slot || 'green'}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">Monthly Cost</div>
              <div className="mono text-[14px] font-medium">${node.monthly_cost_usd}/mo</div>
            </div>
          </div>

          <div className="px-4 py-2.5 border-b border-[var(--color-border)]">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-2">
              Strategies ({node.strategies?.length || 0})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(node.strategies || []).map(sid => (
                <span key={sid} className="mono text-[8px] font-medium px-1.5 py-0.5 border border-[var(--color-border)] bg-[var(--color-muted)]">
                  {sid}
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      {!isOnline && (
        <div className="px-4 py-6 text-center">
          <WifiOff size={24} className="mx-auto text-[var(--color-muted-foreground)] opacity-40 mb-2" />
          <span className="text-[12px] text-[var(--color-muted-foreground)]">Node is offline</span>
          <div className="mt-3">
            <button className="flex items-center gap-1.5 px-4 py-2 mx-auto text-[11px] font-medium bg-[var(--color-accent)] text-white hover:opacity-90">
              <Settings size={12} /> Configure & Start
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function NodesPage() {
  const { data } = usePolling(useCallback(() => api.getNodes(), []), 5000)
  const nodes = data?.nodes || []
  const onlineCount = nodes.filter(n => n.status === 'online').length

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-medium">Node Manager</h1>
          <p className="text-[11px] text-[var(--color-muted-foreground)] mt-1">Live data from Supabase nodes table.</p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-[var(--color-muted-foreground)]">
          <Server size={14} /> <span>{onlineCount}/{nodes.length} online</span>
        </div>
      </div>

      <div className="border border-[var(--color-border)] bg-[var(--color-muted)] px-4 py-2.5 text-[11px] text-[var(--color-muted-foreground)] flex items-center gap-3">
        <Activity size={14} className="text-[var(--color-accent)] shrink-0" />
        <span><strong>{onlineCount} of {nodes.length}</strong> nodes operational. Heartbeats update every 30 seconds.</span>
      </div>

      <div className="space-y-4">
        {nodes.map(node => <NodeCard key={node.node_id} node={node} />)}
      </div>
    </div>
  )
}
