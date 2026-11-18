import { useI18n } from '../i18n'
import { postJSON } from '../lib/api'
import type { Mode, ReplayStatus } from '../types'
import { PauseIcon, PlayIcon, RewindIcon } from './glyphs'

interface ModeBadgeProps {
  mode: Mode | null
  replay: ReplayStatus | null
}

function control(body: Record<string, unknown>) {
  postJSON('/api/replay/control', body).catch((error) => console.error(error))
}

/**
 * LIVE and REPLAY must never be confused: the text, icon, badge shape and color all
 * change, and replay adds the hazard stripe at the top and the simulated date up front.
 */
export function ModeBadge({ mode, replay }: ModeBadgeProps) {
  const { t, f } = useI18n()
  if (mode === 'replay') {
    const years = replay ? `${replay.start.slice(0, 4)}–${replay.end.slice(0, 4)}` : ''
    const progress = replay && replay.total ? replay.position / replay.total : 0
    return (
      <div className="mode mode--replay" role="group" aria-label={t.mode.replayGroup}>
        <div className="mode__badge">
          <RewindIcon />
          <span>{t.mode.replay}</span>
        </div>
        <div className="mode__info">
          <span className="mode__date">{replay ? f.dateShort(replay.date, true) : '…'}</span>
          <span className="mode__sub">{t.mode.historical(years)}</span>
        </div>
        {replay ? (
          <div className="mode__controls">
            <button
              type="button"
              className="iconbtn"
              onClick={() => control({ paused: !replay.paused })}
              aria-label={replay.paused ? t.mode.resume : t.mode.pause}
              aria-pressed={replay.paused}
            >
              {replay.paused ? <PlayIcon /> : <PauseIcon />}
            </button>
            <div className="speed" role="group" aria-label={t.mode.speed}>
              {replay.speeds
                .filter((speed) => speed >= 1)
                .map((speed) => (
                  <button
                    key={speed}
                    type="button"
                    className="speed__btn"
                    aria-pressed={replay.speed === speed}
                    onClick={() => control({ speed })}
                  >
                    {speed}×
                  </button>
                ))}
            </div>
            <div
              className="mode__progress"
              role="progressbar"
              aria-label={t.mode.position}
              aria-valuemin={0}
              aria-valuemax={replay.total}
              aria-valuenow={replay.position}
              title={t.mode.progress(f.int(replay.position), f.int(replay.total))}
            >
              <span style={{ width: `${(progress * 100).toFixed(2)}%` }} />
            </div>
          </div>
        ) : null}
      </div>
    )
  }
  if (mode === 'live') {
    return (
      <div className="mode mode--live" role="group" aria-label={t.mode.liveGroup}>
        <div className="mode__badge">
          <span className="mode__lamp" aria-hidden="true" />
          <span>{t.mode.live}</span>
        </div>
        <div className="mode__info">
          <span className="mode__date">SEC · EDGAR</span>
          <span className="mode__sub">{t.mode.liveSub}</span>
        </div>
      </div>
    )
  }
  return (
    <div className="mode mode--idle" role="status">
      <div className="mode__badge">
        <span>{t.mode.connecting}</span>
      </div>
    </div>
  )
}
