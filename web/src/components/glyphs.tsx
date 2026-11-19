// Dashboard icons, drawn here (no icon library and no third-party images).

import type { SVGProps } from 'react'
import type { FilingKind, SignalType, Source } from '../types'

type IconProps = SVGProps<SVGSVGElement> & { title?: string }

function Svg({ title, children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  )
}

/** Product mark: a radar screen with one contact. */
export function RadarMark(props: IconProps) {
  return (
    <Svg viewBox="0 0 32 32" strokeWidth={1.6} {...props}>
      <circle cx="16" cy="16" r="13" opacity=".35" />
      <circle cx="16" cy="16" r="8" opacity=".6" />
      <circle cx="16" cy="16" r="3" opacity=".9" />
      <path d="M16 16 27.2 9.5" />
      <circle cx="22.5" cy="21.5" r="2.4" fill="currentColor" stroke="none" />
    </Svg>
  )
}

/** Cluster buy: three insiders. */
export function ClusterGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="6.5" r="3" />
      <circle cx="5.5" cy="17" r="3" />
      <circle cx="18.5" cy="17" r="3" />
      <path d="M10.4 9.1 7.1 14.4M13.6 9.1l3.3 5.3M8.5 17h7" opacity=".55" />
    </Svg>
  )
}

/** Large CEO/CFO buy: one person, one arrow up. */
export function OfficerGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="9" cy="7.5" r="3.2" />
      <path d="M3 20c.4-3.6 2.8-5.8 6-5.8 1.4 0 2.6.4 3.6 1.1" />
      <path d="M18 20v-9M14.5 14.2 18 10.7l3.5 3.5" />
    </Svg>
  )
}

/** 13D: a significant slice of the company. */
export function StakeGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 12V3.5M12 12l7.4 4.2" />
      <path d="M12 3.5A8.5 8.5 0 0 1 19.4 16.2L12 12Z" fill="currentColor" fillOpacity=".3" stroke="none" />
    </Svg>
  )
}

/** Form 144: a notice with an arrow down (planned sale). */
export function NoticeGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 3.5h8l4 4V20.5H6Z" />
      <path d="M14 3.5v4h4" opacity=".55" />
      <path d="M12 10.5v6.5M9.2 14.4 12 17l2.8-2.6" />
    </Svg>
  )
}

/** 13F: stacked holdings of a fund. */
export function FundGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 19.5h16" />
      <path d="M6.5 19.5V12h3v7.5M10.5 19.5V7h3v12.5M14.5 19.5v-9.5h3v9.5" />
    </Svg>
  )
}

/** 8-K: a report with an exclamation mark (something happened). */
export function ReportGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="5" y="3.5" width="14" height="17" rx="1.5" />
      <path d="M12 8v5.5" />
      <circle cx="12" cy="16.6" r=".9" fill="currentColor" stroke="none" />
    </Svg>
  )
}

/** News: a folded newspaper. */
export function NewsGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 5.5h11v13H6.5A1.5 1.5 0 0 1 5 17V5.5Z" />
      <path d="M16 9h3v8.5a1 1 0 0 1-1 1h-2" />
      <path d="M8 9h5M8 12h5M8 15h3" opacity=".7" />
    </Svg>
  )
}

/** Short data: a falling line over a bar. */
export function ShortGlyph(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 6.5 9.5 12l3-3L20 16.5" />
      <path d="M15.5 16.5H20V12" />
      <path d="M4 20h16" opacity=".55" />
    </Svg>
  )
}

const SOURCE_OF_TYPE: Partial<Record<SignalType, Source>> = {
  form144_cluster: 'form144',
  form144_large: 'form144',
  fund_consensus_13f: 'thirteenf',
  notable_fund_new_13f: 'thirteenf',
  buyback_8k: 'eightk',
  ceo_cfo_exit_8k: 'eightk',
  bankruptcy_8k: 'eightk',
  auditor_change_8k: 'eightk',
  late_filing_nt: 'eightk',
  short_crowded: 'short',
  squeeze_setup: 'short',
  ftd_persistent: 'short',
}

export function SourceGlyph({ source, ...props }: IconProps & { source: Source | (string & {}) }) {
  if (source === 'form144') return <NoticeGlyph {...props} />
  if (source === 'thirteenf') return <FundGlyph {...props} />
  if (source === 'eightk') return <ReportGlyph {...props} />
  if (source === 'short') return <ShortGlyph {...props} />
  if (source === 'news') return <NewsGlyph {...props} />
  return <ClusterGlyph {...props} />
}

export function SignalGlyph({ type, ...props }: IconProps & { type: SignalType }) {
  if (type === 'cluster_buy') return <ClusterGlyph {...props} />
  if (type === 'big_officer_buy') return <OfficerGlyph {...props} />
  const source = SOURCE_OF_TYPE[type]
  if (source) return <SourceGlyph source={source} {...props} />
  return <StakeGlyph {...props} />
}

export function ExternalIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13.5 5H19v5.5M19 5l-8 8M10 6.5H6.5A1.5 1.5 0 0 0 5 8v9.5A1.5 1.5 0 0 0 6.5 19H16a1.5 1.5 0 0 0 1.5-1.5V14" />
    </Svg>
  )
}

export function PlayIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 5.5v13l10.5-6.5L8 5.5Z" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function PauseIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8.5 5.5v13M15.5 5.5v13" strokeWidth={3} />
    </Svg>
  )
}

export function RewindIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M11.5 6 4 12l7.5 6V6ZM20 6l-7.5 6 7.5 6V6Z" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function CrossIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 6l12 12M18 6 6 18" strokeWidth={2.5} />
    </Svg>
  )
}

export function CheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m5 12.5 4.5 4.5L19 7.5" strokeWidth={2.5} />
    </Svg>
  )
}

const KIND_SHAPES: Record<string, string> = {
  buy: 'M12 5l7 12H5l7-12Z', // triangle pointing up
  sale: 'M12 19 5 7h14l-7 12Z', // triangle pointing down
  new_13d: 'M12 4l8 8-8 8-8-8 8-8Z', // diamond
  amended_13d: 'M12 6l6 6-6 6-6-6 6-6Z',
}

/** Shape that goes with each filing kind on the tape (color never stands alone). */
export function KindGlyph({ kind, ...props }: IconProps & { kind: FilingKind }) {
  const path = KIND_SHAPES[kind]
  if (!path) {
    return (
      <Svg {...props}>
        <circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none" />
      </Svg>
    )
  }
  return (
    <Svg {...props}>
      <path d={path} fill={kind === 'amended_13d' ? 'none' : 'currentColor'} stroke={kind === 'amended_13d' ? 'currentColor' : 'none'} />
    </Svg>
  )
}
