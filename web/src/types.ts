// Shape of the data the server sends (see src/radar/api/views.py).

/**
 * Text the server writes in every supported language: `{ en, "pt-BR" }`.
 * The dashboard picks the current language and falls back to English.
 */
export type Localized<T extends string = string> = { en: T } & { [lang: string]: T | undefined }
/** A localized map or, from older servers, a plain string. */
export type LocalizedText<T extends string = string> = Localized<T> | T

export type InsiderSignalType = 'cluster_buy' | 'big_officer_buy' | 'activist_13d'
/** Signal types of the extra sources (src/radar/sources). */
export type SourceSignalType =
  | 'form144_cluster'
  | 'form144_large'
  | 'fund_consensus_13f'
  | 'notable_fund_new_13f'
  | 'buyback_8k'
  | 'ceo_cfo_exit_8k'
  | 'bankruptcy_8k'
  | 'auditor_change_8k'
  | 'late_filing_nt'
  | 'short_crowded'
  | 'squeeze_setup'
  | 'ftd_persistent'
export type SignalType = InsiderSignalType | SourceSignalType

/** Where a signal or an event comes from. */
export type Source = 'insiders' | 'form144' | 'thirteenf' | 'eightk' | 'short'
export const SOURCES: readonly Source[] = ['insiders', 'form144', 'thirteenf', 'eightk', 'short']
/** Where a market event comes from: the signal sources plus news (events only, no signals yet). */
export type EventSource = Source | 'news'
export const TYPES_BY_SOURCE: Record<Source, readonly SignalType[]> = {
  insiders: ['cluster_buy', 'big_officer_buy', 'activist_13d'],
  form144: ['form144_cluster', 'form144_large'],
  thirteenf: ['fund_consensus_13f', 'notable_fund_new_13f'],
  eightk: ['buyback_8k', 'ceo_cfo_exit_8k', 'bankruptcy_8k', 'auditor_change_8k', 'late_filing_nt'],
  short: ['short_crowded', 'squeeze_setup', 'ftd_persistent'],
}

export type FactKind =
  | 'number'
  | 'decimal'
  | 'usd'
  | 'pct'
  | 'points'
  | 'shares'
  | 'date'
  | 'text'
  | 'items'
  | 'quote'

/** One labeled number of a signal of the extra sources; labeled by `key`, formatted by `kind`. */
export interface Fact {
  key: string
  value: number | string | string[]
  kind: FactKind | (string & {})
}
export type Mode = 'live' | 'replay'

export interface Insider {
  name: string
  role: string
  value: number | null
  percent?: number | null
}

export interface HorizonOutcome {
  exit_date: string | null
  ret: number | null
  spy: number | null
  excess: number | null
}

export type OutcomeStatus =
  | 'ok'
  | 'no_ticker'
  | 'no_prices'
  | 'no_entry_price'
  | 'price_mismatch'
  | 'suspect_jump'
  | 'unmeasured'

/** Outcome measured by the backtest (REPLAY only). */
export interface Outcome {
  /** One of `OutcomeStatus`; unknown codes are shown as sent. */
  status: OutcomeStatus | (string & {})
  entry_date?: string | null
  entry_price?: number | null
  market_cap?: number | null
  horizons?: Record<string, HorizonOutcome>
}

export interface Signal {
  id: string
  mode: Mode
  type: SignalType
  /** English label; the dashboard translates by `type` instead. */
  label: string
  ticker: string
  symbol: string
  company: string
  cik: string
  sector: string
  date: string
  published_at: string
  score: number
  explanation: LocalizedText
  summary: LocalizedText
  summary_source: LocalizedText<'ai' | 'template'>
  value: number | null
  shares: number | null
  avg_price: number | null
  percent: number | null
  stake_increase: number | null
  n_insiders: number
  insiders: Insider[]
  first_buy: string | null
  last_buy: string | null
  event_date: string | null
  has_ceo_cfo: boolean
  activist_tone: boolean
  filing_url: string | null
  accession: string
  n_filings: number
  logo: string | null
  outcome: Outcome | null
  /** Older servers omit it: then the signal is from the insiders source. */
  source?: Source
  /** Card fields of the extra sources (empty for insider signals). */
  facts?: Fact[]
  /** Hypothesis of the rule: beat the index, lag it (a filter), or context only. */
  direction?: 'long' | 'avoid' | 'context'
  /** False for rules shown live but never backtested. */
  tested?: boolean
  /** Latest price of the company (US$), when known. Older servers omit it. */
  price?: number | null
  price_as_of?: string | null
  /** Latest price × shares outstanding (US$), when known. */
  market_value?: number | null
  /** Price and market value at or above the server thresholds; unknown counts as false. */
  liquid?: boolean
  /** Avoid-type signal: shown by default only when `liquid` (see "Show small caps"). */
  liquidity_gated?: boolean
}

/** Something an extra source saw (a Form 144, an 8-K, a 13F, a short-data release, a news item). */
export interface MarketEvent {
  id: string
  source: EventSource
  kind: string
  date: string
  cik: string
  company: string
  ticker: string
  symbol: string
  title: LocalizedText
  data: Record<string, unknown>
  url: string | null
  seen_at: string | null
}

/** Everything the radar knows about one company, across sources (`/api/company/{cik}/context`). */
export interface CompanyContext {
  cik: string
  symbol: string
  ticker: string
  signals: Signal[]
  insiders: Purchase[]
  form144: MarketEvent[]
  eightk: MarketEvent[]
  thirteenf: MarketEvent[]
  /** News items that name the company (absent from servers without the news source). */
  news?: MarketEvent[]
  short: {
    interest: { settlement_date: string; short_shares: number; days_to_cover: number | null; avg_volume: number | null }[]
    volume: { day: string; ratio: number | null }[]
    fails: { settlement_date: string; quantity: number; price: number | null }[]
  }
}

export interface SourceStatus {
  name: string
  state: 'waiting' | 'ok' | 'error' | (string & {})
  interval_s: number
  last_run_at: string | null
  last_ms: number | null
  last_error: string | null
  events: number
  signals: number
  note: string
}

export interface Purchase {
  date: string
  filed_date: string | null
  name: string
  role: string
  shares: number | null
  price: number | null
  value: number
  accession: string
}

export interface SignalDetail extends Signal {
  purchases: Purchase[]
  previous_signals: Signal[]
  chart: { symbol: string; start: string; end: string }
}

export type FilingKind =
  | 'buy'
  | 'sale'
  | 'grant'
  | 'exercise'
  | 'tax'
  | 'gift'
  | 'return_to_issuer'
  | 'conversion'
  | 'new_13d'
  | 'amended_13d'
  | 'other'

export interface Filing {
  accession: string
  form: string
  company: string
  ticker: string
  cik: string
  filed_date: string | null
  accepted_at: string | null
  url: string | null
  kind: FilingKind
  /** English label; the dashboard translates by `kind` instead. */
  kind_label: string
  who: string
  role: string
  value: number | null
  percent: number | null
}

export interface Quote {
  symbol: string
  name: string
  price: number
  prev_close: number | null
  change: number | null
  change_pct: number | null
  as_of: string
  spark: number[]
}

export interface RankedCompany {
  cik: string
  ticker: string
  symbol: string
  name: string
  sector: string
  value: number
  insiders: number
  filings: number
  last_date: string
  age_days: number
  logo: string | null
}

export interface RankedSector {
  sector: string
  value: number
  companies: number
  insiders: number
  share: number
}

export interface Ranking {
  days: number
  as_of: string
  basis: 'open_market_buys' | 'replayed_signals' | (string & {})
  coverage_since: string | null
  total_value: number
  total_companies: number
  companies: RankedCompany[]
  sectors: RankedSector[]
  blips: RankedCompany[]
}

export type Rankings = Partial<Record<'7' | '30', Ranking>>

export interface PricesStatus {
  state: 'starting' | 'ok' | 'error' | 'off' | (string & {})
  source?: string
  delay_minutes?: number
  interval_s?: number
  last_tick_at?: string | null
  error?: string | null
}

export interface ReplayStatus {
  clock: string
  date: string
  speed: number
  speeds: number[]
  paused: boolean
  days_per_minute: number
  position: number
  total: number
  start: string
  end: string
  loops: number
  source: string
  scoreboard: {
    shown: number
    measured: number
    unmeasured: number
    beat_spy_6m: number
    median_excess_6m: number | null
  }
}

export interface Status {
  mode: Mode
  sec: {
    state: 'starting' | 'collecting' | 'ok' | 'error' | (string & {})
    stage: 'idle' | 'feeds' | 'filings' | 'signals' | (string & {})
    interval_s: number
    cycles: number
    last_cycle_at: string | null
    last_cycle_ms: number | null
    next_cycle_at: string | null
    last: Record<string, number> | null
    last_error: string | null
    requests: number
  } | null
  queue: { pending: number } | null
  ai: {
    enabled: boolean
    model: string
    used_last_hour: number
    cap_per_hour: number
    state: 'off' | 'capped' | 'ok' | (string & {})
    /** Language configured for AI summaries. */
    lang?: string
  } | null
  totals: { signals: number; filings: number | null } | null
  replay: ReplayStatus | null
  server_time?: string
  uptime_s?: number
  version?: string
  ws?: { clients: number }
  prices?: PricesStatus
  /** Liquidity thresholds of the avoid signals (LIVE servers that send them). */
  liquidity?: { min_price: number; min_market_value: number }
  sources?: SourceStatus[]
}

export interface Snapshot {
  mode: Mode
  status: Status
  quotes: Record<string, Quote>
  signals: Signal[]
  filings: Filing[]
  ranking: Rankings
  /** Events of the extra sources (absent on older servers and empty in replay). */
  market_events?: MarketEvent[]
}

export type ServerMessage =
  | { type: 'snapshot'; seq: number; boot: string; ts: string; data: Snapshot }
  | { type: 'signal.new'; seq: number; ts: string; data: Signal }
  | { type: 'filing.new'; seq: number; ts: string; data: Filing }
  | { type: 'market_event.new'; seq: number; ts: string; data: MarketEvent }
  | { type: 'price.tick'; seq: number; ts: string; data: PricesStatus & { quotes: Record<string, Quote> } }
  | { type: 'system.status'; seq: number; ts: string; data: Partial<Status> }
  | { type: 'ranking.update'; seq: number; ts: string; data: Rankings }
  | { type: 'feed.reset'; seq: number; ts: string; data: Pick<Snapshot, 'signals' | 'filings' | 'ranking'> }
  | { type: 'signals.update'; seq: number; ts: string; data: Signal[] }

export interface Bar {
  t: string
  o: number
  h: number
  l: number
  c: number
  v: number | null
}

export interface PriceHistory {
  symbol: string
  start: string
  end: string
  source: string
  kind: 'ohlc' | 'close'
  delay_minutes: number
  bars: Bar[]
  error: string | null
}
