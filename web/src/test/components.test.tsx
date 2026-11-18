import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FilingTape } from '../components/FilingTape'
import { ModeBadge } from '../components/ModeBadge'
import { SignalCard } from '../components/SignalCard'
import { SignalFeed } from '../components/SignalFeed'
import { useLang } from '../i18n'
import { initialState, usePanel } from '../store'
import type { ReplayStatus } from '../types'
import { filing, signal } from './fixtures'

const REPLAY: ReplayStatus = {
  clock: '2020-02-18T10:00:00',
  date: '2020-02-18',
  speed: 1,
  speeds: [0.5, 1, 2, 5, 10],
  paused: false,
  days_per_minute: 2,
  position: 100,
  total: 9018,
  start: '2020-01-02',
  end: '2025-12-31',
  loops: 0,
  source: 'backtest-replay.jsonl.gz',
  scoreboard: { shown: 0, measured: 0, unmeasured: 0, beat_spy_6m: 0, median_excess_6m: null },
}

const plain = (text: string | null | undefined) => (text ?? '').replace(/[  ]/g, ' ')

beforeEach(() => usePanel.setState({ ...initialState }))

describe('ModeBadge', () => {
  it('LIVE and REPLAY have different text, not just colors', () => {
    const live = render(<ModeBadge mode="live" replay={null} />)
    expect(screen.getByRole('group', { name: 'Live mode' })).toBeTruthy()
    expect(screen.getByText('Live')).toBeTruthy()
    expect(screen.queryByText('Replay')).toBeNull()
    live.unmount()

    render(<ModeBadge mode="replay" replay={REPLAY} />)
    const group = screen.getByRole('group', { name: 'Replay mode' })
    expect(within(group).getByText('Replay')).toBeTruthy()
    expect(within(group).getByText('Feb 18, 2020')).toBeTruthy()
    expect(within(group).getByText(/Historical data 2020–2025/)).toBeTruthy()
    expect(screen.queryByText('Live')).toBeNull()
  })

  it('replay controls call the server', () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    render(<ModeBadge mode="replay" replay={REPLAY} />)

    fireEvent.click(screen.getByRole('button', { name: 'Pause replay' }))
    fireEvent.click(screen.getByRole('button', { name: '5×' }))

    expect(fetchMock.mock.calls.map((call) => [call[0], JSON.parse(call[1].body)])).toEqual([
      ['/api/replay/control', { paused: true }],
      ['/api/replay/control', { speed: 5 }],
    ])
    expect(screen.getByRole('button', { name: '1×' }).getAttribute('aria-pressed')).toBe('true')
    vi.unstubAllGlobals()
  })

  it('speaks Portuguese when the language is pt-BR', () => {
    useLang.setState({ lang: 'pt-BR' })
    render(<ModeBadge mode="replay" replay={REPLAY} />)
    const group = screen.getByRole('group', { name: 'Modo replay' })
    expect(within(group).getByText('18 fev 2020')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Pausar o replay' })).toBeTruthy()
  })
})

describe('SignalCard', () => {
  it('shows who bought, how much and the signal type in text', () => {
    render(<ul><SignalCard signal={signal('a')} selected={false} fresh={false} now={0} onSelect={() => {}} /></ul>)
    const card = screen.getByRole('button')
    expect(within(card).getByText('ACME')).toBeTruthy()
    expect(within(card).getByText('Cluster buy')).toBeTruthy()
    expect(within(card).getByText('$200K')).toBeTruthy()
    expect(within(card).getByText('Doe Jane')).toBeTruthy() // upper-case name becomes readable
    expect(within(card).getByText('CEO')).toBeTruthy()
    expect(within(card).getByText('Director/Officer')).toBeTruthy()
    expect(within(card).getByText('2 insiders')).toBeTruthy()
    expect(within(card).getByText('Technology')).toBeTruthy()
    expect(card.getAttribute('aria-pressed')).toBe('false')
    expect(within(card).queryByText('New')).toBeNull()
  })

  it('translates server codes and formats numbers in pt-BR', () => {
    useLang.setState({ lang: 'pt-BR' })
    render(<ul><SignalCard signal={signal('a')} selected={false} fresh={false} now={0} onSelect={() => {}} /></ul>)
    const card = screen.getByRole('button')
    expect(within(card).getByText('Compra em grupo')).toBeTruthy()
    expect(plain(card.querySelector('.card__value')?.textContent)).toBe('US$ 200 mil')
    expect(within(card).getByText('diretor/executivo')).toBeTruthy()
    expect(within(card).getByText('Tecnologia')).toBeTruthy()
  })

  it('a new signal and the replay outcome come with a label and an arrow, not only color', () => {
    const outcome = {
      status: 'ok',
      horizons: { '6': { exit_date: '2020-08-18', ret: -0.2, spy: 0.1, excess: -0.3 } },
    }
    render(<ul><SignalCard signal={signal('a', { outcome })} selected fresh now={0} onSelect={() => {}} /></ul>)
    const card = screen.getByRole('button')
    expect(within(card).getByText('New')).toBeTruthy()
    expect(card.getAttribute('aria-pressed')).toBe('true')
    expect(card.textContent).toContain('▼')
    expect(card.textContent).toContain('−30.0% vs SPY')
  })

  it('an unmeasured signal states the reason', () => {
    render(<ul><SignalCard signal={signal('a', { outcome: { status: 'no_prices' } })} selected={false} fresh={false} now={0} onSelect={() => {}} /></ul>)
    expect(screen.getByText(/no prices \(delisted\)/)).toBeTruthy()
  })

  it('a 13D shows the stake instead of a value; composite and free-text roles survive', () => {
    const activist = signal('a', {
      type: 'activist_13d',
      value: null,
      percent: 9.7,
      insiders: [
        { name: 'Fund X', role: '13D filer', value: null, percent: 9.7 },
        { name: 'Fund Y', role: 'Chief Something Officer', value: null },
      ],
    })
    render(<ul><SignalCard signal={activist} selected={false} fresh={false} now={0} onSelect={() => {}} /></ul>)
    expect(screen.getByText('9.7% of the company')).toBeTruthy()
    expect(screen.getByText('New 13D')).toBeTruthy()
    expect(screen.getByText('13D filer')).toBeTruthy()
    expect(screen.getByText('Chief Something Officer')).toBeTruthy()
  })
})

describe('SignalFeed', () => {
  it('lists the signals, filters by type and selects on click', () => {
    usePanel.setState({
      mode: 'replay',
      signals: [signal('a'), signal('b', { type: 'big_officer_buy', symbol: 'BETA', ticker: 'BETA', company: 'Beta Inc' })],
      selectedId: 'a',
    })
    render(<SignalFeed />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(/2 signals/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'CEO/CFO' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('BETA')).toBeTruthy()

    fireEvent.click(screen.getByText('BETA'))
    expect(usePanel.getState().selectedId).toBe('b')
    expect(usePanel.getState().pinnedUntil).toBeGreaterThan(Date.now())

    fireEvent.click(screen.getByRole('button', { name: '13D' }))
    expect(screen.getByText('No signals here')).toBeTruthy()
  })

  it('announces the new signal to screen readers', () => {
    usePanel.setState({ mode: 'live', signals: [signal('a', { mode: 'live' })], arrivals: { a: Date.now() } })
    render(<SignalFeed />)
    expect(screen.getByRole('status').textContent).toBe('New signal: ACME, Cluster buy')
  })

  it('switches language live, without remounting', () => {
    usePanel.setState({ mode: 'replay', signals: [signal('a')], selectedId: 'a' })
    render(<SignalFeed />)
    expect(screen.getByRole('heading', { name: /Signals/ })).toBeTruthy()
    act(() => useLang.getState().setLang('pt-BR'))
    expect(screen.getByRole('heading', { name: /Sinais/ })).toBeTruthy()
    expect(screen.getByText(/1 sinal/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Grupo' })).toBeTruthy()
  })
})

describe('FilingTape', () => {
  it('labels filings by kind code, in the current language', () => {
    usePanel.setState({ filings: [filing('f1', { kind: 'sale', kind_label: 'Sale', value: 1_000_000 })] })
    render(<FilingTape />)
    expect(screen.getAllByText('Sale').length).toBeGreaterThan(0)
    act(() => useLang.getState().setLang('pt-BR'))
    expect(screen.getAllByText('Venda').length).toBeGreaterThan(0)
  })

  it('falls back to the server label for unknown kinds', () => {
    usePanel.setState({ filings: [filing('f1', { kind: 'mystery' as never, kind_label: 'Mystery kind' })] })
    render(<FilingTape />)
    expect(screen.getAllByText('Mystery kind').length).toBeGreaterThan(0)
  })
})
