import { describe, expect, it } from 'vitest'
import { buildMarkers, groupPurchases, snapToBar } from '../components/PriceChart'
import { placeBlips } from '../components/RadarScope'
import { logoTone } from '../components/Logo'
import { CATALOGS } from '../i18n'
import { direction, formatter, hueOf, initials, personName } from '../lib/format'
import { describeMarket, marketStatus, nyseHolidays } from '../lib/market'
import type { Purchase, Ranking } from '../types'
import { signal } from './fixtures'

/** Intl puts no-break spaces in pt-BR currency ("US$\u00a03,55\u00a0mi"); compare with plain spaces. */
const plain = (text: string) => text.replace(/[\u00a0\u202f]/g, ' ')

describe('formatting in English (en-US)', () => {
  const f = formatter('en')

  it('compact dollars', () => {
    expect(f.usd(3_547_771)).toBe('$3.55M')
    expect(f.usd(2_200_000)).toBe('$2.2M')
    expect(f.usd(166_950)).toBe('$167K')
    expect(f.usd(1_250_000_000)).toBe('$1.25B')
    expect(f.usd(250_000_000)).toBe('$250M')
    expect(f.usd(995)).toBe('$995')
    expect(f.usd(-2_200_000)).toBe('−$2.2M')
    expect(f.usd(null)).toBe('n/a')
    expect(f.money(20)).toBe('$20.00')
  })

  it('numbers use a decimal point and thousands commas', () => {
    expect(f.price(732.39)).toBe('732.39')
    expect(f.int(1_234_567)).toBe('1,234,567')
    expect(f.decimal(1.8432)).toBe('1.84')
  })

  it('percentages always signed, and zero unsigned', () => {
    expect(f.pct(0.123)).toBe('+12.3%')
    expect(f.pct(-0.065)).toBe('−6.5%')
    expect(f.pct(-0.0001)).toBe('0.0%')
    expect(f.pct(0.436, 1, false)).toBe('43.6%')
    expect(f.pct(undefined)).toBe('n/a')
    expect(f.points(9.7, 2)).toBe('9.70%')
  })

  it('dates without depending on the browser time zone', () => {
    expect(f.date('2020-02-18')).toBe('02/18/2020')
    expect(f.dateShort('2020-02-08')).toBe('Feb 8')
    expect(f.dateShort('2026-11-17T20:15:33', true)).toBe('Nov 17, 2026')
    expect(f.monthShort('2020-10-01')).toBe('Oct')
    expect(f.weekdayShort(1)).toBe('Mon')
    expect(f.date(null)).toBe('n/a')
  })

  it('relative time', () => {
    const now = Date.parse('2026-11-18T12:00:00Z')
    expect(f.ago('2026-11-18T11:59:48Z', now)).toBe('12s ago')
    expect(f.ago('2026-11-18T11:57:00Z', now)).toBe('3 min ago')
    expect(f.ago('2026-11-18T09:00:00Z', now)).toBe('3h ago')
    expect(f.ago('2026-11-14T12:00:00Z', now)).toBe('4d ago')
    expect(f.until('2026-11-18T12:00:42Z', now)).toBe('in 42s')
  })
})

describe('formatting in Brazilian Portuguese (pt-BR)', () => {
  const f = formatter('pt-BR')

  it('compact dollars', () => {
    expect(plain(f.usd(3_547_771))).toBe('US$ 3,55 mi')
    expect(plain(f.usd(2_200_000))).toBe('US$ 2,2 mi')
    expect(plain(f.usd(166_950))).toBe('US$ 167 mil')
    expect(plain(f.usd(1_250_000_000))).toBe('US$ 1,25 bi')
    expect(plain(f.usd(995))).toBe('US$ 995')
    expect(f.usd(null)).toBe('n/d')
    expect(plain(f.money(20))).toBe('US$ 20,00')
  })

  it('numbers use a decimal comma', () => {
    expect(f.price(732.39)).toBe('732,39')
    expect(f.int(1_234_567)).toBe('1.234.567')
    expect(f.pct(0.123)).toBe('+12,3%')
    expect(f.pct(-0.065)).toBe('−6,5%')
    expect(f.points(9.7, 2)).toBe('9,70%')
  })

  it('dates', () => {
    expect(f.date('2020-02-18')).toBe('18/02/2020')
    expect(f.dateShort('2020-02-08')).toBe('8 fev')
    expect(f.dateShort('2026-11-17T20:15:33', true)).toBe('17 nov 2026')
    expect(f.monthShort('2020-10-01')).toBe('out')
    expect(f.weekdayShort(1)).toBe('seg')
  })

  it('relative time', () => {
    const now = Date.parse('2026-11-18T12:00:00Z')
    expect(f.ago('2026-11-18T11:59:48Z', now)).toBe('há 12 s')
    expect(f.ago('2026-11-14T12:00:00Z', now)).toBe('há 4 d')
    expect(f.until('2026-11-18T12:03:00Z', now)).toBe('em 3 min')
  })
})

describe('locale-free helpers', () => {
  it('direction goes with an arrow alongside color', () => {
    expect([direction(0.01), direction(-0.01), direction(0), direction(null)]).toEqual(['up', 'down', 'flat', 'flat'])
  })

  it('upper-case names become readable', () => {
    expect(personName('CARLEONE JOSEPH')).toBe('Carleone Joseph')
    expect(personName("O'ROURKE JAMES")).toBe("O'Rourke James")
    expect(personName('PW PARTNERS ATLAS FUND III LP')).toBe('Pw Partners Atlas Fund III LP')
    expect(personName('Musk Elon')).toBe('Musk Elon')
  })

  it('monogram for companies without a logo', () => {
    expect(initials('BRK-B', 'Berkshire Hathaway')).toBe('BR')
    expect(initials('', 'Muzinich BDC, Inc.')).toBe('MB')
    expect(hueOf('TSLA')).toBe(hueOf('TSLA'))
    expect(hueOf('TSLA')).not.toBe(hueOf('AAPL'))
  })
})

describe('New York trading session', () => {
  // November 2026: New York is at UTC−5.
  const at = (iso: string) => marketStatus(new Date(iso))
  const en = (iso: string) => describeMarket(at(iso), CATALOGS.en, formatter('en'))
  const pt = (iso: string) => describeMarket(at(iso), CATALOGS['pt-BR'], formatter('pt-BR'))

  it('recognizes pre-market, open, after hours and closed', () => {
    expect(at('2026-11-18T13:52:00Z')).toEqual({ state: 'pre', opensIn: 38 })
    expect(at('2026-11-18T15:00:00Z')).toEqual({ state: 'open', closesIn: 360 })
    expect(at('2026-11-18T21:30:00Z').state).toBe('post')
    expect(en('2026-11-18T13:52:00Z')).toEqual({ label: 'Pre-market', detail: 'opens in 38 min' })
    expect(en('2026-11-18T15:00:00Z')).toEqual({ label: 'Market open', detail: 'closes in 6h 00m' })
    expect(en('2026-11-19T03:00:00Z')).toEqual({ label: 'Market closed', detail: 'opens tomorrow at 9:30 (NY)' })
    expect(en('2026-11-19T07:00:00Z').detail).toBe('opens today at 9:30 (NY)')
  })

  it('describes the session in pt-BR', () => {
    expect(pt('2026-11-18T13:52:00Z').detail).toBe('abre em 38 min')
    expect(pt('2026-11-18T15:00:00Z')).toEqual({ label: 'Mercado aberto', detail: 'fecha em 6h00' })
    expect(pt('2026-11-19T03:00:00Z').detail).toBe('abre amanhã às 9h30 (NY)')
  })

  it('weekends and holidays are closed, pointing at the next session', () => {
    expect(en('2026-11-21T15:00:00Z').detail).toBe('opens Mon at 9:30 (NY)')
    expect(pt('2026-11-21T15:00:00Z').detail).toBe('abre seg às 9h30 (NY)')
    // Thanksgiving (Thursday, 2026-11-26).
    expect(at('2026-11-26T15:00:00Z')).toEqual({ state: 'closed', nextOpen: { days: 1, weekday: 5 } })
  })

  it('computes moving and observed holidays', () => {
    const y2026 = nyseHolidays(2026)
    expect(y2026.has('2026-04-03')).toBe(true) // Good Friday
    expect(y2026.has('2026-07-03')).toBe(true) // July 4th falls on a Saturday
    expect(y2026.has('2026-11-26')).toBe(true)
    expect(y2026.has('2026-01-19')).toBe(true) // Martin Luther King
    expect(nyseHolidays(2027).has('2027-03-26')).toBe(true)
    expect(nyseHolidays(2025).has('2025-05-26')).toBe(true) // Memorial Day
  })
})

describe('chart markers', () => {
  const times = ['2020-02-12', '2020-02-13', '2020-02-14', '2020-02-18', '2020-02-19']
  const buy = (date: string, value = 1000): Purchase => ({
    date, filed_date: null, name: 'DOE JANE', role: 'CEO', shares: 10, price: 100, value, accession: 'x',
  })

  it('snaps dates without a session to the next session', () => {
    expect(snapToBar(times, '2020-02-15')).toBe('2020-02-18') // Saturday
    expect(snapToBar(times, '2020-02-13')).toBe('2020-02-13')
    expect(snapToBar(times, '2020-03-01')).toBeNull()
    expect(snapToBar(times, null)).toBeNull()
  })

  it('groups same-day buys into one marker with a count', () => {
    const purchases = [buy('2020-02-13'), buy('2020-02-13'), buy('2020-02-13'), buy('2020-02-14'), buy('2019-01-01')]
    const groups = groupPurchases(times, purchases)
    expect([...groups.keys()]).toEqual(['2020-02-13', '2020-02-14'])
    expect(groups.get('2020-02-13')).toHaveLength(3)

    const markers = buildMarkers(times, signal('a', { date: '2020-02-18' }), purchases)
    expect(markers.map((m) => [m.time, m.shape, m.text])).toEqual([
      ['2020-02-13', 'circle', '3'],
      ['2020-02-14', 'circle', undefined],
      ['2020-02-18', 'arrowDown', undefined],
    ])
  })

  it('marks backtest exits when the signal has an outcome', () => {
    const withOutcome = signal('a', {
      date: '2020-02-12',
      outcome: { status: 'ok', horizons: { '1': { exit_date: '2020-02-19', ret: 0.1, spy: 0, excess: 0.1 } } },
    })
    const markers = buildMarkers(times, withOutcome, [])
    expect(markers.at(-1)).toMatchObject({ time: '2020-02-19', shape: 'square', text: '1 mo' })
    expect(buildMarkers(times, withOutcome, [], (m) => `${m} m`).at(-1)?.text).toBe('1 m')
  })
})

describe('sector radar', () => {
  const sectors = ['Healthcare', 'Technology', 'Financials', 'Unclassified']
  const company = (cik: string, sector: string, value: number, age: number) => ({
    cik, ticker: `T${cik}`, symbol: `T${cik}`, name: `Company ${cik}`, sector, value,
    insiders: 2, filings: 1, last_date: '2020-02-18', age_days: age, logo: null,
  })
  const ranking: Ranking = {
    days: 7, as_of: '2020-02-18', basis: 'open_market_buys', coverage_since: null, total_value: 0, total_companies: 3,
    companies: [],
    sectors: sectors.map((sector) => ({ sector, value: 0, companies: 0, insiders: 0, share: 0 })),
    blips: [company('1', 'Healthcare', 4_000_000, 0), company('2', 'Financials', 1_000_000, 7), company('3', 'Nonexistent', 10, 3)],
  }

  it('puts each company in its sector slice, with recent ones near the edge', () => {
    const [fresh, old, unknown] = placeBlips(ranking)
    const distance = (b: { x: number; y: number }) => Math.hypot(b.x - 260, b.y - 200)
    const angle = (b: { x: number; y: number }) => ((Math.atan2(b.y - 200, b.x - 260) * 180) / Math.PI + 450) % 360

    expect(distance(fresh!)).toBeGreaterThan(distance(old!))
    expect(distance(fresh!)).toBeLessThanOrEqual(158)
    expect(distance(old!)).toBeGreaterThanOrEqual(30)
    expect(angle(fresh!)).toBeGreaterThan(0) // Healthcare: 0° to 90°
    expect(angle(fresh!)).toBeLessThan(90)
    expect(angle(old!)).toBeGreaterThan(180) // Financials: 180° to 270°
    expect(angle(old!)).toBeLessThan(270)
    expect(fresh!.r).toBeGreaterThan(old!.r) // larger value, larger dot
    expect(unknown!.r).toBeGreaterThan(3) // an unknown sector doesn't break the drawing
  })

  it('a company keeps its position between updates', () => {
    expect(placeBlips(ranking)).toEqual(placeBlips(ranking))
  })
})

describe('logo plate', () => {
  const pixels = (count: number, rgba: [number, number, number, number], blank = 0) => {
    const data = new Uint8ClampedArray((count + blank) * 4)
    for (let i = 0; i < count; i += 1) data.set(rgba, i * 4)
    return data
  }

  it('a light logo gets a dark plate; an empty image becomes a monogram', () => {
    expect(logoTone(pixels(40, [255, 255, 255, 255], 60))).toBe('dark')
    expect(logoTone(pixels(40, [20, 20, 20, 255], 60))).toBe('light')
    expect(logoTone(pixels(100, [255, 255, 255, 255]))).toBe('light') // opaque white background
    expect(logoTone(pixels(1, [0, 0, 0, 255], 99))).toBe('empty')
  })
})
