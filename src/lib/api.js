/**
 * API client for FastAPI backend + Supabase realtime.
 * All dashboard data flows through here.
 */

const API_BASE = import.meta.env.VITE_API_URL || ''

async function fetchAPI(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`)
    if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
    return await res.json()
  } catch (err) {
    console.warn(`[api] ${path} failed:`, err.message)
    return null
  }
}

// ── Endpoint functions ──────────────────────────────────────────────────────

export const api = {
  getOverview: (mode = 'paper') => fetchAPI(`/api/overview?mode=${mode}`),
  getAnalytics: (mode = 'paper') => fetchAPI(`/api/analytics?mode=${mode}`),
  getNodes: () => fetchAPI('/api/nodes'),
  getStrategies: () => fetchAPI('/api/strategies'),
  getScannerLive: (nodeId = 'singapore-01') => fetchAPI(`/api/scanner/live?node_id=${nodeId}`),
  getScannerOpportunities: (nodeId = 'singapore-01') => fetchAPI(`/api/scanner/opportunities?node_id=${nodeId}`),
  getRiskCurrent: () => fetchAPI('/api/risk/current'),
  getPortfolio: (mode = 'paper') => fetchAPI(`/api/portfolio?mode=${mode}`),
  getPositions: (mode = 'paper') => fetchAPI(`/api/positions?mode=${mode}`),
  getTaxSummary: () => fetchAPI('/api/tax/summary'),
  getVersions: () => fetchAPI('/api/versions'),
  getApiConfig: () => fetchAPI('/api/config/apis'),
  getNotifications: () => fetchAPI('/api/notifications'),

  getStrategyDetail: (strategyId) => fetchAPI(`/api/strategies/${strategyId}/detail`),
  getStrategyTrades: (strategyId, limit = 50) => fetchAPI(`/api/strategies/${strategyId}/trades?limit=${limit}`),
  getTriangleScannerData: (limit = 50) => fetchAPI(`/api/strategies/A_M1_triangular_arb/live-triangles?limit=${limit}`),
  getExecutionReality: (strategyId, limit = 500) => fetchAPI(`/api/strategies/${strategyId}/execution-reality?limit=${limit}`),
  getPromotionGates: (strategyId) => fetchAPI(`/api/strategies/${strategyId}/promotion-gates`),

  resetAndAllocate: (strategyId, mode = 'paper') =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/reset-allocate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message })),

  allocateCapital: (strategyId, amountUsdc) =>
    fetch(`${API_BASE}/api/capital/allocate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy_id: strategyId, amount_usdc: amountUsdc }),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message })),

  saveStrategyVersion: (strategyId, versionTag, notes = '') =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/save-version`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_tag: versionTag, notes }),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message })),

  toggleStrategy: (strategyId) =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/toggle`, { method: 'POST' })
      .then(r => r.json()).catch(() => null),

  updateStrategyConfig: (strategyId, config) =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message })),

  triggerKillSwitch: () =>
    fetch(`${API_BASE}/api/kill-switch/trigger`, { method: 'POST' })
      .then(r => r.json()).catch(() => null),

  releaseKillSwitch: () =>
    fetch(`${API_BASE}/api/kill-switch/release`, { method: 'POST' })
      .then(r => r.json()).catch(() => null),

  // ── Live-test controls (arm/disarm + master toggle) ──────────────────────
  getLiveTestStatus: (strategyId) =>
    fetchAPI(`/api/strategies/${strategyId}/live-test/status`),

  armLiveTest: (strategyId, count, sizeUsdc = null, cooldownS = null) => {
    const body = { count }
    if (sizeUsdc !== null && sizeUsdc !== undefined) body.size_usdc = sizeUsdc
    if (cooldownS !== null && cooldownS !== undefined) body.cooldown_s = cooldownS
    return fetch(`${API_BASE}/api/strategies/${strategyId}/live-test/arm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message }))
  },

  disarmLiveTest: (strategyId) =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/live-test/disarm`, { method: 'POST' })
      .then(async r => {
        const data = await r.json()
        if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
        return data
      }).catch(e => ({ error: true, detail: e.message })),

  toggleTrading: (strategyId, fields) =>
    fetch(`${API_BASE}/api/strategies/${strategyId}/trading/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    }).then(async r => {
      const data = await r.json()
      if (!r.ok) return { error: true, detail: data?.detail || `HTTP ${r.status}` }
      return data
    }).catch(e => ({ error: true, detail: e.message })),
}
