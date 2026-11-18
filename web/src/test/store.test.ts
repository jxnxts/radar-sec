import { describe, expect, it } from 'vitest'
import { FRESH_MS, MAX_SIGNALS, PIN_MS, applyEvent, applySnapshot, initialState, isFresh } from '../store'
import type { PanelState } from '../store'
import type { Filing, ServerMessage, Signal, Snapshot } from '../types'
import { filing, signal, snapshot } from './fixtures'

type Snap = Extract<ServerMessage, { type: 'snapshot' }>

function snap(data: Partial<Snapshot>, seq = 10, boot = 'abc'): Snap {
  return { type: 'snapshot', seq, boot, ts: '', data: snapshot(data) }
}

function reduce(state: PanelState, message: ServerMessage, now = 1000): PanelState {
  const patch = message.type === 'snapshot' ? applySnapshot(state, message, now) : applyEvent(state, message, now)
  return { ...state, ...patch }
}

const NEW = (s: Signal, seq: number): ServerMessage => ({ type: 'signal.new', seq, ts: '', data: s })
const FILING = (f: Filing, seq: number): ServerMessage => ({ type: 'filing.new', seq, ts: '', data: f })

describe('snapshot', () => {
  it('fills the panel and selects the newest signal', () => {
    const state = reduce(initialState, snap({ signals: [signal('a'), signal('b')], filings: [filing('f1')] }))
    expect(state.mode).toBe('replay')
    expect(state.signals.map((s) => s.id)).toEqual(['a', 'b'])
    expect(state.selectedId).toBe('a')
    expect(state.seq).toBe(10)
    expect(state.everConnected).toBe(true)
    // First load: nothing is "new", or the whole screen would flash on open.
    expect(state.arrivals).toEqual({})
  })

  it("keeps the operator's selection while the signal still exists", () => {
    let state = reduce(initialState, snap({ signals: [signal('a'), signal('b')] }))
    state = { ...state, selectedId: 'b' }
    state = reduce(state, snap({ signals: [signal('c'), signal('a'), signal('b')] }, 20))
    expect(state.selectedId).toBe('b')
  })

  it('on reconnection, highlights what arrived while the connection was down', () => {
    let state = reduce(initialState, snap({ signals: [signal('a')] }))
    state = reduce(state, snap({ signals: [signal('c'), signal('b'), signal('a')] }, 30), 5000)
    expect(state.arrivals).toEqual({ c: 5000, b: 5000 })
    expect(isFresh(state.arrivals, 'c', 5000 + FRESH_MS - 1)).toBe(true)
    expect(isFresh(state.arrivals, 'c', 5000 + FRESH_MS + 1)).toBe(false)
    expect(isFresh(state.arrivals, 'a', 5000)).toBe(false)
  })

  it('highlights nothing when the server restarted (different boot)', () => {
    let state = reduce(initialState, snap({ signals: [signal('a')] }))
    state = reduce(state, snap({ signals: [signal('z'), signal('a')] }, 3, 'other'), 5000)
    expect(state.arrivals).toEqual({})
    expect(state.seq).toBe(3)
  })

  it('does not repeat filings on the tape', () => {
    const state = reduce(initialState, snap({ filings: [filing('f1'), filing('f1'), filing('f2')] }))
    expect(state.filings.map((f) => f.accession)).toEqual(['f1', 'f2'])
  })
})

describe('events', () => {
  const base = reduce(initialState, snap({ signals: [signal('a')] }))

  it('a new signal goes on top, is highlighted and takes focus', () => {
    const state = reduce(base, NEW(signal('b'), 11), 2000)
    expect(state.signals.map((s) => s.id)).toEqual(['b', 'a'])
    expect(state.arrivals.b).toBe(2000)
    expect(state.selectedId).toBe('b')
    expect(state.seq).toBe(11)
  })

  it('does not steal focus while the operator reads another signal', () => {
    const pinned = { ...base, selectedId: 'a', pinnedUntil: 2000 + PIN_MS }
    expect(reduce(pinned, NEW(signal('b'), 11), 2500).selectedId).toBe('a')
    // Once the pin expires, the panel follows new signals again.
    expect(reduce(pinned, NEW(signal('b'), 11), 2000 + PIN_MS + 1).selectedId).toBe('b')
  })

  it('ignores events the snapshot already had and repeated signals', () => {
    expect(reduce(base, NEW(signal('x'), 10)).signals).toHaveLength(1) // stale seq
    const twice = reduce(reduce(base, NEW(signal('b'), 11)), NEW(signal('b'), 12))
    expect(twice.signals.map((s) => s.id)).toEqual(['b', 'a'])
    expect(twice.seq).toBe(12)
  })

  it('caps the feed size', () => {
    let state = base
    for (let i = 0; i < MAX_SIGNALS + 20; i += 1) state = reduce(state, NEW(signal(`n${i}`), 11 + i))
    expect(state.signals).toHaveLength(MAX_SIGNALS)
    expect(state.signals[0]?.id).toBe(`n${MAX_SIGNALS + 19}`)
  })

  it('a new filing goes to the start of the tape, without duplicates', () => {
    let state = reduce(base, FILING(filing('f1'), 11))
    state = reduce(state, FILING(filing('f2'), 12))
    state = reduce(state, FILING(filing('f1'), 13))
    expect(state.filings.map((f) => f.accession)).toEqual(['f1', 'f2'])
  })

  it('quotes and system status are merged', () => {
    let state = reduce(base, {
      type: 'price.tick',
      seq: 11,
      ts: '',
      data: { state: 'ok', delay_minutes: 15, quotes: { SPY: { symbol: 'SPY', name: 'S&P 500', price: 1, prev_close: 1, change: 0, change_pct: 0, as_of: '', spark: [] } } },
    })
    expect(state.quotes.SPY?.price).toBe(1)
    expect(state.prices?.delay_minutes).toBe(15)

    state = reduce(state, { type: 'system.status', seq: 12, ts: '', data: { ws: { clients: 3 } } })
    expect(state.status?.ws?.clients).toBe(3)
    expect(state.status?.mode).toBe('replay') // whatever the event did not carry stays
  })

  it('feed.reset swaps the content even with a lower seq and releases the pin', () => {
    const pinned = { ...base, pinnedUntil: 99_999_999, arrivals: { a: 1 } }
    const state = reduce(pinned, {
      type: 'feed.reset',
      seq: 2,
      ts: '',
      data: { signals: [signal('k')], filings: [], ranking: {} },
    })
    expect(state.signals.map((s) => s.id)).toEqual(['k'])
    expect(state.selectedId).toBe('k')
    expect(state.pinnedUntil).toBe(0)
    expect(state.arrivals).toEqual({})
  })
})
