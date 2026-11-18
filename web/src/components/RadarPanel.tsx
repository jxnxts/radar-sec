import { labelOf, useI18n } from '../i18n'
import { usePanel } from '../store'
import { Logo } from './Logo'
import { Panel } from './Panel'
import { RadarScope } from './RadarScope'

export function RadarPanel() {
  const { t, f } = useI18n()
  const window = usePanel((s) => s.window)
  const ranking = usePanel((s) => s.ranking[s.window])
  const setWindow = usePanel((s) => s.setWindow)
  const select = usePanel((s) => s.select)

  const pick = (cik: string) => {
    const match = usePanel.getState().signals.find((signal) => signal.cik === cik)
    if (match) select(match.id)
  }

  const max = ranking?.companies[0]?.value ?? 0
  const sectors = (ranking?.sectors ?? [])
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)

  return (
    <Panel
      index="03"
      title={t.radar.title}
      labelledBy="radar-title"
      className="radar"
      aside={
        <div className="segmented" role="group" aria-label={t.radar.window}>
          {(['7', '30'] as const).map((days) => (
            <button
              key={days}
              type="button"
              className="chip"
              aria-pressed={window === days}
              onClick={() => setWindow(days)}
            >
              {t.common.days(days)}
            </button>
          ))}
        </div>
      }
    >
      {!ranking ? (
        <div className="empty">
          <p className="empty__title">{t.radar.building}</p>
        </div>
      ) : (
        <>
          <RadarScope ranking={ranking} onPick={pick} />
          <p className="radar__sectors" title={t.radar.basis(labelOf(t.radar.bases, ranking.basis))}>
            {sectors.length > 0 ? (
              sectors.map((s) => (
                <span key={s.sector}>
                  <b>{labelOf(t.sectors, s.sector)}</b> {f.pct(s.share, 0, false)}
                </span>
              ))
            ) : (
              <span>{t.radar.noBuys}</span>
            )}
          </p>
          <p className="radar__key" title={t.radar.sizeTitle}>
            {t.radar.key(ranking.days)}
            {ranking.coverage_since ? t.radar.since(f.dateShort(ranking.coverage_since)) : t.radar.dotValue}
          </p>

          <ol className="rank" aria-label={t.radar.rankGroup(ranking.days)}>
            {ranking.companies.slice(0, 4).map((company, index) => (
              <li key={company.cik || company.name} className="rank__row">
                <span className="rank__pos">{index + 1}</span>
                <Logo src={company.logo} ticker={company.symbol || company.ticker} company={company.name} size="sm" />
                <span className="rank__id">
                  <span className="rank__ticker">{company.symbol || company.ticker || '—'}</span>
                  <span className="rank__name">{company.name}</span>
                </span>
                <span className="rank__bar" aria-hidden="true">
                  <span style={{ width: `${max ? Math.max(4, (company.value / max) * 100) : 0}%` }} />
                </span>
                <span className="rank__value">{f.usd(company.value)}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </Panel>
  )
}
