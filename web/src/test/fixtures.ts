import type { Filing, Signal, Snapshot } from '../types'

export function signal(id: string, patch: Partial<Signal> = {}): Signal {
  return {
    id,
    mode: 'replay',
    type: 'cluster_buy',
    label: 'Insider cluster buy',
    ticker: 'ACME',
    symbol: 'ACME',
    company: 'Acme Corp',
    cik: '100',
    sector: 'Technology',
    date: '2020-02-18',
    published_at: '2020-02-18T10:00:00',
    score: 72,
    explanation: { en: 'Two insiders bought.', 'pt-BR': 'Dois insiders compraram.' },
    summary: { en: 'Who: 2 insiders.\nHow much: $200K.', 'pt-BR': 'Quem: 2 insiders.\nQuanto: US$ 200 mil.' },
    summary_source: { en: 'template', 'pt-BR': 'template' },
    value: 200_000,
    shares: 10_000,
    avg_price: 20,
    percent: null,
    stake_increase: null,
    n_insiders: 2,
    insiders: [
      { name: 'DOE JANE', role: 'CEO', value: 150_000 },
      { name: 'Roe Richard', role: 'Director/Officer', value: 50_000 },
    ],
    first_buy: '2020-02-14',
    last_buy: '2020-02-18',
    event_date: null,
    has_ceo_cfo: true,
    activist_tone: false,
    filing_url: 'https://www.sec.gov/Archives/edgar/data/100/x-index.htm',
    accession: `acc-${id}`,
    n_filings: 2,
    logo: null,
    outcome: null,
    ...patch,
  }
}

export function filing(accession: string, patch: Partial<Filing> = {}): Filing {
  return {
    accession,
    form: '4',
    company: 'Acme Corp',
    ticker: 'ACME',
    cik: '100',
    filed_date: '2020-02-18',
    accepted_at: null,
    url: null,
    kind: 'buy',
    kind_label: 'Open-market buy',
    who: 'DOE JANE',
    role: 'CEO',
    value: 150_000,
    percent: null,
    ...patch,
  }
}

export function snapshot(patch: Partial<Snapshot> = {}): Snapshot {
  return {
    mode: 'replay',
    status: { mode: 'replay', sec: null, queue: null, ai: null, totals: null, replay: null },
    quotes: {},
    signals: [],
    filings: [],
    ranking: {},
    ...patch,
  }
}
