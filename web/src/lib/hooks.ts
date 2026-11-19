import { useEffect, useState } from 'react'
import { getJSON } from './api'
import type { CompanyContext, PriceHistory, SignalDetail } from '../types'

/** Clock that re-renders the component every `interval` ms. */
export function useNow(interval = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), interval)
    return () => clearInterval(timer)
  }, [interval])
  return now
}

export interface Loadable<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** Fetches JSON and refetches when `path` changes. `null` fetches nothing. */
export function useFetch<T>(path: string | null): Loadable<T> {
  const [state, setState] = useState<Loadable<T> & { path: string | null }>({
    data: null,
    loading: path !== null,
    error: null,
    path,
  })
  useEffect(() => {
    if (path === null) {
      setState({ data: null, loading: false, error: null, path })
      return
    }
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true, error: null, path }))
    getJSON<T>(path, controller.signal)
      .then((data) => setState({ data, loading: false, error: null, path }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({ data: null, loading: false, error: String(error), path })
      })
    return () => controller.abort()
  }, [path])
  // Until the new response arrives, the old data belongs to another signal: don't show it.
  return state.path === path ? state : { data: null, loading: path !== null, error: null }
}

export function useSignalDetail(id: string | null): Loadable<SignalDetail> {
  return useFetch<SignalDetail>(id ? `/api/signals/${encodeURIComponent(id)}` : null)
}

/**
 * Everything the radar knows about a company across sources (live only). `version`
 * changes when new events of that company arrive, which refetches the context.
 */
export function useCompanyContext(cik: string | null, version = 0): Loadable<CompanyContext> {
  return useFetch<CompanyContext>(
    cik ? `/api/company/${encodeURIComponent(cik)}/context${version ? `?v=${version}` : ''}` : null,
  )
}

export function usePriceHistory(
  chart: { symbol: string; start: string; end: string } | null | undefined,
): Loadable<PriceHistory> {
  const path =
    chart && chart.symbol
      ? `/api/prices/${encodeURIComponent(chart.symbol)}/history?start=${chart.start}&end=${chart.end}`
      : null
  return useFetch<PriceHistory>(path)
}

export function usePrefersReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(
    () => typeof matchMedia === 'function' && matchMedia(query).matches,
  )
  useEffect(() => {
    if (typeof matchMedia !== 'function') return
    const media = matchMedia(query)
    const onChange = () => setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return reduced
}
