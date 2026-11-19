import { useEffect, useMemo, useState } from 'react'
import { localized, useI18n } from '../i18n'
import { clockOf, personName, type Format } from '../lib/format'
import { usePrefersReducedMotion } from '../lib/hooks'
import { usePanel } from '../store'
import type { Filing, MarketEvent } from '../types'
import { KindGlyph, SourceGlyph } from './glyphs'

function formBadge(form: string): string {
  if (form.includes('13D')) return form.endsWith('/A') ? '13D/A' : '13D'
  return form === '4/A' ? 'F4/A' : 'F4'
}

function amount(filing: Filing, f: Format): string {
  if (filing.percent != null) return f.points(filing.percent, 1)
  if (filing.value != null && filing.value > 0) return f.usd(filing.value)
  return ''
}

function TapeItem({ filing }: { filing: Filing }) {
  const { t, f } = useI18n()
  const value = amount(filing, f)
  const who = filing.who ? personName(filing.who) : ''
  const content = (
    <>
      <span className="tape__form">{formBadge(filing.form)}</span>
      <span className="tape__ticker">{filing.ticker || filing.company}</span>
      {who ? <span className="tape__who">{who}</span> : null}
      <span className={`tape__kind tape__kind--${filing.kind}`}>
        <KindGlyph kind={filing.kind} />
        {t.filingKinds[filing.kind] ?? filing.kind_label}
        {value ? <b>{value}</b> : null}
      </span>
      <span className="tape__when">
        {f.dateShort(filing.filed_date)}
        {filing.accepted_at ? ` ${clockOf(filing.accepted_at)}` : ''}
      </span>
    </>
  )
  return filing.url ? (
    <a className="tape__item" href={filing.url} target="_blank" rel="noreferrer noopener" tabIndex={-1}>
      {content}
    </a>
  ) : (
    <span className="tape__item">{content}</span>
  )
}

function EventTapeItem({ event }: { event: MarketEvent }) {
  const { t, f, lang } = useI18n()
  const content = (
    <>
      <span className={`tape__form tape__form--${event.source}`}>
        <SourceGlyph source={event.source} />
        {t.sources.eventKinds[event.kind] ?? t.sources.name[event.source] ?? event.source}
      </span>
      {event.ticker || event.company ? (
        <span className="tape__ticker">{event.ticker || event.company}</span>
      ) : null}
      <span className="tape__event">{localized(event.title, lang)}</span>
      <span className="tape__when">
        {f.dateShort(event.date)}
        {event.seen_at ? ` ${clockOf(event.seen_at)}` : ''}
      </span>
    </>
  )
  return event.url ? (
    <a className="tape__item" href={event.url} target="_blank" rel="noreferrer noopener" tabIndex={-1}>
      {content}
    </a>
  ) : (
    <span className="tape__item">{content}</span>
  )
}

type TapeEntry = { key: string; at: string; filing?: Filing; event?: MarketEvent }

/** Filings and extra-source events on one tape, newest first. */
export function tapeEntries(filings: Filing[], events: MarketEvent[]): TapeEntry[] {
  const entries: TapeEntry[] = [
    ...filings.map((filing) => ({
      key: `f-${filing.accession}`,
      at: filing.accepted_at ?? filing.filed_date ?? '',
      filing,
    })),
    ...events.map((event) => ({ key: `e-${event.id}`, at: event.seen_at ?? event.date, event })),
  ]
  // Stable sort: equal times keep the server order (newest first within each list).
  return entries.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
}

function Entry({ entry }: { entry: TapeEntry }) {
  return entry.filing ? <TapeItem filing={entry.filing} /> : entry.event ? <EventTapeItem event={entry.event} /> : null
}

/**
 * Filing tape. The newest one stays still on the left (and flashes on arrival); the rest
 * scroll by on the tape, which only swaps its content at the end of each loop to avoid jumps.
 */
export function FilingTape() {
  const { t } = useI18n()
  const filings = usePanel((s) => s.filings)
  const events = usePanel((s) => s.events)
  const entries = useMemo(() => tapeEntries(filings, events), [filings, events])
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState<TapeEntry[]>(entries)
  const latest = entries[0]

  useEffect(() => {
    if (shown.length === 0 || reduced) setShown(entries)
  }, [entries, shown.length, reduced])

  const duration = useMemo(() => Math.max(40, shown.length * 5), [shown.length])

  return (
    <footer className="tape" aria-label={t.tape.group}>
      <div className="tape__latest">
        <span className="tape__label">{t.tape.latest}</span>
        {latest ? (
          <span className="tape__flash" key={latest.key}>
            <Entry entry={latest} />
          </span>
        ) : (
          <span className="tape__idle">{t.tape.waiting}</span>
        )}
      </div>
      <div className="tape__window">
        {shown.length === 0 ? (
          <span className="tape__idle">{t.tape.empty}</span>
        ) : (
          <div
            className="tape__track"
            style={{ animationDuration: `${duration}s` }}
            onAnimationIteration={() => {
              const state = usePanel.getState()
              setShown(tapeEntries(state.filings, state.events))
            }}
          >
            {[0, 1].map((copy) => (
              <div className="tape__run" key={copy} aria-hidden={copy === 1}>
                {shown.map((entry) => (
                  <Entry key={`${copy}-${entry.key}`} entry={entry} />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </footer>
  )
}
