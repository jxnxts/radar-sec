import { useI18n } from '../i18n'

interface ScoreRingProps {
  score: number
  size?: 'sm' | 'lg'
}

/** Score from 0 to 100 on an arc. Only a ranking heuristic: the backtest shows it does not predict returns. */
export function ScoreRing({ score, size = 'sm' }: ScoreRingProps) {
  const { t } = useI18n()
  const radius = 15
  const length = 2 * Math.PI * radius
  const filled = Math.max(0, Math.min(100, score)) / 100
  return (
    <span
      className={`score score--${size}`}
      title={t.score.title}
    >
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle className="score__track" cx="18" cy="18" r={radius} />
        <circle
          className="score__value"
          cx="18"
          cy="18"
          r={radius}
          strokeDasharray={`${(filled * length).toFixed(2)} ${length.toFixed(2)}`}
          transform="rotate(-90 18 18)"
        />
      </svg>
      <span className="score__number">{Math.round(score)}</span>
      <span className="sr-only">{t.score.outOf}</span>
    </span>
  )
}
