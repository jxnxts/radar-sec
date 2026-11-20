import { labelOf, localized, roleLabel, useI18n } from '../i18n'
import { personName } from '../lib/format'
import { usePriceHistory, useSignalDetail } from '../lib/hooks'
import { quoteDelay } from '../lib/market'
import { cardFacts, factLabel, formatFact } from '../lib/facts'
import { sourceOf, usePanel } from '../store'
import type { Outcome, Purchase, Quote, Signal } from '../types'
import { CompanyContext } from './CompanyContext'
import { Delta } from './Delta'
import { ExternalIcon, SignalGlyph } from './glyphs'
import { Logo } from './Logo'
import { Panel } from './Panel'
import { PriceChart } from './PriceChart'
import { ScoreRing } from './ScoreRing'
import { OutcomeBadge } from './SignalCard'

function Kpi({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`kpi${wide ? ' kpi--wide' : ''}`}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function OutcomeTable({ outcome }: { outcome: Outcome }) {
  const { t, f } = useI18n()
  if (outcome.status !== 'ok' || !outcome.horizons) {
    return (
      <p className="aftermath__none">
        {t.detail.notMeasuredBefore}
        <OutcomeBadge outcome={outcome} />
        {t.detail.notMeasuredAfter}
      </p>
    )
  }
  return (
    <table className="aftermath__table">
      <thead>
        <tr>
          <th scope="col">{t.detail.horizon}</th>
          <th scope="col">{t.detail.signal}</th>
          <th scope="col">SPY</th>
          <th scope="col">{t.detail.excess}</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(outcome.horizons).map(([months, h]) => (
          <tr key={months}>
            <th scope="row">{t.common.months(Number(months))}</th>
            <td>{f.pct(h.ret)}</td>
            <td>{f.pct(h.spy)}</td>
            <td>
              <Delta value={h.excess} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function headlineFact(signal: Signal) {
  return cardFacts(signal.facts)[0]
}

/** KPIs of a signal of the extra sources, straight from its facts. */
function SourceKpis({ signal, quote }: { signal: Signal; quote: Quote | undefined }) {
  const { t, f } = useI18n()
  const facts = (signal.facts ?? []).filter((fact) => fact.kind !== 'quote')
  return (
    <dl className="kpis">
      {facts.map((fact) => (
        <Kpi key={fact.key} label={factLabel(t, fact)} wide={fact.kind === 'items'}>
          {formatFact(t, f, fact)}
        </Kpi>
      ))}
      {quote ? (
        <Kpi label={t.detail.kpi.quoteDelayed(quoteDelay(quote))}>
          {f.price(quote.price)} <Delta value={quote.change_pct} digits={2} />
        </Kpi>
      ) : null}
    </dl>
  )
}

function Kpis({ signal, quote }: { signal: Signal; quote: Quote | undefined }) {
  const { t, f } = useI18n()
  const k = t.detail.kpi
  if (sourceOf(signal) !== 'insiders') return <SourceKpis signal={signal} quote={quote} />
  if (signal.type === 'activist_13d') {
    return (
      <dl className="kpis">
        <Kpi label={k.declaredStake}>{f.points(signal.percent, 2)}</Kpi>
        <Kpi label={k.shares}>{f.int(signal.shares)}</Kpi>
        <Kpi label={k.eventDate}>{f.date(signal.event_date)}</Kpi>
        <Kpi label={k.tone}>{signal.activist_tone ? k.activist : k.neutral}</Kpi>
        {quote ? (
          <Kpi label={k.quoteDelayed(quoteDelay(quote))}>
            {f.price(quote.price)} <Delta value={quote.change_pct} digits={2} />
          </Kpi>
        ) : null}
      </dl>
    )
  }
  const sinceBuy = quote && signal.avg_price ? quote.price / signal.avg_price - 1 : null
  return (
    <dl className="kpis">
      <Kpi label={k.bought}>{f.usd(signal.value)}</Kpi>
      <Kpi label={signal.type === 'cluster_buy' ? k.distinctInsiders : k.stakeIncrease}>
        {signal.type === 'cluster_buy' ? f.int(signal.n_insiders) : f.pct(signal.stake_increase)}
      </Kpi>
      <Kpi label={k.avgPrice}>{f.money(signal.avg_price)}</Kpi>
      <Kpi label={k.buys}>
        {signal.first_buy === signal.last_buy
          ? f.dateShort(signal.last_buy)
          : k.range(f.dateShort(signal.first_buy), f.dateShort(signal.last_buy))}
      </Kpi>
      {quote ? (
        <Kpi label={k.quoteDelayed(quoteDelay(quote))}>
          {f.price(quote.price)}
          {sinceBuy != null ? (
            <span className="kpi__sub">
              <Delta value={sinceBuy} /> {k.vsBuy}
            </span>
          ) : null}
        </Kpi>
      ) : null}
    </dl>
  )
}

function Purchases({ rows }: { rows: Purchase[] }) {
  const { t, f } = useI18n()
  const columns = t.detail.columns
  if (rows.length === 0) {
    return <p className="note">{t.detail.noPurchases}</p>
  }
  return (
    <div className="tablewrap" tabIndex={0} role="region" aria-label={t.detail.purchasesRegion}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{columns.date}</th>
            <th scope="col">{columns.insider}</th>
            <th scope="col" className="num">{columns.shares}</th>
            <th scope="col" className="num">{columns.price}</th>
            <th scope="col" className="num">{columns.value}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const role = roleLabel(t, row.role)
            return (
              <tr key={`${row.accession}-${row.date}-${index}`}>
                <td>{f.dateShort(row.date, true)}</td>
                <td className="who" title={`${personName(row.name)} · ${role}`}>
                  <span className="table__name">{personName(row.name)}</span>
                  <span className="table__role">{role}</span>
                </td>
                <td className="num">{f.int(row.shares)}</td>
                <td className="num">{f.price(row.price)}</td>
                <td className="num strong">{f.usd(row.value)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function SignalDetail() {
  const { t, f, lang } = useI18n()
  const selectedId = usePanel((s) => s.selectedId)
  const signal = usePanel((s) => s.signals.find((item) => item.id === s.selectedId) ?? null)
  const quote = usePanel((s) => (signal?.symbol ? s.quotes[signal.symbol] : undefined))
  const detail = useSignalDetail(selectedId)
  const history = usePriceHistory(detail.data?.chart)

  if (!signal) {
    return (
      <Panel index="02" title={t.detail.title} labelledBy="detail-title" className="detail">
        <div className="empty empty--tall">
          <p className="empty__title">{t.detail.waitingTitle}</p>
          <p>{t.detail.waitingText}</p>
        </div>
      </Panel>
    )
  }

  const purchases = detail.data?.purchases ?? []
  const previous = detail.data?.previous_signals ?? []
  const summaryLines = localized(signal.summary, lang)
    .split('\n')
    .filter((line) => line.trim())
  const byAi = localized(signal.summary_source, lang) === 'ai'
  const excerpt = signal.facts?.find((fact) => fact.kind === 'quote')

  return (
    <Panel
      index="02"
      title={t.detail.title}
      labelledBy="detail-title"
      className={`detail detail--${signal.type}`}
      aside={
        signal.filing_url ? (
          <a className="link" href={signal.filing_url} target="_blank" rel="noreferrer noopener">
            {t.detail.openFiling} <ExternalIcon />
          </a>
        ) : null
      }
    >
      <div className="detail__scroll" key={signal.id}>
        <header className="detail__head">
          <Logo src={signal.logo} ticker={signal.symbol || signal.ticker} company={signal.company} size="lg" />
          <div className="detail__id">
            <h3 className="detail__ticker">{signal.symbol || signal.ticker || signal.company}</h3>
            <p className="detail__company">
              {signal.company}
              {signal.sector ? <span className="detail__sector">{labelOf(t.sectors, signal.sector)}</span> : null}
            </p>
          </div>
          <div className="detail__type">
            <span className="type type--lg">
              <SignalGlyph type={signal.type} />
              {t.signalType.long[signal.type]}
            </span>
            <span className="detail__date">{t.detail.publishedOn(f.date(signal.date))}</span>
          </div>
          <ScoreRing score={signal.score} size="lg" />
        </header>

        <Kpis signal={signal} quote={quote} />

        <div className="detail__chart">
          {!signal.symbol ? (
            <div className="empty">
              <p className="empty__title">{t.detail.noTicker}</p>
              <p>{t.detail.noTickerText}</p>
            </div>
          ) : history.loading || detail.loading ? (
            <div className="empty empty--loading" role="status">
              <span className="sweep" aria-hidden="true" />
              {t.detail.loadingPrices(signal.symbol)}
            </div>
          ) : history.data && history.data.bars.length > 1 ? (
            <PriceChart history={history.data} signal={signal} purchases={purchases} />
          ) : (
            <div className="empty">
              <p className="empty__title">{t.detail.noPrices(signal.symbol)}</p>
              <p>{t.detail.noPricesText}</p>
            </div>
          )}
        </div>

        <div className="detail__lower">
          <section className="block" aria-label={t.detail.summaryRegion}>
            <h4 className="block__title">
              {t.detail.summary}
              <span className={`tag tag--${byAi ? 'ai' : 'template'}`}>{byAi ? t.detail.byAi : t.detail.template}</span>
            </h4>
            <div className="summary">
              {summaryLines.map((line, index) => (
                <p key={index}>{line}</p>
              ))}
            </div>
            {signal.outcome ? (
              <div className="aftermath">
                <h4 className="block__title">{t.detail.afterwards}</h4>
                <OutcomeTable outcome={signal.outcome} />
              </div>
            ) : (
              <>
                <h4 className="block__title">{t.detail.rule}</h4>
                <p className="rule">{localized(signal.explanation, lang)}</p>
                {excerpt ? <blockquote className="excerpt">{formatFact(t, f, excerpt)}</blockquote> : null}
              </>
            )}
          </section>

          <section className="block" aria-label={t.detail.buysRegion}>
            <h4 className="block__title">
              {signal.mode === 'replay' ? t.detail.replayBuys : t.detail.companyBuys}
              <span className="block__count">{purchases.length}</span>
            </h4>
            {detail.error ? <p className="note note--err">{t.detail.loadError}</p> : <Purchases rows={purchases} />}
            {previous.length > 0 ? (
              <>
                <h4 className="block__title">
                  {t.detail.previous} <span className="block__count">{previous.length}</span>
                </h4>
                <ul className="previous">
                  {previous.slice(0, 4).map((item) => (
                    <li key={item.id} className="previous__item">
                      <SignalGlyph type={item.type} />
                      <span>{f.dateShort(item.date, true)}</span>
                      <span>{t.signalType.short[item.type]}</span>
                      <span className="num">
                        {sourceOf(item) !== 'insiders'
                          ? headlineFact(item)
                            ? formatFact(t, f, headlineFact(item)!)
                            : ''
                          : item.type === 'activist_13d'
                            ? f.points(item.percent)
                            : f.usd(item.value)}
                      </span>
                      {item.outcome ? <OutcomeBadge outcome={item.outcome} /> : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        </div>

        <CompanyContext signal={signal} />
      </div>
    </Panel>
  )
}
