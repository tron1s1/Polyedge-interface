import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '../lib/supabaseClient'

/**
 * Hook: fetch data from API on mount + poll every `interval` ms.
 * Returns { data, loading, error, refetch }.
 */
export function usePolling(fetchFn, interval = 5000) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const fetchRef = useRef(fetchFn)
  fetchRef.current = fetchFn

  const refetch = useCallback(async () => {
    try {
      const result = await fetchRef.current()
      if (result !== null) {
        setData(result)
        setError(null)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refetch()
    const id = setInterval(refetch, interval)
    return () => clearInterval(id)
  }, [refetch, interval])

  return { data, loading, error, refetch }
}

/**
 * Hook: subscribe to Supabase realtime changes on a table.
 * Calls `onInsert` / `onUpdate` callbacks when events arrive.
 */
export function useRealtimeTable(table, { onInsert, onUpdate } = {}) {
  useEffect(() => {
    const channel = supabase
      .channel(`live-${table}`)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table }, (payload) => {
        onInsert?.(payload.new)
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table }, (payload) => {
        onUpdate?.(payload.new)
      })
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [table, onInsert, onUpdate])
}
