// Locale-aware numbers and dates. Every formatter takes the language explicitly
// (`formatter(lang)`); components get the current one from `useI18n()`.

import { CATALOGS, intlLocale, type Lang } from '../i18n/catalog'

const MINUS = '−'

function parts(iso: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null
}

/** Calendar date at UTC midnight: SEC dates have no time zone, so we never shift them. */
function utcDate(iso: string | null | undefined): Date | null {
  const p = iso ? parts(iso) : null
  return p ? new Date(Date.UTC(p[0], p[1] - 1, p[2])) : null
}

function bad(value: number | null | undefined): value is null | undefined {
  return value == null || Number.isNaN(value)
}

/** Drops abbreviation dots and the "de" connector that pt-BR puts in short dates. */
function tidy(format: Intl.DateTimeFormat, date: Date): string {
  return format
    .formatToParts(date)
    .map((part) => {
      if (part.type === 'literal') return part.value.replace(/^\s*de\s*$/, ' ')
      if (part.type === 'month' || part.type === 'weekday') return part.value.replace(/\.$/, '')
      return part.value
    })
    .join('')
}

export interface Format {
  lang: Lang
  /** Compact dollars: "$3.55M". */
  usd: (value: number | null | undefined) => string
  /** Full dollars with cents: "$20.00". */
  money: (value: number | null | undefined, digits?: number) => string
  /** Plain price: "732.39". */
  price: (value: number | null | undefined, digits?: number) => string
  int: (value: number | null | undefined) => string
  /** Up to `digits` decimals, trailing zeros dropped: "1.84". */
  decimal: (value: number | null | undefined, digits?: number) => string
  /** Fraction as a percentage: 0.123 → "+12.3%". The sign shows whenever `signed`. */
  pct: (value: number | null | undefined, digits?: number, signed?: boolean) => string
  /** Value already in percentage points: 5.1 → "5.1%". */
  points: (value: number | null | undefined, digits?: number) => string
  /** "02/18/2020" (en-US order). */
  date: (iso: string | null | undefined) => string
  /** "Feb 18" (with the year when `withYear`). */
  dateShort: (iso: string | null | undefined, withYear?: boolean) => string
  /** "Feb". */
  monthShort: (iso: string | null | undefined) => string
  /** "Mon" for a weekday index (0 = Sunday). */
  weekdayShort: (weekday: number) => string
  /** "12s ago". */
  ago: (iso: string | null | undefined, now: number) => string
  /** "in 42s". */
  until: (iso: string | null | undefined, now: number) => string
}

function build(lang: Lang): Format {
  const locale = intlLocale(lang)
  const t = CATALOGS[lang]
  const na = t.common.na

  const fixedCache = new Map<number, Intl.NumberFormat>()
  const fixed = (value: number, digits: number) => {
    let format = fixedCache.get(digits)
    if (!format) {
      format = new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })
      fixedCache.set(digits, format)
    }
    return format.format(Math.abs(value))
  }
  const sign = (value: number) => (value < 0 ? MINUS : '')

  const compact = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumSignificantDigits: 3,
  })
  const whole = new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  const moneyCache = new Map<number, Intl.NumberFormat>()
  const decimalCache = new Map<number, Intl.NumberFormat>()

  const short = new Intl.DateTimeFormat(locale, { timeZone: 'UTC', month: 'short', day: 'numeric' })
  const shortYear = new Intl.DateTimeFormat(locale, {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  const numeric = new Intl.DateTimeFormat(locale, {
    timeZone: 'UTC',
    month: '2-digit',
    day: '2-digit',
    year: 'numeric',
  })
  const month = new Intl.DateTimeFormat(locale, { timeZone: 'UTC', month: 'short' })
  const weekday = new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: 'short' })

  const span = (seconds: number) => {
    if (seconds < 60) return t.time.seconds(seconds)
    if (seconds < 3600) return t.time.minutes(Math.floor(seconds / 60))
    if (seconds < 86_400) return t.time.hours(Math.floor(seconds / 3600))
    return t.time.days(Math.floor(seconds / 86_400))
  }

  return {
    lang,
    usd: (value) => {
      if (bad(value)) return na
      const magnitude = Math.abs(value)
      return sign(value) + (magnitude >= 1000 ? compact : whole).format(magnitude)
    },
    money: (value, digits = 2) => {
      if (bad(value)) return na
      let format = moneyCache.get(digits)
      if (!format) {
        format = new Intl.NumberFormat(locale, {
          style: 'currency',
          currency: 'USD',
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        })
        moneyCache.set(digits, format)
      }
      return sign(value) + format.format(Math.abs(value))
    },
    price: (value, digits = 2) => (bad(value) ? na : sign(value) + fixed(value, digits)),
    int: (value) => (bad(value) ? na : sign(value) + fixed(value, 0)),
    decimal: (value, digits = 2) => {
      if (bad(value)) return na
      let format = decimalCache.get(digits)
      if (!format) {
        format = new Intl.NumberFormat(locale, { maximumFractionDigits: digits })
        decimalCache.set(digits, format)
      }
      return sign(value) + format.format(Math.abs(value))
    },
    pct: (value, digits = 1, signed = true) => {
      if (bad(value)) return na
      const rounded = Number((value * 100).toFixed(digits))
      const mark = rounded < 0 ? MINUS : signed && rounded > 0 ? '+' : ''
      return `${mark}${fixed(rounded, digits)}%`
    },
    points: (value, digits = 1) => (bad(value) ? na : `${fixed(value, digits)}%`),
    date: (iso) => {
      const date = utcDate(iso)
      return date ? numeric.format(date) : na
    },
    dateShort: (iso, withYear = false) => {
      const date = utcDate(iso)
      return date ? tidy(withYear ? shortYear : short, date) : na
    },
    monthShort: (iso) => {
      const date = utcDate(iso)
      return date ? tidy(month, date) : ''
    },
    weekdayShort: (day) => tidy(weekday, new Date(Date.UTC(2023, 0, 1 + day))), // 2023-01-01 was a Sunday
    ago: (iso, now) => {
      const then = iso ? Date.parse(iso) : Number.NaN
      if (Number.isNaN(then)) return na
      return t.time.ago(span(Math.max(0, Math.round((now - then) / 1000))))
    },
    until: (iso, now) => {
      if (!iso) return ''
      const seconds = Math.max(0, Math.round((Date.parse(iso) - now) / 1000))
      return t.time.in(seconds < 60 ? t.time.seconds(seconds) : t.time.minutes(Math.ceil(seconds / 60)))
    },
  }
}

const FORMATS: Partial<Record<Lang, Format>> = {}

/** Formatters for `lang` (built once per language). */
export function formatter(lang: Lang): Format {
  return (FORMATS[lang] ??= build(lang))
}

/** Direction of a number, so meaning never depends on color alone. */
export function direction(value: number | null | undefined): 'up' | 'down' | 'flat' {
  if (value == null || Number.isNaN(value) || Math.abs(value) < 0.00005) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export const ARROWS = { up: '▲', down: '▼', flat: '■' } as const

/** "HH:MM" from an ISO string without converting time zones (the replay clock is New York time). */
export function clockOf(iso: string | null | undefined): string {
  const match = iso ? /T(\d{2}:\d{2})/.exec(iso) : null
  return match?.[1] ?? ''
}

/** Person name in mixed case: "CARLEONE JOSEPH" → "Carleone Joseph". */
export function personName(name: string): string {
  if (name !== name.toUpperCase()) return name
  return name
    .toLowerCase()
    .replace(/(^|[\s\-/.'(])(\p{L})/gu, (_, sep: string, letter: string) => sep + letter.toUpperCase())
    .replace(/\b(Llc|Lp|Inc|Ltd|Ii|Iii|Iv|Jr|Sr|Usa|Ceo|Cfo|Gp)\b/g, (word) =>
      ['Jr', 'Sr'].includes(word) ? word : word.toUpperCase(),
    )
}

/** Stable hue derived from the ticker, for the monogram of companies without a logo. */
export function hueOf(text: string): number {
  let hash = 0
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) % 360
  return hash
}

export function initials(ticker: string, company: string): string {
  const clean = ticker.replace(/[^A-Za-z]/g, '').toUpperCase()
  if (clean) return clean.slice(0, 2)
  const words = company.split(/\s+/).filter(Boolean)
  return ((words[0]?.[0] ?? '?') + (words[1]?.[0] ?? '')).toUpperCase()
}
