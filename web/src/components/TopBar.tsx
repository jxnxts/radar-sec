import { CATALOGS, LANGS, labelOf, useI18n, useLang } from '../i18n'
import { useNow } from '../lib/hooks'
import { clock, dayLabel, describeMarket, marketStatus } from '../lib/market'
import { usePanel } from '../store'
import type { Quote } from '../types'
import { Delta } from './Delta'
import { ModeBadge } from './ModeBadge'
import { RadarMark } from './glyphs'
import { Sparkline } from './Sparkline'

const INDEX_ORDER = ['SPY', 'QQQ', 'IWM', '^VIX']
const INDEX_NAMES: Record<string, string> = {
  SPY: 'S&P 500',
  QQQ: 'Nasdaq 100',
  IWM: 'Russell 2000',
  '^VIX': 'VIX',
}

/** Each character in a fixed-width cell, so the clock doesn't jitter every second. */
function Digits({ text }: { text: string }) {
  return (
    <>
      {[...text].map((char, index) => (
        <span key={index} className={char === ':' ? 'digit digit--sep' : 'digit'} aria-hidden="true">
          {char}
        </span>
      ))}
      <span className="sr-only">{text}</span>
    </>
  )
}

function Clock({ city, zone, date }: { city: string; zone: string; date: Date }) {
  const { lang } = useI18n()
  return (
    <div className="clock">
      <span className="clock__city">{city}</span>
      <time className="clock__time">
        <Digits text={clock(date, zone, lang)} />
      </time>
      <span className="clock__day">{dayLabel(date, zone, lang)}</span>
    </div>
  )
}

function Clocks({ now }: { now: number }) {
  const { t } = useI18n()
  const date = new Date(now)
  return (
    <div className="clocks" role="group" aria-label={t.topbar.clocks}>
      <Clock city={t.topbar.newYork} zone="America/New_York" date={date} />
      <Clock city={t.topbar.brasilia} zone="America/Sao_Paulo" date={date} />
    </div>
  )
}

function Market({ now }: { now: number }) {
  const { t, f } = useI18n()
  const status = marketStatus(new Date(now))
  const { label, detail } = describeMarket(status, t, f)
  return (
    <div className={`market market--${status.state}`} role="status" aria-label={t.market.group}>
      <span className="market__shape" aria-hidden="true" />
      <span className="market__label">{label}</span>
      <span className="market__detail">{detail}</span>
    </div>
  )
}

function IndexTile({ symbol, quote }: { symbol: string; quote: Quote | undefined }) {
  const { t, f } = useI18n()
  const label = symbol.replace('^', '')
  return (
    <div className="index" title={INDEX_NAMES[symbol]}>
      <div className="index__head">
        <span className="index__symbol">{label}</span>
        {quote ? <Delta value={quote.change_pct} digits={2} /> : null}
      </div>
      {quote ? (
        <div className="index__row">
          {/* The key changes with the price and restarts the update flash. */}
          <span className="index__price tick" key={quote.price}>
            {f.price(quote.price)}
          </span>
          <Sparkline values={quote.spark} baseline={quote.prev_close} width={64} height={20} />
        </div>
      ) : (
        <div className="index__row index__row--empty">{t.indices.noQuote}</div>
      )}
      <span className="sr-only">{INDEX_NAMES[symbol]}</span>
    </div>
  )
}

function Indices() {
  const { t } = useI18n()
  const quotes = usePanel((s) => s.quotes)
  const prices = usePanel((s) => s.prices)
  const delay = prices?.delay_minutes ?? 15
  return (
    <div className="indices" role="group" aria-label={t.indices.group(delay)}>
      <div className="indices__tiles">
        {INDEX_ORDER.map((symbol) => (
          <IndexTile key={symbol} symbol={symbol} quote={quotes[symbol]} />
        ))}
      </div>
      <p className="indices__note">
        <span className="tag tag--delay">{t.common.delayed(delay)}</span>
        {prices?.source ?? 'Yahoo Finance'}
      </p>
    </div>
  )
}

type LampState = 'ok' | 'busy' | 'warn' | 'err' | 'off'

function Lamp({ name, state, text }: { name: string; state: LampState; text: string }) {
  return (
    <div className={`lamp lamp--${state}`}>
      <span className="lamp__shape" aria-hidden="true" />
      <span className="lamp__name">{name}</span>
      <span className="lamp__text">{text}</span>
    </div>
  )
}

function System({ now }: { now: number }) {
  const { t, f } = useI18n()
  const status = usePanel((s) => s.status)
  const connection = usePanel((s) => s.connection)
  const prices = usePanel((s) => s.prices)
  const tx = t.system

  let sec: [LampState, string] = ['off', tx.waiting]
  if (status?.mode === 'replay' && status.replay) {
    sec = ['off', tx.paused]
  } else if (status?.sec) {
    const s = status.sec
    const pending = status.queue?.pending ?? 0
    if (s.state === 'collecting' || s.state === 'starting') {
      sec = ['busy', pending > 0 ? tx.queue(pending) : tx.reading(labelOf(tx.stages, s.stage))]
    } else if (s.state === 'error') {
      sec = ['err', s.last_error ? tx.cycleFailed : tx.error]
    } else {
      const errors = s.last?.errors ?? 0
      sec = [errors > 0 ? 'warn' : 'ok', tx.readAgo(f.ago(s.last_cycle_at, now))]
    }
  }

  let ai: [LampState, string] = ['off', tx.waiting]
  if (status?.mode === 'replay') ai = ['off', tx.unused]
  else if (status?.ai) {
    const a = status.ai
    if (a.state === 'off') ai = ['off', tx.aiOff]
    else if (a.state === 'capped') ai = ['warn', tx.aiCapped(a.used_last_hour, a.cap_per_hour)]
    else ai = ['ok', tx.aiRate(a.used_last_hour, a.cap_per_hour)]
  }

  let ws: [LampState, string]
  if (connection.state === 'open') ws = ['ok', tx.connected]
  else if (connection.state === 'connecting') ws = ['busy', tx.connecting]
  else ws = ['err', tx.reconnects(f.until(new Date(connection.retryAt ?? now).toISOString(), now))]

  let px: [LampState, string] = ['off', tx.waiting]
  if (prices) {
    if (prices.state === 'ok') px = ['ok', f.ago(prices.last_tick_at, now)]
    else if (prices.state === 'error') px = ['err', tx.noSource]
    else if (prices.state === 'off') px = ['off', tx.pricesOff]
    else px = ['busy', tx.fetching]
  }

  return (
    <div className="system" role="group" aria-label={tx.group}>
      <Lamp name={tx.lamps.sec} state={sec[0]} text={sec[1]} />
      <Lamp name={tx.lamps.ai} state={ai[0]} text={ai[1]} />
      <Lamp name={tx.lamps.ws} state={ws[0]} text={ws[1]} />
      <Lamp name={tx.lamps.prices} state={px[0]} text={px[1]} />
    </div>
  )
}

/** EN / PT switch. Each option names its language in that language. */
export function LanguageSwitch() {
  const { t, lang } = useI18n()
  const setLang = useLang((s) => s.setLang)
  return (
    <div className="lang" role="group" aria-label={t.language.group}>
      <div className="segmented">
        {LANGS.map((option) => (
          <button
            key={option}
            type="button"
            className="chip lang__btn"
            lang={option}
            aria-label={CATALOGS[option].meta.nativeName}
            title={CATALOGS[option].meta.nativeName}
            aria-pressed={lang === option}
            onClick={() => setLang(option)}
          >
            {CATALOGS[option].meta.short}
          </button>
        ))}
      </div>
    </div>
  )
}

export function TopBar() {
  const { t, f } = useI18n()
  const now = useNow(1000)
  const mode = usePanel((s) => s.mode)
  const replay = usePanel((s) => s.status?.replay ?? null)
  return (
    <header className={`topbar topbar--${mode ?? 'idle'}`}>
      <div className="brand">
        <RadarMark className="brand__mark" />
        <div className="brand__text">
          <span className="brand__name">Radar SEC</span>
          <span className="brand__sub">{t.topbar.brandSub}</span>
        </div>
      </div>
      <ModeBadge mode={mode} replay={replay} />
      <Clocks now={now} />
      <Market now={now} />
      <Indices />
      <System now={now} />
      <LanguageSwitch />
      {mode === 'replay' && replay ? (
        <span className="sr-only">{t.topbar.replaySr(f.dateShort(replay.date, true))}</span>
      ) : null}
    </header>
  )
}
