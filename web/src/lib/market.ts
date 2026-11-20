// New York (NYSE/Nasdaq) trading session state, computed in the browser.

import type { Messages } from '../i18n/en'
import { intlLocale, type Lang } from '../i18n/catalog'
import type { Format } from './format'
import type { Quote } from '../types'

export type MarketState = 'open' | 'pre' | 'post' | 'closed'

/** Language-free description of the session; `describeMarket` turns it into text. */
export type MarketStatus =
  | { state: 'open'; closesIn: number }
  | { state: 'pre'; opensIn: number }
  | { state: 'post' }
  /** `nextOpen`: days until the next session (0 = today) and its weekday (0 = Sunday). */
  | { state: 'closed'; nextOpen: { days: number; weekday: number } | null }

interface NyTime {
  year: number
  month: number // 1-12
  day: number
  weekday: number // 0 = Sunday
  minutes: number // since midnight
}

const NY = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  weekday: 'short',
  hour: 'numeric',
  minute: 'numeric',
  hourCycle: 'h23',
})
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function nyTime(now: Date): NyTime {
  const map: Record<string, string> = {}
  for (const part of NY.formatToParts(now)) map[part.type] = part.value
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    weekday: WEEKDAYS.indexOf(map.weekday ?? 'Sun'),
    minutes: Number(map.hour) * 60 + Number(map.minute),
  }
}

function key(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function weekdayOf(year: number, month: number, day: number): number {
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

/** N-th occurrence of a weekday in the month (n = -1 for the last one). */
function nth(year: number, month: number, weekday: number, n: number): number {
  if (n > 0) {
    const first = weekdayOf(year, month, 1)
    return 1 + ((weekday - first + 7) % 7) + (n - 1) * 7
  }
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return last - ((weekdayOf(year, month, last) - weekday + 7) % 7)
}

/** Easter Sunday (Meeus algorithm), to find Good Friday. */
function easter(year: number): [number, number] {
  const a = year % 19
  const b = Math.floor(year / 100)
  const c = year % 100
  const d = Math.floor(b / 4)
  const e = b % 4
  const f = Math.floor((b + 8) / 25)
  const g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30
  const i = Math.floor(c / 4)
  const k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7
  const m = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * m + 114) / 31)
  const day = ((h + l - 7 * m + 114) % 31) + 1
  return [month, day]
}

/** Fixed-date holiday: observed on Friday when it falls on Saturday, on Monday when on Sunday. */
function observed(year: number, month: number, day: number): string {
  const weekday = weekdayOf(year, month, day)
  const date = new Date(Date.UTC(year, month - 1, day + (weekday === 6 ? -1 : weekday === 0 ? 1 : 0)))
  return key(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate())
}

/** Holidays when the New York exchanges are closed. */
export function nyseHolidays(year: number): Set<string> {
  const [easterMonth, easterDay] = easter(year)
  const goodFriday = new Date(Date.UTC(year, easterMonth - 1, easterDay - 2))
  return new Set([
    observed(year, 1, 1),
    key(year, 1, nth(year, 1, 1, 3)), // Martin Luther King
    key(year, 2, nth(year, 2, 1, 3)), // Presidents' Day
    key(year, goodFriday.getUTCMonth() + 1, goodFriday.getUTCDate()),
    key(year, 5, nth(year, 5, 1, -1)), // Memorial Day
    observed(year, 6, 19), // Juneteenth
    observed(year, 7, 4),
    key(year, 9, nth(year, 9, 1, 1)), // Labor Day
    key(year, 11, nth(year, 11, 4, 4)), // Thanksgiving
    observed(year, 12, 25),
  ])
}

function isTradingDay(year: number, month: number, day: number): boolean {
  const weekday = weekdayOf(year, month, day)
  return weekday !== 0 && weekday !== 6 && !nyseHolidays(year).has(key(year, month, day))
}

const PRE = 4 * 60
const OPEN = 9 * 60 + 30
const CLOSE = 16 * 60
const POST = 20 * 60

export function marketStatus(now: Date): MarketStatus {
  const ny = nyTime(now)
  if (isTradingDay(ny.year, ny.month, ny.day)) {
    if (ny.minutes >= OPEN && ny.minutes < CLOSE) return { state: 'open', closesIn: CLOSE - ny.minutes }
    if (ny.minutes >= PRE && ny.minutes < OPEN) return { state: 'pre', opensIn: OPEN - ny.minutes }
    if (ny.minutes >= CLOSE && ny.minutes < POST) return { state: 'post' }
  }
  // Closed: look for the next session.
  const cursor = new Date(Date.UTC(ny.year, ny.month - 1, ny.day))
  const todayStillOpens = isTradingDay(ny.year, ny.month, ny.day) && ny.minutes < PRE
  for (let step = todayStillOpens ? 0 : 1; step < 10; step += 1) {
    const next = new Date(cursor.getTime() + step * 86_400_000)
    const [y, m, d] = [next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate()]
    if (isTradingDay(y, m, d)) return { state: 'closed', nextOpen: { days: step, weekday: next.getUTCDay() } }
  }
  return { state: 'closed', nextOpen: null }
}

/** Label and detail line for the session, in the catalog's language. */
export function describeMarket(status: MarketStatus, t: Messages, f: Format): { label: string; detail: string } {
  const span = (minutes: number) => t.market.span(Math.floor(minutes / 60), minutes % 60)
  const label = t.market.label[status.state]
  switch (status.state) {
    case 'open':
      return { label, detail: t.market.closesIn(span(status.closesIn)) }
    case 'pre':
      return { label, detail: t.market.opensIn(span(status.opensIn)) }
    case 'post':
      return { label, detail: t.market.sessionEnded }
    case 'closed': {
      const next = status.nextOpen
      if (!next) return { label, detail: '' }
      const when =
        next.days === 0 ? t.market.today : next.days === 1 ? t.market.tomorrow : f.weekdayShort(next.weekday)
      return { label, detail: t.market.opensAt(when) }
    }
  }
}

const CLOCK = new Map<string, Intl.DateTimeFormat>()

/** "08:52:10" in the given time zone. */
export function clock(now: Date, timeZone: string, lang: Lang): string {
  const key = `${lang}|${timeZone}`
  let format = CLOCK.get(key)
  if (!format) {
    format = new Intl.DateTimeFormat(intlLocale(lang), {
      timeZone,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    })
    CLOCK.set(key, format)
  }
  return format.format(now)
}

const DAY = new Map<string, Intl.DateTimeFormat>()

/** "Wed, Nov 18" in the given time zone and language. */
export function dayLabel(now: Date, timeZone: string, lang: Lang): string {
  const key = `${lang}|${timeZone}`
  let format = DAY.get(key)
  if (!format) {
    format = new Intl.DateTimeFormat(intlLocale(lang), { timeZone, weekday: 'short', day: 'numeric', month: 'short' })
    DAY.set(key, format)
  }
  return format
    .formatToParts(now)
    .map((part) => (part.type === 'literal' ? part.value.replace(/^\s*de\s*$/, ' ') : part.value.replace(/\.$/, '')))
    .join('')
}

/** Minutes a quote lags the market (0 = real time); servers before Tiingo sent none: Yahoo's 15. */
export function quoteDelay(quote: Pick<Quote, 'delay_minutes'> | undefined, fallback = 15): number {
  return quote?.delay_minutes ?? fallback
}
