import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { SignalCard } from '../components/SignalCard'
import { SignalFeed } from '../components/SignalFeed'
import { useLang } from '../i18n'
import {
  SMALL_CAPS_KEY,
  applyEvent,
  applySnapshot,
  hiddenSmallCaps,
  initialState,
  isSmallCapAvoid,
  usePanel,
  visibleSignals,
} from '../store'
import type { ServerMessage } from '../types'
import { signal, snapshot, sourceSignal } from './fixtures'

const plain = (text: string | null | undefined) => (text ?? '').replace(/[\u00a0\u202f]/g, ' ')

const liquidAvoid = sourceSignal('big', {
  symbol: 'BIG',
  ticker: 'BIG',
  liquidity_gated: true,
  liquid: true,
  price: 80,
  market_value: 4_000_000_000,
})
const smallAvoid = sourceSignal('tiny', {
  symbol: 'TINY',
  ticker: 'TINY',
  company: 'Tiny Corp',
  liquidity_gated: true,
  liquid: false,
  price: 2,
  market_value: 20_000_000,
})
const unknownAvoid = sourceSignal('ghost', { symbol: 'GHST', ticker: 'GHST', liquidity_gated: true })
const insider = signal('ins', { mode: 'live', liquidity_gated: false, liquid: false })

beforeEach(() => {
  usePanel.setState({ ...initialState })
  useLang.getState().setLang('en')
})

describe('store: small-cap avoid signals', () => {
  it('hides avoid signals of small or unknown companies unless asked, never the others', () => {
    expect(isSmallCapAvoid(smallAvoid)).toBe(true)
    expect(isSmallCapAvoid(unknownAvoid)).toBe(true) // unknown liquidity is not liquid
    expect(isSmallCapAvoid(liquidAvoid)).toBe(false)
    expect(isSmallCapAvoid(insider)).toBe(false) // long and insider signals are never gated
    expect(isSmallCapAvoid(sourceSignal('old'))).toBe(false) // older servers send no flag

    const signals = [insider, liquidAvoid, smallAvoid, unknownAvoid]
    const base = { signals, source: 'all' as const, filter: 'all' as const }
    expect(visibleSignals({ ...base, showSmallCaps: false }).map((s) => s.id)).toEqual(['ins', 'big'])
    expect(visibleSignals({ ...base, showSmallCaps: true })).toHaveLength(4)
    expect(hiddenSmallCaps({ ...base, showSmallCaps: false })).toBe(2)
    expect(hiddenSmallCaps({ ...base, source: 'insiders', showSmallCaps: false })).toBe(0)
  })

  it('a hidden signal arriving live never takes the focus', () => {
    const state = { ...initialState, seq: 1, signals: [insider], selectedId: 'ins' }
    const hidden: ServerMessage = { type: 'signal.new', seq: 2, ts: '', data: smallAvoid }
    expect(applyEvent(state, hidden, 0).selectedId).toBe('ins')
    const shown: ServerMessage = { type: 'signal.new', seq: 2, ts: '', data: liquidAvoid }
    expect(applyEvent(state, shown, 0).selectedId).toBe('big')
    expect(applyEvent({ ...state, showSmallCaps: true }, hidden, 0).selectedId).toBe('tiny')
  })

  it('selects the first shown signal of a snapshot', () => {
    const message = { type: 'snapshot', seq: 1, boot: 'b', ts: '', data: snapshot({ signals: [smallAvoid, insider] }) } as const
    expect(applySnapshot(initialState, message, 0).selectedId).toBe('ins')
  })

  it('merges updated price and market value into the signals on screen', () => {
    const state = { ...initialState, seq: 1, signals: [insider, unknownAvoid] }
    const measured = { ...unknownAvoid, liquid: true, price: 30, market_value: 900_000_000 }
    const message: ServerMessage = { type: 'signals.update', seq: 2, ts: '', data: [measured, signal('gone')] }
    const next = applyEvent(state, message, 0)
    expect(next.signals?.map((s) => s.id)).toEqual(['ins', 'ghost'])
    expect(next.signals?.[1]?.liquid).toBe(true)
    expect(applyEvent(state, { ...message, data: [signal('gone')] }, 0)).toEqual({ seq: 2 })
  })

  it('remembers the choice and survives blocked storage', () => {
    usePanel.getState().setShowSmallCaps(true)
    expect(localStorage.getItem(SMALL_CAPS_KEY)).toBe('1')
    usePanel.getState().setShowSmallCaps(false)
    expect(localStorage.getItem(SMALL_CAPS_KEY)).toBe('0')

    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('blocked')
    }
    try {
      expect(() => usePanel.getState().setShowSmallCaps(true)).not.toThrow()
      expect(usePanel.getState().showSmallCaps).toBe(true)
    } finally {
      Storage.prototype.setItem = original
    }
  })

  it('hiding the signal in focus moves the focus to the first one still shown', () => {
    usePanel.setState({ signals: [smallAvoid, insider], selectedId: 'tiny', showSmallCaps: true })
    usePanel.getState().setShowSmallCaps(false)
    expect(usePanel.getState().selectedId).toBe('ins')
  })
})

describe('small caps on screen', () => {
  it('the toggle reveals the hidden avoid signals and says how many are hidden', () => {
    usePanel.setState({ mode: 'live', signals: [insider, liquidAvoid, smallAvoid, unknownAvoid], selectedId: 'ins' })
    render(<SignalFeed />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('2 hidden')).toBeTruthy()
    const toggle = screen.getByRole('button', { name: 'Show small caps' })
    expect(toggle.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(toggle)
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
    expect(screen.queryByText('2 hidden')).toBeNull()
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(localStorage.getItem(SMALL_CAPS_KEY)).toBe('1')

    act(() => useLang.getState().setLang('pt-BR'))
    expect(screen.getByRole('button', { name: 'Mostrar small caps' })).toBeTruthy()
  })

  it('has no toggle when no signal is gated (replay, insider signals only)', () => {
    usePanel.setState({ mode: 'replay', signals: [signal('a')], selectedId: 'a' })
    render(<SignalFeed />)
    expect(screen.queryByRole('button', { name: 'Show small caps' })).toBeNull()
  })

  it('the toggle title states the server thresholds when it sends them', () => {
    usePanel.setState({
      mode: 'live',
      signals: [smallAvoid],
      status: { liquidity: { min_price: 5, min_market_value: 300_000_000 } } as never,
    })
    render(<SignalFeed />)
    const title = plain(screen.getByRole('button', { name: 'Show small caps' }).getAttribute('title'))
    expect(title).toContain('price from $5, market value from $300M')
  })

  it('avoid cards show price and market value, and flag small caps', () => {
    render(
      <ul>
        <SignalCard signal={smallAvoid} selected={false} fresh={false} now={0} onSelect={() => {}} />
        <SignalCard signal={liquidAvoid} selected={false} fresh={false} now={0} onSelect={() => {}} />
        <SignalCard signal={unknownAvoid} selected={false} fresh={false} now={0} onSelect={() => {}} />
        <SignalCard signal={insider} selected={false} fresh={false} now={0} onSelect={() => {}} />
      </ul>,
    )
    expect(screen.getByText('$2.00')).toBeTruthy()
    expect(screen.getByText('$20M')).toBeTruthy()
    expect(screen.getByText('$4B')).toBeTruthy()
    expect(screen.getAllByText('Small cap')).toHaveLength(2) // tiny and unknown, not the liquid one
    expect(screen.getByText('Price or market value unknown')).toBeTruthy()
    expect(screen.getAllByText('Mkt value')).toHaveLength(2) // never on the insider card

    act(() => useLang.getState().setLang('pt-BR'))
    expect(screen.getAllByText('Valor de mercado')).toHaveLength(2)
    expect(plain(screen.getByText(/US\$ 20 mi/).textContent)).toBe('US$ 20 mi')
  })
})
