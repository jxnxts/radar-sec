import { localized, useI18n } from '../i18n'
import { useFetch } from '../lib/hooks'
import { usePanel } from '../store'
import type { Backtest, BacktestRow } from '../types'
import { CheckIcon, CrossIcon, SignalGlyph } from './glyphs'
import { Panel } from './Panel'

const TYPES = ['cluster_buy', 'big_officer_buy'] as const

const HORIZONS = [1, 3, 6]

function cell(rows: BacktestRow[], type: string, months: number): BacktestRow | undefined {
  return rows.find((row) => row.type === type && row.horizon_months === months)
}

/** Diverging bar: median excess over the SPY, with zero in the middle. */
function ExcessBar({ value, scale }: { value: number | null; scale: number }) {
  if (value == null) return null
  const width = Math.min(50, (Math.abs(value) / scale) * 50)
  return (
    <span className="xbar" aria-hidden="true">
      <span
        className={`xbar__fill xbar__fill--${value < 0 ? 'neg' : 'pos'}`}
        style={value < 0 ? { right: '50%', width: `${width}%` } : { left: '50%', width: `${width}%` }}
      />
    </span>
  )
}

function Scoreboard() {
  const { t, f } = useI18n()
  const board = usePanel((s) => s.status?.replay?.scoreboard ?? null)
  if (!board) return null
  return (
    <p className="bt__board">
      <span className="bt__board-label">{t.backtest.inThisReplay}</span>
      {board.measured === 0 ? (
        t.backtest.noneMeasured
      ) : (
        <>
          <b>{t.backtest.beatOf(f.int(board.beat_spy_6m), f.int(board.measured))}</b>
          {t.backtest.beatSpy}
          <b>{f.pct(board.median_excess_6m)}</b>
          {board.unmeasured > 0 ? t.backtest.unmeasuredCount(f.int(board.unmeasured)) : ''}
        </>
      )}
    </p>
  )
}

export function BacktestPanel() {
  const { t, f, lang } = useI18n()
  const { data, error, loading } = useFetch<Backtest>('/api/backtest')

  if (!data) {
    return (
      <Panel index="04" title={t.backtest.title} labelledBy="bt-title" className="bt">
        <div className="empty">
          <p className="empty__title">{loading ? t.backtest.reading : t.backtest.unavailable}</p>
          {error ? <p>{t.backtest.runHint}</p> : null}
        </div>
      </Panel>
    )
  }

  const years = data.period ? `${data.period.start.slice(0, 4)}–${data.period.end.slice(0, 4)}` : ''
  const scale = Math.max(...data.rows.map((row) => Math.abs(row.excess_median ?? 0)), 0.01)
  const yearList = [...new Set(data.by_year.map((row) => row.year))].sort()
  const funnel = 'generated' in data.funnel ? data.funnel : null
  const verdict = localized(data.verdict, lang)
  const caveat = localized(data.caveat, lang)

  return (
    <Panel
      index="04"
      title={t.backtest.title}
      labelledBy="bt-title"
      className="bt"
      aside={<span className="panel__meta">{t.backtest.against(years, data.benchmark)}</span>}
    >
      <div
        className={`bt__verdict bt__verdict--${data.beats_benchmark ? 'yes' : 'no'}`}
        title={[verdict, caveat].filter(Boolean).join('\n\n') || undefined}
      >
        <span className="bt__stamp" aria-hidden="true">
          {data.beats_benchmark ? <CheckIcon /> : <CrossIcon />}
        </span>
        <div>
          <p className="bt__headline">{data.beats_benchmark ? t.backtest.beat : t.backtest.notBeat}</p>
          <p className="bt__sub">{t.backtest.sub}</p>
        </div>
      </div>

      <table className="bt__grid">
        <caption className="sr-only">{t.backtest.caption(data.benchmark)}</caption>
        <thead>
          <tr>
            <th scope="col">{t.backtest.medianExcess}</th>
            {HORIZONS.map((months) => (
              <th scope="col" key={months}>
                {t.common.months(months)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TYPES.map((type) => (
            <tr key={type}>
              <th scope="row">
                <SignalGlyph type={type} />
                <span>
                  {t.signalType.short[type]}
                  <small>{t.backtest.signals(f.int(cell(data.rows, type, 6)?.n))}</small>
                </span>
              </th>
              {HORIZONS.map((months) => {
                const row = cell(data.rows, type, months)
                return (
                  <td key={months}>
                    <span className={`bt__num bt__num--${(row?.excess_median ?? 0) < 0 ? 'neg' : 'pos'}`}>
                      {f.pct(row?.excess_median)}
                    </span>
                    <ExcessBar value={row?.excess_median ?? null} scale={scale} />
                    <span className="bt__beats">{t.backtest.beatShare(f.pct(row?.beats, 1, false))}</span>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {yearList.length > 0 ? (
        <table className="bt__years">
          <caption>{t.backtest.yearsCaption}</caption>
          <thead>
            <tr>
              <td />
              {yearList.map((year) => (
                <th scope="col" key={year}>
                  {String(year).slice(2)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TYPES.map((type) => (
              <tr key={type}>
                <th scope="row">{t.signalType.tiny[type]}</th>
                {yearList.map((year) => {
                  const value = data.by_year.find((r) => r.type === type && r.year === year)?.excess_median_6m
                  const level = value == null ? 0 : Math.min(3, Math.ceil(Math.abs(value) / 0.045))
                  return (
                    <td key={year} className={`heat heat--${(value ?? 0) < 0 ? 'neg' : 'pos'}-${level}`}>
                      {f.pct(value, 0)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <p className="bt__notes">
        {t.backtest.maxT} <b>{f.decimal(data.max_t)}</b> {t.backtest.evidence}
        {funnel ? (
          <>
            {' · '}
            <b>{f.pct(funnel.unmeasured_share, 0, false)}</b> {t.backtest.unmeasured}
          </>
        ) : null}
        {' · '}
        {t.backtest.scoreNoHelp}
      </p>
      <Scoreboard />
    </Panel>
  )
}
