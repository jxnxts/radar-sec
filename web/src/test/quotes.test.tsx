import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { SignalCard } from '../components/SignalCard'
import { Indices } from '../components/TopBar'
import { useLang } from '../i18n'
import { initialState, usePanel } from '../store'
import type { Quote } from '../types'
import { signal } from './fixtures'

const plain = (text: string | null | undefined) => (text ?? '').replace(/[  ]/g, ' ')

function quote(symbol: string, extra: Partial<Quote> = {}): Quote {
  return {
    symbol,
    name: '',
    price: 715.87,
    prev_close: 730.2,
    change: -14.33,
    change_pct: -0.0196,
    as_of: '2026-11-19T21:00:00+00:00',
    spark: [],
    ...extra,
  }
}

beforeEach(() => {
  usePanel.setState({ ...initialState })
  act(() => useLang.getState().setLang('en'))
})

describe('quote source label', () => {
  it('says real time and names Tiingo IEX when the server uses it', () => {
    usePanel.setState({
      quotes: { SPY: quote('SPY', { source: 'Tiingo IEX', delay_minutes: 0 }) },
      prices: {
        state: 'ok',
        source: 'Tiingo IEX',
        delay_minutes: 0,
        provider: {
          primary: 'Tiingo IEX',
          primary_state: 'ok',
          primary_error: null,
          fallback: 'Yahoo Finance',
          fallback_symbols: ['^VIX'],
        },
      },
    })
    render(<Indices />)
    expect(screen.getByRole('group', { name: 'Indices, real-time quotes' })).toBeTruthy()
    const note = screen.getByText('Real-time').parentElement
    expect(plain(note?.textContent)).toBe('Real-timeTiingo IEX')
    expect(note?.getAttribute('title')).toBe('^VIX from Yahoo Finance')
  })

  it('keeps the Yahoo delay when that is the source, in both languages', () => {
    usePanel.setState({ prices: { state: 'ok', source: 'Yahoo Finance', delay_minutes: 15 } })
    const { unmount } = render(<Indices />)
    expect(screen.getByText('Delayed ~15 min')).toBeTruthy()
    expect(screen.getByText('Delayed ~15 min').parentElement?.getAttribute('title')).toBeNull()
    unmount()
    act(() => useLang.getState().setLang('pt-BR'))
    usePanel.setState({ prices: { state: 'ok', source: 'Tiingo IEX', delay_minutes: 0 } })
    render(<Indices />)
    expect(screen.getByText('Tempo real')).toBeTruthy()
  })

  it('a card labels its quote by that quote own delay', () => {
    const card = (q: Quote) =>
      render(
        <ul>
          <SignalCard signal={signal('a')} quote={q} selected={false} fresh={false} now={0} onSelect={() => {}} />
        </ul>,
      )
    const live = card(quote('ACME', { delay_minutes: 0 }))
    expect(screen.getByText('Today · real-time')).toBeTruthy()
    live.unmount()
    card(quote('ACME')) // an older server sends no delay: Yahoo's 15 minutes
    expect(screen.getByText('Today · delayed')).toBeTruthy()
  })
})
