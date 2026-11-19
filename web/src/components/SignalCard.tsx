import { labelOf, localized, roleLabel, useI18n } from '../i18n'
import { cardFacts, factLabel, formatFact } from '../lib/facts'
import { ARROWS, direction, personName } from '../lib/format'
import { sourceOf } from '../store'
import type { Outcome, Quote, Signal } from '../types'
import { Delta } from './Delta'
import { SignalGlyph, SourceGlyph } from './glyphs'
import { Logo } from './Logo'
import { ScoreRing } from './ScoreRing'

const UNCLASSIFIED = 'Unclassified'

/** Backtest outcome of the signal: what happened over the next 6 months, against the SPY. */
export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const { t, f } = useI18n()
  const six = outcome.horizons?.['6']
  if (outcome.status !== 'ok' || !six || six.excess == null) {
    const status = outcome.status === 'ok' ? 'unmeasured' : outcome.status
    return (
      <span className="outcome outcome--none" title={t.outcome.notMeasuredTitle}>
        <span className="outcome__label">{t.outcome.after}</span>
        {labelOf(t.outcome.status, status)}
      </span>
    )
  }
  const dir = direction(six.excess)
  return (
    <span
      className={`outcome outcome--${dir}`}
      title={t.outcome.sixMonthsTitle(f.pct(six.ret), f.pct(six.spy), f.pct(six.excess))}
    >
      <span className="outcome__label">{t.outcome.sixMonthsLater}</span>
      <span aria-hidden="true">{ARROWS[dir]}</span>
      {t.outcome.vsSpy(f.pct(six.excess))}
    </span>
  )
}

interface SignalCardProps {
  signal: Signal
  quote?: Quote
  selected: boolean
  fresh: boolean
  now: number
  onSelect: (id: string) => void
}

export function SignalCard({ signal, quote, selected, fresh, now, onSelect }: SignalCardProps) {
  const { t, f, lang } = useI18n()
  const people = signal.insiders.slice(0, 2)
  const more = signal.insiders.length - people.length
  const when =
    signal.mode === 'live' && fresh ? f.ago(signal.published_at, now) : f.dateShort(signal.date)
  const source = sourceOf(signal)
  const facts = cardFacts(signal.facts)
  const headline =
    source !== 'insiders'
      ? facts[0]
        ? formatFact(t, f, facts[0])
        : '—'
      : signal.type === 'activist_13d'
        ? t.card.stakeOfCompany(f.points(signal.percent))
        : f.usd(signal.value)
  const countLine =
    source !== 'insiders'
      ? facts[1]
        ? `${factLabel(t, facts[1])}: ${formatFact(t, f, facts[1])}`
        : facts[0]
          ? factLabel(t, facts[0])
          : ''
      : signal.type === 'cluster_buy'
        ? t.card.insiders(signal.n_insiders)
        : signal.type === 'big_officer_buy'
          ? signal.stake_increase != null
            ? t.card.stake(f.pct(signal.stake_increase))
            : t.card.openMarket
          : signal.activist_tone
            ? t.card.activistTone
            : t.card.declaredStake

  return (
    <li className="card-slot">
      <button
        type="button"
        className={`card card--${signal.type} card--src-${source}${selected ? ' is-selected' : ''}${fresh ? ' is-fresh' : ''}`}
        aria-pressed={selected}
        onClick={() => onSelect(signal.id)}
        data-signal-id={signal.id}
      >
        <span className="card__rail" aria-hidden="true" />
        <span className="card__top">
          <Logo src={signal.logo} ticker={signal.symbol || signal.ticker} company={signal.company} />
          <span className="card__id">
            <span className="card__ticker">{signal.symbol || signal.ticker || '—'}</span>
            <span className="card__company">{signal.company}</span>
          </span>
          <ScoreRing score={signal.score} />
        </span>

        <span className="card__meta">
          <span className="type">
            <SignalGlyph type={signal.type} />
            {t.signalType.short[signal.type]}
          </span>
          {fresh ? <span className="tag tag--new">{t.card.new}</span> : null}
          <span className="card__when">{when}</span>
        </span>

        <span className="card__figure">
          <span className="card__value">{headline}</span>
          <span className="card__count">{countLine}</span>
        </span>

        <span className="card__people">
          {people.map((person) => (
            <span className="person" key={`${person.name}-${person.role}`}>
              <span className="person__name">{personName(person.name)}</span>
              <span className="person__role">{roleLabel(t, person.role)}</span>
              {person.value != null ? <span className="person__value">{f.usd(person.value)}</span> : null}
            </span>
          ))}
          {more > 0 ? <span className="person person--more">{t.common.andMore(more)}</span> : null}
        </span>

        <span className="card__foot">
          <span className="card__tags">
            {source !== 'insiders' ? (
              <span className="tag tag--source" title={t.sources.title[source]}>
                <SourceGlyph source={source} />
                {t.sources.name[source]}
              </span>
            ) : null}
            {signal.direction === 'avoid' || signal.direction === 'long' ? (
              <span className={`tag tag--${signal.direction}`} title={t.sources.directionTitle[signal.direction]}>
                {t.sources.direction[signal.direction]}
              </span>
            ) : null}
            {signal.tested === false ? (
              <span className="tag tag--untested" title={t.sources.untestedTitle}>
                {t.sources.untested}
              </span>
            ) : null}
            {signal.sector && signal.sector !== UNCLASSIFIED ? (
              <span className="tag">{labelOf(t.sectors, signal.sector)}</span>
            ) : null}
            {localized(signal.summary_source, lang) === 'ai' ? (
              <span className="tag tag--ai">{t.card.aiSummary}</span>
            ) : null}
          </span>
          {signal.outcome ? (
            <OutcomeBadge outcome={signal.outcome} />
          ) : quote ? (
            <span className="outcome" title={t.card.todayTitle}>
              <span className="outcome__label">{t.card.todayDelayed}</span>
              <Delta value={quote.change_pct} digits={2} />
            </span>
          ) : null}
        </span>
      </button>
    </li>
  )
}
