import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  TickMarkType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { intlLocale, useI18n } from '../i18n'
import { personName } from '../lib/format'
import { theme } from '../theme'
import type { PriceHistory, Purchase, Signal } from '../types'

interface Tip {
  x: number
  flip: boolean
  time: string
  close: number
  buys: Purchase[]
}

interface PriceChartProps {
  history: PriceHistory
  signal: Signal
  purchases: Purchase[]
}

/** First session on or after `date` (markers must land on a bar that exists). */
export function snapToBar(times: string[], date: string | null | undefined): string | null {
  if (!date) return null
  const day = date.slice(0, 10)
  return times.find((time) => time >= day) ?? null
}

/** Buys grouped by the chart session they fall on (those before the period are left out). */
export function groupPurchases(times: string[], purchases: Purchase[]): Map<string, Purchase[]> {
  const groups = new Map<string, Purchase[]>()
  const first = times[0]
  if (!first) return groups
  for (const purchase of purchases) {
    if (purchase.date < first) continue
    const time = snapToBar(times, purchase.date)
    if (!time) continue
    groups.set(time, [...(groups.get(time) ?? []), purchase])
  }
  return groups
}

/** Signal bar: the filing's session, or the last available one if the filing is from today. */
export function signalBar(times: string[], date: string): string | null {
  return snapToBar(times, date) ?? (times.length && date > times[times.length - 1]! ? times[times.length - 1]! : null)
}

export function buildMarkers(
  times: string[],
  signal: Signal,
  purchases: Purchase[],
  exitLabel: (months: string) => string = (months) => `${months} mo`,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = []

  // One marker per session: several buys on the same day become one dot with the count.
  for (const [time, rows] of groupPurchases(times, purchases)) {
    markers.push({
      time,
      position: 'belowBar',
      shape: 'circle',
      color: theme.ice,
      size: 1,
      text: rows.length > 1 ? String(rows.length) : undefined,
    })
  }

  const signalTime = signalBar(times, signal.date)
  if (signalTime) {
    markers.push({
      time: signalTime,
      position: 'aboveBar',
      shape: 'arrowDown',
      color: theme.amber,
      size: 2,
    })
  }

  for (const [months, horizon] of Object.entries(signal.outcome?.horizons ?? {})) {
    const time = snapToBar(times, horizon.exit_date)
    if (time && horizon.exit_date && time === horizon.exit_date) {
      markers.push({ time, position: 'aboveBar', shape: 'square', color: theme.textDim, text: exitLabel(months), size: 1 })
    }
  }
  return markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
}

export function PriceChart({ history, signal, purchases }: PriceChartProps) {
  const { t, f, lang } = useI18n()
  const host = useRef<HTMLDivElement>(null)
  const [signalX, setSignalX] = useState<number | null>(null)
  const [width, setWidth] = useState(0)
  const [tip, setTip] = useState<Tip | null>(null)

  useEffect(() => {
    const element = host.current
    if (!element || history.bars.length === 0) return
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
    const times = history.bars.map((bar) => bar.t)

    const chart: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: theme.textDim,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        fontSize: Math.round(rem * 0.7),
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: theme.line, style: LineStyle.Dotted },
        horzLines: { color: theme.line, style: LineStyle.Dotted },
      },
      rightPriceScale: { borderColor: theme.lineStrong, scaleMargins: { top: 0.16, bottom: 0.12 } },
      timeScale: {
        borderColor: theme.lineStrong,
        rightOffset: 2,
        fixLeftEdge: true,
        fixRightEdge: true,
        tickMarkFormatter: (time: Time, type: TickMarkType) => {
          const iso = String(time)
          if (type === TickMarkType.Year) return iso.slice(0, 4)
          return type === TickMarkType.Month ? f.monthShort(iso) : f.dateShort(iso)
        },
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: theme.textDim, labelBackgroundColor: theme.lineStrong },
        horzLine: { color: theme.textDim, labelBackgroundColor: theme.lineStrong },
      },
      localization: {
        locale: intlLocale(lang),
        priceFormatter: (value: number) => f.price(value),
        timeFormatter: (time: Time) => f.date(String(time)),
      },
      handleScroll: false,
      handleScale: false,
    })

    const series =
      history.kind === 'ohlc'
        ? chart.addSeries(CandlestickSeries, {
            upColor: theme.up,
            downColor: theme.down,
            wickUpColor: theme.up,
            wickDownColor: theme.down,
            borderVisible: false,
            priceLineVisible: false,
          })
        : chart.addSeries(AreaSeries, {
            lineColor: theme.ice,
            topColor: 'rgba(108, 198, 255, 0.22)',
            bottomColor: 'rgba(108, 198, 255, 0)',
            lineWidth: 2,
            priceLineVisible: false,
          })
    if (history.kind === 'ohlc') {
      series.setData(
        history.bars.map((bar) => ({ time: bar.t, open: bar.o, high: bar.h, low: bar.l, close: bar.c })),
      )
    } else {
      series.setData(history.bars.map((bar) => ({ time: bar.t, value: bar.c })))
    }

    createSeriesMarkers(series, buildMarkers(times, signal, purchases, (months) => t.common.monthsShort(months)))

    const buys = groupPurchases(times, purchases)
    const closes = new Map(history.bars.map((bar) => [bar.t, bar.c]))
    chart.subscribeCrosshairMove((param) => {
      const time = param.time ? String(param.time) : null
      const close = time ? closes.get(time) : undefined
      if (!time || close === undefined || !param.point) {
        setTip(null)
        return
      }
      setTip({
        x: param.point.x,
        flip: param.point.x > element.clientWidth * 0.6,
        time,
        close,
        buys: buys.get(time) ?? [],
      })
    })

    // Average price paid by the insiders. Only drawn when it matches the chart:
    // the series is split-adjusted, the Form 4 price is not.
    const signalTime = signalBar(times, signal.date)
    const reference = history.bars.find((bar) => bar.t === signalTime)?.c
    if (signal.avg_price && reference && Math.abs(signal.avg_price / reference - 1) < 0.3) {
      series.createPriceLine({
        price: signal.avg_price,
        color: theme.ice,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: t.chart.avgPriceLine,
      })
    }

    chart.timeScale().fitContent()

    const place = () => {
      const x = signalTime ? chart.timeScale().timeToCoordinate(signalTime as Time) : null
      setSignalX(x)
      setWidth(element.clientWidth)
    }
    place()
    chart.timeScale().subscribeVisibleLogicalRangeChange(place)
    const observer = new ResizeObserver(() => requestAnimationFrame(place))
    observer.observe(element)

    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [history, signal, purchases, t, f, lang])

  const first = history.bars[0]
  const last = history.bars[history.bars.length - 1]
  const summary =
    first && last
      ? t.chart.summary(
          history.symbol,
          f.date(first.t),
          f.date(last.t),
          f.price(first.c),
          f.price(last.c),
          f.date(signal.date),
        )
      : ''

  return (
    <figure className="chart">
      <div className="chart__canvas" ref={host} role="img" aria-label={summary} />
      {signalX != null ? (
        <div
          className={`chart__signal${signalX > width * 0.62 ? ' chart__signal--flip' : ''}`}
          style={{ transform: `translateX(${signalX}px)` }}
          aria-hidden="true"
        >
          <span>{t.chart.signalPublic(f.date(signal.date))}</span>
        </div>
      ) : null}
      {tip ? (
        <div
          className="chart__tip"
          style={tip.flip ? { right: `calc(100% - ${tip.x - 14}px)` } : { left: tip.x + 14 }}
          aria-hidden="true"
        >
          <span>
            <b>{f.date(tip.time)}</b> · {t.chart.closedAt(f.price(tip.close))}
          </span>
          {tip.buys.length > 0 ? (
            <>
              <span>
                {t.chart.buys(tip.buys.length)} · <b>{f.usd(tip.buys.reduce((sum, row) => sum + row.value, 0))}</b>
              </span>
              {tip.buys.slice(0, 4).map((row, index) => (
                <span className="chart__tip-buy" key={index}>
                  <span>{personName(row.name)}</span>
                  <span>{f.usd(row.value)}</span>
                </span>
              ))}
              {tip.buys.length > 4 ? <span>{t.common.andMore(tip.buys.length - 4)}</span> : null}
            </>
          ) : null}
        </div>
      ) : null}
      <figcaption className="chart__caption">
        <span className="chart__legend">
          <i className="key key--signal" /> {t.chart.legendFiling}
          <i className="key key--buy" /> {t.chart.legendBuy}
          {signal.outcome?.horizons ? (
            <>
              <i className="key key--exit" /> {t.chart.legendExit}
            </>
          ) : null}
        </span>
        <span>
          {history.kind === 'ohlc' ? t.chart.daily : t.chart.close} · {history.source} ·{' '}
          <span className="tag tag--delay">{t.chart.delayed(history.delay_minutes)}</span>
        </span>
      </figcaption>
    </figure>
  )
}
