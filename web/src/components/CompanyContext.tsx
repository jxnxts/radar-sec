import { useMemo } from 'react'
import { localized, useI18n } from '../i18n'
import { useCompanyContext } from '../lib/hooks'
import { personName } from '../lib/format'
import { sourceOf, usePanel } from '../store'
import type { CompanyContext as Context, MarketEvent, Signal } from '../types'
import { SignalGlyph, SourceGlyph } from './glyphs'

const MAX_ROWS = 4

function EventList({ events }: { events: MarketEvent[] }) {
  const { t, f, lang } = useI18n()
  if (events.length === 0) return <p className="ctx__none">{t.context.none}</p>
  return (
    <ul className="ctx__list">
      {events.slice(0, MAX_ROWS).map((event) => (
        <li key={event.id} className="ctx__row">
          <span className="ctx__date">{f.dateShort(event.date, true)}</span>
          {event.url ? (
            <a className="ctx__text" href={event.url} target="_blank" rel="noreferrer noopener">
              {localized(event.title, lang)}
            </a>
          ) : (
            <span className="ctx__text">{localized(event.title, lang)}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Section({
  source,
  title,
  count,
  children,
}: {
  source: string
  title: string
  count: number
  children: React.ReactNode
}) {
  const { t } = useI18n()
  return (
    <section className={`ctx__section ctx__section--${source}`} aria-label={title}>
      <h5 className="ctx__title">
        <SourceGlyph source={source} />
        {title}
        <span className="block__count" title={t.context.count(count)}>
          {count}
        </span>
      </h5>
      {children}
    </section>
  )
}

function ShortData({ context }: { context: Context }) {
  const { t, f } = useI18n()
  const latest = context.short.interest[0]
  const ratios = context.short.volume.map((row) => row.ratio).filter((r): r is number => r != null)
  const avg = ratios.length ? ratios.reduce((a, b) => a + b, 0) / ratios.length : null
  const fail = context.short.fails[0]
  if (!latest && avg == null && !fail) return <p className="ctx__none">{t.context.none}</p>
  return (
    <dl className="ctx__facts">
      {latest ? (
        <div>
          <dt>{t.context.shortInterest}</dt>
          <dd>
            {f.int(latest.short_shares)}
            <span className="ctx__sub">
              {f.dateShort(latest.settlement_date, true)}
              {latest.days_to_cover != null ? ` · ${t.context.daysToCover(f.decimal(latest.days_to_cover, 1))}` : ''}
            </span>
          </dd>
        </div>
      ) : null}
      {avg != null ? (
        <div title={t.context.shortVolumeTitle}>
          <dt>{t.context.shortVolume}</dt>
          <dd>{f.pct(avg, 0, false)}</dd>
        </div>
      ) : null}
      {fail ? (
        <div>
          <dt>{t.context.fails}</dt>
          <dd>
            {f.int(fail.quantity)}
            <span className="ctx__sub">{f.dateShort(fail.settlement_date, true)}</span>
          </dd>
        </div>
      ) : null}
    </dl>
  )
}

function SignalsRow({ signals, current }: { signals: Signal[]; current: string }) {
  const { t, f } = useI18n()
  const others = signals.filter((s) => s.id !== current).slice(0, MAX_ROWS)
  if (others.length === 0) return <p className="ctx__none">{t.context.none}</p>
  return (
    <ul className="ctx__list">
      {others.map((signal) => (
        <li key={signal.id} className="ctx__row">
          <span className="ctx__date">{f.dateShort(signal.date, true)}</span>
          <span className="ctx__text">
            <SignalGlyph type={signal.type} /> {t.signalType.short[signal.type]}
            <span className="ctx__sub"> · {t.sources.name[sourceOf(signal)]}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The company in focus seen through every source: insiders, Form 144, 8-K, 13F and short data. */
export function CompanyContext({ signal }: { signal: Signal }) {
  const { t, f } = useI18n()
  const mode = usePanel((s) => s.mode)
  const events = usePanel((s) => s.events)
  const version = useMemo(
    () => events.filter((e) => e.cik === signal.cik || (e.symbol && e.symbol === signal.symbol)).length,
    [events, signal.cik, signal.symbol],
  )
  const live = mode === 'live' && Boolean(signal.cik)
  const context = useCompanyContext(live ? signal.cik : null, version)

  return (
    <section className="block ctx" aria-label={t.context.title}>
      <h4 className="block__title">{t.context.title}</h4>
      {!live ? (
        <p className="note">{t.context.replay}</p>
      ) : context.error ? (
        <p className="note note--err">{t.context.error}</p>
      ) : !context.data ? (
        <p className="note" role="status">
          {t.context.loading}
        </p>
      ) : (
        <div className="ctx__grid">
          <Section source="insiders" title={t.context.insiders} count={context.data.insiders.length}>
            {context.data.insiders.length === 0 ? (
              <p className="ctx__none">{t.context.none}</p>
            ) : (
              <ul className="ctx__list">
                {context.data.insiders.slice(0, MAX_ROWS).map((row, index) => (
                  <li key={`${row.accession}-${index}`} className="ctx__row">
                    <span className="ctx__date">{f.dateShort(row.date, true)}</span>
                    <span className="ctx__text">
                      {personName(row.name)} <b>{f.usd(row.value)}</b>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section source="form144" title={t.context.form144} count={context.data.form144.length}>
            <EventList events={context.data.form144} />
          </Section>
          <Section source="eightk" title={t.context.eightk} count={context.data.eightk.length}>
            <EventList events={context.data.eightk} />
          </Section>
          <Section source="thirteenf" title={t.context.thirteenf} count={context.data.thirteenf.length}>
            <EventList events={context.data.thirteenf} />
          </Section>
          <Section source="short" title={t.context.short} count={context.data.short.interest.length}>
            <ShortData context={context.data} />
          </Section>
          <Section source="signals" title={t.context.signals} count={context.data.signals.length}>
            <SignalsRow signals={context.data.signals} current={signal.id} />
          </Section>
        </div>
      )}
    </section>
  )
}
