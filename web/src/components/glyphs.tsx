// Dashboard icons, drawn here (no icon library and no third-party images).

import type { SVGProps } from 'react'
import type { FilingKind, SignalType } from '../types'

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

export function SignalGlyph({ type, ...props }: IconProps & { type: SignalType }) {
  if (type === 'cluster_buy') return <ClusterGlyph {...props} />
  if (type === 'big_officer_buy') return <OfficerGlyph {...props} />
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
