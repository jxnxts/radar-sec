import { useEffect } from 'react'
import { FilingTape } from './components/FilingTape'
import { RadarPanel } from './components/RadarPanel'
import { SignalDetail } from './components/SignalDetail'
import { SignalFeed } from './components/SignalFeed'
import { TopBar } from './components/TopBar'
import { applyDocumentLang, useI18n } from './i18n'
import { useNow } from './lib/hooks'
import { RadarSocket, socketUrl } from './lib/socket'
import { usePanel, visibleSignals } from './store'

function ConnectionBanner() {
  const connection = usePanel((s) => s.connection)
  const everConnected = usePanel((s) => s.everConnected)
  const now = useNow(1000)
  const { t, f } = useI18n()
  if (connection.state === 'open') return null
  const retry =
    connection.state === 'waiting' && connection.retryAt
      ? t.connection.retry(f.until(new Date(connection.retryAt).toISOString(), now))
      : t.connection.connecting
  return (
    <div className="banner" role="alert">
      <strong>{everConnected ? t.connection.lost : t.connection.never}</strong>{' '}
      {everConnected ? t.connection.stale : t.connection.hint} {retry}
    </div>
  )
}

export function App() {
  const mode = usePanel((s) => s.mode)
  const { t, lang } = useI18n()

  useEffect(() => applyDocumentLang(lang), [lang])

  useEffect(() => {
    const { receive, setConnection } = usePanel.getState()
    const socket = new RadarSocket({
      url: socketUrl(window.location),
      onMessage: receive,
      onState: setConnection,
    })
    socket.start()
    return () => socket.stop()
  }, [])

  // Up and down arrows step through the signals from anywhere on the screen.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      const target = event.target as HTMLElement | null
      if (target?.closest('input, select, textarea, .tablewrap')) return
      const state = usePanel.getState()
      const { selectedId, select } = state
      const list = visibleSignals(state)
      const index = list.findIndex((s) => s.id === selectedId)
      const next = list[index + (event.key === 'ArrowDown' ? 1 : -1)]
      if (!next) return
      event.preventDefault()
      select(next.id)
      document
        .querySelector(`[data-signal-id="${next.id}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className={`room room--${mode ?? 'idle'}`}>
      <a className="skip" href="#feed-title">
        {t.app.skipToSignals}
      </a>
      {mode === 'replay' ? <div className="hazard hazard--top" aria-hidden="true" /> : null}
      <TopBar />
      <ConnectionBanner />
      <main className="grid">
        <SignalFeed />
        <SignalDetail />
        <div className="side">
          <RadarPanel />
        </div>
      </main>
      <FilingTape />
    </div>
  )
}
