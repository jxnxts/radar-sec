import { useEffect, useMemo, useRef } from 'react'
import { useI18n } from '../i18n'
import { useNow } from '../lib/hooks'
import { isFresh, usePanel } from '../store'
import type { SignalType } from '../types'
import { Panel } from './Panel'
import { SignalCard } from './SignalCard'

const FILTERS: Array<SignalType | 'all'> = ['all', 'cluster_buy', 'big_officer_buy', 'activist_13d']

export function SignalFeed() {
  const { t } = useI18n()
  const signals = usePanel((s) => s.signals)
  const arrivals = usePanel((s) => s.arrivals)
  const quotes = usePanel((s) => s.quotes)
  const selectedId = usePanel((s) => s.selectedId)
  const pinnedUntil = usePanel((s) => s.pinnedUntil)
  const filter = usePanel((s) => s.filter)
  const mode = usePanel((s) => s.mode)
  const select = usePanel((s) => s.select)
  const follow = usePanel((s) => s.follow)
  const setFilter = usePanel((s) => s.setFilter)
  const now = useNow(1000)
  const list = useRef<HTMLOListElement>(null)

  const visible = useMemo(
    () => (filter === 'all' ? signals : signals.filter((s) => s.type === filter)),
    [signals, filter],
  )
  const newest = signals[0]
  const newestFresh = newest ? isFresh(arrivals, newest.id, now) : false
  const pinned = pinnedUntil > now

  // New signal on top: scroll the list back up, unless the operator is reading another one.
  useEffect(() => {
    if (!pinned && list.current) list.current.scrollTop = 0
  }, [newest?.id, pinned])

  const announcement =
    newest && newestFresh ? t.feed.announce(newest.symbol || newest.company, t.signalType.short[newest.type]) : ''

  return (
    <Panel
      index="01"
      title={t.feed.title}
      labelledBy="feed-title"
      className={`feed${newestFresh ? ' feed--alert' : ''}`}
      aside={
        <div className="filters" role="group" aria-label={t.feed.filterGroup}>
          {FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              className="chip"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {id === 'all' ? t.feed.all : t.signalType.tiny[id]}
            </button>
          ))}
        </div>
      }
    >
      <div className="feed__status">
        <span>
          {t.feed.count(visible.length)}
          {mode === 'replay' ? t.feed.replayTime : t.feed.last30}
        </span>
        <button
          type="button"
          className="follow"
          aria-pressed={!pinned}
          onClick={follow}
          title={pinned ? t.feed.pinnedTitle : t.feed.followingTitle}
        >
          <span className="follow__dot" aria-hidden="true" />
          {pinned ? t.feed.pinned(Math.ceil((pinnedUntil - now) / 1000)) : t.feed.following}
        </button>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      {visible.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t.feed.emptyTitle}</p>
          <p>{filter === 'all' ? t.feed.emptyAll : t.feed.emptyFiltered}</p>
        </div>
      ) : (
        <ol className="feed__list" ref={list}>
          {visible.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              quote={signal.symbol ? quotes[signal.symbol] : undefined}
              selected={signal.id === selectedId}
              fresh={isFresh(arrivals, signal.id, now)}
              now={now}
              onSelect={select}
            />
          ))}
        </ol>
      )}
    </Panel>
  )
}
