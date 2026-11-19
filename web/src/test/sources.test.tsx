import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { tapeEntries, FilingTape } from '../components/FilingTape'
import { SignalCard } from '../components/SignalCard'
import { SignalFeed } from '../components/SignalFeed'
import { CATALOGS, useLang } from '../i18n'
import { formatFact } from '../lib/facts'
import { formatter } from '../lib/format'
import { MAX_EVENTS, applyEvent, applySnapshot, initialState, usePanel, visibleSignals } from '../store'
import type { ServerMessage } from '../types'
import { filing, marketEvent, signal, snapshot, sourceSignal } from './fixtures'

const plain = (text: string | null | undefined) => (text ?? '').replace(/[  ]/g, ' ')

beforeEach(() => {
  usePanel.setState({ ...initialState })
  useLang.getState().setLang('en')
})

describe('store: extra sources', () => {
  it('takes the events from the snapshot and tolerates older servers without them', () => {
    const message = { type: 'snapshot', seq: 3, boot: 'b', ts: '', data: snapshot({ market_events: [marketEvent('e1')] }) } as const
    expect(applySnapshot(initialState, message, 0).events?.map((e) => e.id)).toEqual(['e1'])
    const old = { type: 'snapshot', seq: 3, boot: 'b', ts: '', data: snapshot() } as const
    expect(applySnapshot(initialState, old, 0).events).toEqual([])
  })

  it('prepends new events once and caps the list', () => {
    const state = { ...initialState, seq: 1, events: [marketEvent('e1')] }
    const message: ServerMessage = { type: 'market_event.new', seq: 2, ts: '', data: marketEvent('e2') }
    const next = applyEvent(state, message, 0)
    expect(next.events?.map((e) => e.id)).toEqual(['e2', 'e1'])
    const again = applyEvent({ ...state, ...next }, { ...message, seq: 3 }, 0)
    expect(again.events?.map((e) => e.id)).toEqual(['e2', 'e1'])
    const many = Array.from({ length: MAX_EVENTS + 5 }, (_, i) => marketEvent(`x${i}`))
    const full = applyEvent({ ...state, events: many }, message, 0)
    expect(full.events).toHaveLength(MAX_EVENTS)
  })

  it('filters signals by source and then by type', () => {
    const signals = [signal('a'), sourceSignal('b'), sourceSignal('c', { type: 'ftd_persistent' })]
    expect(visibleSignals({ signals, source: 'all', filter: 'all' }).map((s) => s.id)).toEqual(['a', 'b', 'c'])
    expect(visibleSignals({ signals, source: 'insiders', filter: 'all' }).map((s) => s.id)).toEqual(['a'])
    expect(visibleSignals({ signals, source: 'short', filter: 'ftd_persistent' }).map((s) => s.id)).toEqual(['c'])
  })
})

describe('source signals on screen', () => {
  it('shows the source, the hypothesis and the facts on the card, never by color alone', () => {
    render(
      <ul>
        <SignalCard signal={sourceSignal('s', { tested: false })} selected={false} fresh={false} now={0} onSelect={() => {}} />
      </ul>,
    )
    expect(screen.getByText('Crowded short')).toBeTruthy()
    expect(screen.getByText('Short')).toBeTruthy()
    expect(screen.getByText('Avoid')).toBeTruthy()
    expect(screen.getByText('Not tested')).toBeTruthy()
    expect(screen.getByText('9.2')).toBeTruthy()
    expect(plain(screen.getByText(/Short change/).textContent)).toBe('Short change: +40.0%')
  })

  it('formats facts per kind and language', () => {
    const en = formatter('en')
    const pt = formatter('pt-BR')
    const shares = { key: 'short_shares', value: 5_200_000, kind: 'shares' }
    expect(formatFact(CATALOGS.en, en, shares)).toBe('5.2M sh.')
    expect(plain(formatFact(CATALOGS['pt-BR'], pt, shares))).toBe('5,2 mi ações')
    expect(formatFact(CATALOGS.en, en, { key: 'items', value: ['5.02', '9.01'], kind: 'items' })).toBe('Officer change')
    expect(formatFact(CATALOGS.en, en, { key: 'weight', value: 0.123, kind: 'pct' })).toBe('12.3%')
  })

  it('filters the feed with the source chips, then the type chips', () => {
    usePanel.setState({
      mode: 'live',
      signals: [signal('a', { mode: 'live' }), sourceSignal('b', { symbol: 'SHRT', ticker: 'SHRT' })],
      selectedId: 'a',
    })
    render(<SignalFeed />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Short' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('SHRT')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'FTD' }))
    expect(screen.getByText('No signals here')).toBeTruthy()
  })

  it('puts the events on the tape next to the filings, in the current language', () => {
    usePanel.setState({
      filings: [filing('f1', { accepted_at: '2026-11-18T14:00:00+00:00' })],
      events: [marketEvent('e1')],
    })
    render(<FilingTape />)
    expect(screen.getAllByText('8-K · Earnings release').length).toBeGreaterThan(0)
    act(() => useLang.getState().setLang('pt-BR'))
    expect(screen.getAllByText('8-K · Resultado divulgado').length).toBeGreaterThan(0)
  })

  it('orders tape entries by time, newest first', () => {
    const entries = tapeEntries(
      [filing('f1', { accepted_at: '2026-11-18T14:00:00+00:00' })],
      [marketEvent('e1'), marketEvent('e0', { seen_at: '2026-11-18T13:00:00+00:00' })],
    )
    expect(entries.map((e) => e.key)).toEqual(['e-e1', 'f-f1', 'e-e0'])
  })
})
