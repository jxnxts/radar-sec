import { useI18n } from '../i18n'
import { ARROWS, direction } from '../lib/format'

interface DeltaProps {
  value: number | null | undefined
  digits?: number
  className?: string
}

/** Percentage change with arrow and sign: direction never depends on color alone. */
export function Delta({ value, digits = 1, className = '' }: DeltaProps) {
  const { f } = useI18n()
  const dir = direction(value)
  return (
    <span className={`delta delta--${dir} ${className}`}>
      <span className="delta__arrow" aria-hidden="true">
        {ARROWS[dir]}
      </span>
      {f.pct(value, digits)}
    </span>
  )
}
