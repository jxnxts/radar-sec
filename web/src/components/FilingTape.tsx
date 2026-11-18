import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../i18n'
import { clockOf, personName, type Format } from '../lib/format'
import { usePrefersReducedMotion } from '../lib/hooks'
import { usePanel } from '../store'
import type { Filing } from '../types'
import { KindGlyph } from './glyphs'

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

/**
 * Filing tape. The newest one stays still on the left (and flashes on arrival); the rest
 * scroll by on the tape, which only swaps its content at the end of each loop to avoid jumps.
 */
export function FilingTape() {
  const { t } = useI18n()
  const filings = usePanel((s) => s.filings)
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState<Filing[]>(filings)
  const latest = filings[0]

  useEffect(() => {
    if (shown.length === 0 || reduced) setShown(filings)
  }, [filings, shown.length, reduced])

  const duration = useMemo(() => Math.max(40, shown.length * 5), [shown.length])

  return (
    <footer className="tape" aria-label={t.tape.group}>
      <div className="tape__latest">
        <span className="tape__label">{t.tape.latest}</span>
        {latest ? (
          <span className="tape__flash" key={latest.accession}>
            <TapeItem filing={latest} />
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
            onAnimationIteration={() => setShown(usePanel.getState().filings)}
          >
            {[0, 1].map((copy) => (
              <div className="tape__run" key={copy} aria-hidden={copy === 1}>
                {shown.map((filing) => (
                  <TapeItem key={`${copy}-${filing.accession}`} filing={filing} />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </footer>
  )
}
