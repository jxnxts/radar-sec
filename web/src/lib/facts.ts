// Labels and formatting of the `facts` the server sends for signals of the extra sources.

import type { Messages } from '../i18n'
import type { Fact } from '../types'
import type { Format } from './format'

/** Changes read better with a sign: "+40%" short interest, "-18%" covering. */
const SIGNED = new Set(['short_change', 'momentum', 'breadth_change'])

export function factLabel(t: Messages, fact: Fact): string {
  return t.sources.facts[fact.key] ?? fact.key
}

function compactShares(t: Messages, f: Format, value: number): string {
  if (Math.abs(value) >= 1e6) return t.sources.shares(t.sources.million(f.decimal(value / 1e6, 1)))
  if (Math.abs(value) >= 1e3) return t.sources.shares(t.sources.thousand(f.int(value / 1e3)))
  return t.sources.shares(f.int(value))
}

export function formatFact(t: Messages, f: Format, fact: Fact): string {
  const { value } = fact
  if (Array.isArray(value)) {
    return value
      .filter((code) => code !== '9.01')
      .map((code) => t.sources.items[code] ?? code)
      .join(' · ')
  }
  if (typeof value === 'string') {
    if (fact.kind === 'date') return f.dateShort(value, true)
    if (fact.kind === 'quote') return `“${value.length > 220 ? `${value.slice(0, 217)}…` : value}”`
    return value
  }
  switch (fact.kind) {
    case 'usd':
      return f.usd(value)
    case 'pct':
      return f.pct(value, 1, SIGNED.has(fact.key))
    case 'points':
      return f.points(value, 2)
    case 'decimal':
      return f.decimal(value, 1)
    case 'shares':
      return compactShares(t, f, value)
    default:
      return f.int(value)
  }
}

/** The facts worth a card: filing excerpts are long and go to the detail panel only. */
export function cardFacts(facts: Fact[] | undefined): Fact[] {
  return (facts ?? []).filter((fact) => fact.kind !== 'quote')
}
