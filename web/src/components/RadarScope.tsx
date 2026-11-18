import { labelOf, useI18n } from '../i18n'
import { hueOf } from '../lib/format'
import type { RankedCompany, Ranking } from '../types'

// Scope geometry (viewBox units).
const WIDTH = 520
const HEIGHT = 400
const CX = WIDTH / 2
const CY = HEIGHT / 2
const R_OUT = 158
const R_IN = 30
const LABEL_R = 172

function polar(radius: number, degrees: number): [number, number] {
  const radians = (degrees * Math.PI) / 180
  return [CX + radius * Math.cos(radians), CY + radius * Math.sin(radians)]
}

function wedge(start: number, end: number, inner: number, outer: number): string {
  const [x1, y1] = polar(outer, start)
  const [x2, y2] = polar(outer, end)
  const [x3, y3] = polar(inner, end)
  const [x4, y4] = polar(inner, start)
  return `M${x1.toFixed(1)} ${y1.toFixed(1)} A${outer} ${outer} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L${x3.toFixed(1)} ${y3.toFixed(1)} A${inner} ${inner} 0 0 0 ${x4.toFixed(1)} ${y4.toFixed(1)} Z`
}

/** Stable fraction between 0 and 1 from a text (spreads the dots without randomness). */
function spread(text: string, salt: number): number {
  return ((hueOf(text) * 7 + salt * 131) % 360) / 360
}

export interface Blip {
  company: RankedCompany
  x: number
  y: number
  r: number
  labelled: boolean
  /** Label to the left of the dot (right half of the scope), so it doesn't run into the sector name. */
  labelLeft: boolean
}

export function placeBlips(ranking: Ranking): Blip[] {
  const sectors = ranking.sectors.map((s) => s.sector)
  const step = 360 / Math.max(sectors.length, 1)
  const max = Math.max(...ranking.blips.map((b) => b.value), 1)
  return ranking.blips.map((company, index) => {
    const sector = Math.max(0, sectors.indexOf(company.sector))
    const start = sector * step - 90
    const angle = start + step * (0.14 + 0.72 * spread(company.cik || company.name, 1))
    // Edge = today; the older the buy, the closer to the center.
    const age = Math.min(company.age_days, ranking.days) / ranking.days
    const jitter = (spread(company.cik || company.name, 2) - 0.5) * 10
    const radius = R_IN + 18 + (1 - age) * (R_OUT - R_IN - 32) + jitter
    const [x, y] = polar(radius, angle)
    return { company, x, y, r: 3.2 + 10 * Math.sqrt(company.value / max), labelled: index < 5, labelLeft: x > CX }
  })
}

interface RadarScopeProps {
  ranking: Ranking
  onPick: (cik: string) => void
}

/**
 * Radar scope: each slice is a sector, each dot a company with insider buys.
 * Dot size is the amount bought; the edge is today and the center the start of the window.
 * The list next to it carries the same data as text.
 */
export function RadarScope({ ranking, onPick }: RadarScopeProps) {
  const { t, f } = useI18n()
  const sectors = ranking.sectors
  const step = 360 / Math.max(sectors.length, 1)
  const topShare = Math.max(...sectors.map((s) => s.share), 0.0001)
  const blips = placeBlips(ranking)
  const leader = sectors.reduce((best, s) => (s.value > best.value ? s : best), sectors[0]!)
  const description =
    ranking.total_companies === 0
      ? t.radar.scopeEmpty(ranking.days)
      : t.radar.scope(ranking.total_companies, ranking.days, f.usd(ranking.total_value), labelOf(t.sectors, leader.sector))

  return (
    <svg className="scope" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={description}>
      <defs>
        <radialGradient id="scope-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--amber)" stopOpacity="0.10" />
          <stop offset="100%" stopColor="var(--amber)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx={CX} cy={CY} r={R_OUT} fill="url(#scope-glow)" />

      {sectors.map((sector, index) => {
        const start = index * step - 90
        const mid = start + step / 2
        const [lx, ly] = polar(LABEL_R, mid)
        const cos = Math.cos((mid * Math.PI) / 180)
        const anchor = cos > 0.1 ? 'start' : cos < -0.1 ? 'end' : 'middle'
        const heat = sector.value > 0 ? 0.05 + 0.3 * (sector.share / topShare) : 0
        const [dx, dy] = polar(R_OUT, start)
        const [ix, iy] = polar(R_IN, start)
        return (
          <g key={sector.sector} className={`scope__sector${sector.value > 0 ? ' is-active' : ''}`}>
            <path d={wedge(start, start + step, R_IN, R_OUT)} fill="var(--amber)" fillOpacity={heat} />
            <line x1={ix} y1={iy} x2={dx} y2={dy} className="scope__spoke" />
            <text x={lx} y={ly} textAnchor={anchor} dominantBaseline="middle" className="scope__label">
              {labelOf(t.sectors, sector.sector)}
              {sector.companies > 0 ? <tspan className="scope__count"> {sector.companies}</tspan> : null}
            </text>
          </g>
        )
      })}

      {[1, 0.66, 0.33].map((fraction) => (
        <circle
          key={fraction}
          cx={CX}
          cy={CY}
          r={R_IN + (R_OUT - R_IN) * fraction}
          className={`scope__ring${fraction === 1 ? ' scope__ring--rim' : ''}`}
        />
      ))}
      <circle cx={CX} cy={CY} r={R_IN} className="scope__ring" />
      <circle cx={CX} cy={CY} r="2.5" className="scope__center" />

      <g className="scope__sweep" aria-hidden="true">
        {Array.from({ length: 14 }, (_, i) => (
          <path
            key={i}
            d={wedge(-90 - (i + 1) * 3, -90 - i * 3, R_IN, R_OUT)}
            fill="var(--amber)"
            fillOpacity={0.16 * (1 - i / 14)}
          />
        ))}
        <line x1={CX} y1={CY - R_IN} x2={CX} y2={CY - R_OUT} className="scope__beam" />
      </g>

      {blips.map((blip) => (
        <g
          key={blip.company.cik || blip.company.name}
          className="scope__blip"
          role="button"
          tabIndex={0}
          onClick={() => onPick(blip.company.cik)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onPick(blip.company.cik)
            }
          }}
        >
          <title>
            {`${blip.company.ticker || blip.company.name} · ${labelOf(t.sectors, blip.company.sector)} · ${f.usd(blip.company.value)} · ${blip.company.age_days === 0 ? t.time.today : t.time.ago(t.time.days(blip.company.age_days))}`}
          </title>
          <circle cx={blip.x} cy={blip.y} r={blip.r + 5} className="scope__hit" />
          <circle cx={blip.x} cy={blip.y} r={blip.r} className="scope__dot" />
          {blip.labelled && blip.company.ticker ? (
            <text
              x={blip.labelLeft ? blip.x - blip.r - 4 : blip.x + blip.r + 4}
              y={blip.y}
              textAnchor={blip.labelLeft ? 'end' : 'start'}
              dominantBaseline="middle"
              className="scope__ticker"
            >
              {blip.company.symbol || blip.company.ticker}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  )
}
