// Dashboard state. `applySnapshot` and `applyEvent` are pure: they take the state and
// a server message and return what changed, which keeps them easy to test.

import { create } from 'zustand'
import type { ConnectionInfo } from './lib/socket'
import type {
  Filing,
  MarketEvent,
  Mode,
  PricesStatus,
  Quote,
  Rankings,
  ServerMessage,
  Signal,
  SignalType,
  Source,
  Status,
} from './types'

export const MAX_SIGNALS = 80
export const MAX_FILINGS = 80
export const MAX_EVENTS = 80
/** How long a newly arrived signal stays highlighted. */
export const FRESH_MS = 45_000
/** After an operator click, the panel waits this long before following new signals again. */
export const PIN_MS = 120_000

export interface PanelState {
  connection: ConnectionInfo
  everConnected: boolean
  boot: string | null
  seq: number
  mode: Mode | null
  status: Status | null
  prices: PricesStatus | null
  quotes: Record<string, Quote>
  signals: Signal[]
  filings: Filing[]
  /** Events of the extra sources (Form 144, 8-K, 13F, short data), newest first. */
  events: MarketEvent[]
  ranking: Rankings
  /** When each signal arrived in this session (ms), for the "new" highlight. */
  arrivals: Record<string, number>
  selectedId: string | null
  pinnedUntil: number
  filter: SignalType | 'all'
  /** Source chips of the signal feed. */
  source: Source | 'all'
  window: '7' | '30'
}

export const initialState: PanelState = {
  connection: { state: 'connecting', attempt: 0, retryAt: null },
  everConnected: false,
  boot: null,
  seq: 0,
  mode: null,
  status: null,
  prices: null,
  quotes: {},
  signals: [],
  filings: [],
  events: [],
  ranking: {},
  arrivals: {},
  selectedId: null,
  pinnedUntil: 0,
  filter: 'all',
  source: 'all',
  window: '7',
}

/** Source of a signal; older servers send none, and those are all insider signals. */
export function sourceOf(signal: Signal): Source {
  return signal.source ?? 'insiders'
}

/** Signals that pass the feed filters (source chips and signal type). */
export function visibleSignals(state: Pick<PanelState, 'signals' | 'filter' | 'source'>): Signal[] {
  return state.signals.filter(
    (s) => (state.source === 'all' || sourceOf(s) === state.source) && (state.filter === 'all' || s.type === state.filter),
  )
}

function mergeEvents(current: MarketEvent[], incoming: MarketEvent[]): MarketEvent[] {
  const seen = new Set<string>()
  const merged: MarketEvent[] = []
  for (const event of [...incoming, ...current]) {
    if (seen.has(event.id)) continue
    seen.add(event.id)
    merged.push(event)
  }
  return merged.slice(0, MAX_EVENTS)
}

function mergeFilings(current: Filing[], incoming: Filing[]): Filing[] {
  const seen = new Set<string>()
  const merged: Filing[] = []
  for (const filing of [...incoming, ...current]) {
    if (seen.has(filing.accession)) continue
    seen.add(filing.accession)
    merged.push(filing)
  }
  return merged.slice(0, MAX_FILINGS)
}

function keepSelection(state: PanelState, signals: Signal[]): string | null {
  if (state.selectedId && signals.some((s) => s.id === state.selectedId)) return state.selectedId
  return signals[0]?.id ?? null
}

export function applySnapshot(
  state: PanelState,
  message: Extract<ServerMessage, { type: 'snapshot' }>,
  now: number,
): Partial<PanelState> {
  const { data } = message
  const signals = data.signals.slice(0, MAX_SIGNALS)
  const arrivals: Record<string, number> = {}
  // Reconnection to the same server: whatever was not on screen arrived while we were away
  // and deserves the same highlight as a signal received live.
  if (state.everConnected && state.boot === message.boot && state.mode === data.mode) {
    const known = new Set(state.signals.map((s) => s.id))
    for (const signal of signals) {
      const arrived = state.arrivals[signal.id]
      if (arrived) arrivals[signal.id] = arrived
      else if (!known.has(signal.id)) arrivals[signal.id] = now
    }
  }
  return {
    everConnected: true,
    boot: message.boot,
    seq: message.seq,
    mode: data.mode,
    status: data.status,
    prices: data.status.prices ?? null,
    quotes: data.quotes,
    signals,
    filings: mergeFilings([], data.filings),
    events: mergeEvents([], data.market_events ?? []),
    ranking: data.ranking,
    arrivals,
    selectedId: keepSelection(state, signals),
  }
}

export function applyEvent(
  state: PanelState,
  message: Exclude<ServerMessage, { type: 'snapshot' }>,
  now: number,
): Partial<PanelState> {
  // The snapshot may already contain events published while it was being built.
  if (message.seq <= state.seq && message.type !== 'feed.reset') return {}
  const seq = Math.max(state.seq, message.seq)

  switch (message.type) {
    case 'signal.new': {
      const signal = message.data
      if (state.signals.some((s) => s.id === signal.id)) return { seq }
      const signals = [signal, ...state.signals].slice(0, MAX_SIGNALS)
      const follow = now >= state.pinnedUntil || state.selectedId === null
      return {
        seq,
        signals,
        arrivals: { ...state.arrivals, [signal.id]: now },
        selectedId: follow ? signal.id : state.selectedId,
      }
    }
    case 'filing.new':
      return { seq, filings: mergeFilings(state.filings, [message.data]) }
    case 'market_event.new':
      return { seq, events: mergeEvents(state.events, [message.data]) }
    case 'price.tick': {
      const { quotes, ...prices } = message.data
      return { seq, quotes, prices }
    }
    case 'system.status': {
      const status = { ...(state.status ?? {}), ...message.data } as Status
      return { seq, status, prices: message.data.prices ?? state.prices }
    }
    case 'ranking.update':
      return { seq, ranking: message.data }
    case 'feed.reset': {
      const signals = message.data.signals.slice(0, MAX_SIGNALS)
      return {
        seq,
        signals,
        filings: mergeFilings([], message.data.filings),
        ranking: message.data.ranking,
        arrivals: {},
        selectedId: signals[0]?.id ?? null,
        pinnedUntil: 0,
      }
    }
    default:
      return { seq }
  }
}

interface Actions {
  receive: (message: ServerMessage) => void
  setConnection: (info: ConnectionInfo) => void
  select: (id: string) => void
  follow: () => void
  setFilter: (filter: SignalType | 'all') => void
  setSource: (source: Source | 'all') => void
  setWindow: (window: '7' | '30') => void
}

export const usePanel = create<PanelState & Actions>((set) => ({
  ...initialState,
  receive: (message) =>
    set((state) =>
      message.type === 'snapshot'
        ? applySnapshot(state, message, Date.now())
        : applyEvent(state, message, Date.now()),
    ),
  setConnection: (connection) => set({ connection }),
  select: (id) => set({ selectedId: id, pinnedUntil: Date.now() + PIN_MS }),
  follow: () => set((state) => ({ pinnedUntil: 0, selectedId: state.signals[0]?.id ?? null })),
  setFilter: (filter) => set({ filter }),
  setSource: (source) => set({ source }),
  setWindow: (window) => set({ window }),
}))

export function isFresh(arrivals: Record<string, number>, id: string, now: number): boolean {
  const arrived = arrivals[id]
  return arrived !== undefined && now - arrived < FRESH_MS
}
