interface SparklineProps {
  values: number[]
  /** Reference line (previous close). */
  baseline?: number | null
  width?: number
  height?: number
}

/** Tiny SVG line chart. Decorative: the number next to it carries the information. */
export function Sparkline({ values, baseline, width = 96, height = 28 }: SparklineProps) {
  if (values.length < 2) return <svg className="spark" viewBox={`0 0 ${width} ${height}`} aria-hidden="true" />
  const all = baseline != null ? [...values, baseline] : values
  const min = Math.min(...all)
  const max = Math.max(...all)
  const range = max - min || 1
  const pad = 2
  const x = (index: number) => (index / (values.length - 1)) * width
  const y = (value: number) => pad + (1 - (value - min) / range) * (height - pad * 2)
  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const last = values[values.length - 1] ?? 0
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {baseline != null ? (
        <line className="spark__base" x1="0" x2={width} y1={y(baseline)} y2={y(baseline)} />
      ) : null}
      <path className="spark__area" d={`${line} L${width} ${height} L0 ${height} Z`} />
      <path className="spark__line" d={line} />
      <circle className="spark__dot" cx={width - 1.5} cy={y(last)} r="1.8" />
    </svg>
  )
}
