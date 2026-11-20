"""News in live mode: press-release wires, GDELT and (with a key) Tiingo.

Each feed has its own pace. Every new item is stored in `news_items` and handed to
the forward-test log with its `seen_at`; the items that name a listed company also
become market events (tape and company context). Nothing here fires a signal.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from radar.config import NewsConfig, tiingo_api_key

from ..base import NEWS, MarketEvent, PollResult
from .client import NewsClient, NewsHttpError
from .feeds import (
    WIRES,
    FeedFormatError,
    Wire,
    gdelt_url,
    parse_gdelt,
    parse_rss,
    parse_tiingo,
    tiingo_url,
)
from .matching import CompanyIndex, match_companies
from .model import NewsItem, normalize_title
from .scoring import NewsScorer
from .tags import tag

log = logging.getLogger(__name__)

EVENT_SUMMARY_MAX = 300
MIN_TITLE_FOR_DEDUPE = 20  # shorter headlines ("Press release") are not deduped by title


class Feed:
    """One input of the news source, polled at its own interval."""

    name: str = ""
    interval_s: float = 300.0
    # HTTP answers that mean "this key will never get in" (not "try later"): the feed
    # is turned off for the rest of the session instead of retried.
    disable_on: frozenset[int] = frozenset()

    def fetch(self, client: NewsClient) -> list[NewsItem]:
        raise NotImplementedError


class WireFeed(Feed):
    def __init__(self, wire: Wire, interval_s: float):
        self.wire = wire
        self.name = wire.name
        self.interval_s = interval_s

    def fetch(self, client: NewsClient) -> list[NewsItem]:
        content = client.get(self.wire.url, robots=True)
        if content is None:  # 304: nothing new since the last poll
            return []
        items = parse_rss(content, self.wire.name)
        if self.wire.url_must_contain:
            items = [i for i in items if self.wire.url_must_contain in i.url]
        return items


class GdeltFeed(Feed):
    name = "gdelt"

    def __init__(self, query: str, max_records: int, interval_s: float):
        self.query = query
        self.max_records = max_records
        self.interval_s = interval_s
        # Look back twice the interval (at least the 1 hour GDELT accepts); dedupe
        # removes the overlap.
        self.timespan = f"{max(1, math.ceil(2 * interval_s / 3600))}h"

    def fetch(self, client: NewsClient) -> list[NewsItem]:
        url = gdelt_url(self.query, max_records=self.max_records, timespan=self.timespan)
        return parse_gdelt(client.get(url, conditional=False) or b"")


class TiingoFeed(Feed):
    name = "tiingo"
    # 401: bad key; 403: the plan has no News API access ("You do not have permission").
    disable_on = frozenset({401, 403})

    def __init__(self, api_key: str, interval_s: float, limit: int = 100):
        if not api_key:
            raise ValueError("Tiingo needs TIINGO_API_KEY")
        self._key = api_key
        self.interval_s = interval_s
        self.limit = limit

    def fetch(self, client: NewsClient) -> list[NewsItem]:
        content = client.get(
            tiingo_url(limit=self.limit),
            headers={"Authorization": f"Token {self._key}", "Content-Type": "application/json"},
            conditional=False,
        )
        return parse_tiingo(content or b"[]")


def build_feeds(config: NewsConfig, tiingo_key: str | None = None) -> list[Feed]:
    feeds: list[Feed] = []
    for name in config.wires:
        wire = WIRES.get(name)
        if wire is None:
            raise ValueError(f"unknown news wire '{name}' (known: {', '.join(WIRES)})")
        feeds.append(WireFeed(wire, config.interval_seconds))
    if config.gdelt:
        feeds.append(
            GdeltFeed(config.gdelt_query, config.gdelt_max_records, config.gdelt_interval_seconds)
        )
    key = tiingo_api_key() if tiingo_key is None else tiingo_key
    if key:
        feeds.append(TiingoFeed(key, config.tiingo_interval_seconds))
    return feeds


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat(timespec="seconds") if moment else None


class NewsSource:
    name = NEWS

    def __init__(
        self,
        config: NewsConfig | None = None,
        *,
        client: NewsClient | None = None,
        feeds: list[Feed] | None = None,
        tiingo_key: str | None = None,
        scorer: NewsScorer | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.config = config or NewsConfig()
        self.client = client or NewsClient(
            user_agent=self.config.user_agent,
            min_host_interval=self.config.min_host_interval_seconds,
            timeout=self.config.timeout_seconds,
        )
        self.feeds = feeds if feeds is not None else build_feeds(self.config, tiingo_key)
        self.interval_s = min(
            (f.interval_s for f in self.feeds), default=self.config.interval_seconds
        )
        self.scorer = scorer
        self._clock = clock
        self._now = now
        self._next: dict[str, float] = {f.name: 0.0 for f in self.feeds}
        # Per-feed state for /api/health: waiting | ok | error | disabled.
        self._state: dict[str, dict[str, Any]] = {
            f.name: {"state": "waiting", "error": None, "last_ok_at": None} for f in self.feeds
        }
        self._index: CompanyIndex | None = None
        self._index_of: int | None = None

    def close(self) -> None:
        self.client.close()

    def index(self, ctx) -> CompanyIndex | None:
        registry = getattr(ctx, "registry", None)
        if registry is None:
            return None
        if self._index is None or self._index_of != id(registry):
            self._index, self._index_of = CompanyIndex(registry), id(registry)
        return self._index

    def due(self) -> list[Feed]:
        now = self._clock()
        return [
            f
            for f in self.feeds
            if self._state[f.name]["state"] != "disabled" and self._next.get(f.name, 0.0) <= now
        ]

    def _disable(self, feed: Feed, exc: NewsHttpError) -> None:
        reason = f"HTTP {exc.status_code}"
        if exc.detail:
            reason += f": {exc.detail}"
        self._state[feed.name] = {
            **self._state[feed.name],
            "state": "disabled",
            "error": reason,
        }
        log.warning(
            "news feed %s disabled for this session (%s); restart the radar after the "
            "plan or key changes",
            feed.name,
            reason,
        )

    def health(self) -> dict[str, Any]:
        """State of each feed, for /api/health (a disabled feed says why)."""
        return {
            "feeds": [
                {"name": f.name, "interval_s": f.interval_s, **self._state[f.name]}
                for f in self.feeds
            ]
        }

    def poll(self, ctx) -> PollResult:
        result = PollResult()
        index = self.index(ctx)
        errors: list[str] = []
        fetched = 0
        due = self.due()
        for feed in due:
            try:
                items = feed.fetch(self.client)
            except NewsHttpError as exc:
                if exc.status_code in feed.disable_on:
                    self._disable(feed, exc)
                    continue
                self._failed(feed, exc, errors)
                continue
            except FeedFormatError as exc:
                self._failed(feed, exc, errors)
                continue
            finally:
                self._next[feed.name] = self._clock() + feed.interval_s
            fetched += 1
            seen_at = self._now()
            self._state[feed.name] = {
                "state": "ok",
                "error": None,
                "last_ok_at": _iso(seen_at),
            }
            # Feeds list the newest first; store the oldest first.
            for item in reversed(items):
                self._take(ctx, index, item, seen_at, result)
        result.requests = len(due)
        if errors and not fetched:
            raise RuntimeError("; ".join(errors)[:300])
        matched = sum(1 for r in result.records if r["data"]["tickers"])
        note = f"{len(result.records)} new items, {matched} matched"
        if index is None or not len(index):
            note += "; SEC ticker list unavailable, nothing matched"
        if errors:
            note += f"; {'; '.join(errors)}"
        disabled = [n for n, st in self._state.items() if st["state"] == "disabled"]
        if disabled:
            note += f"; off for this session: {', '.join(disabled)}"
        result.note = note[:300]
        return result

    def _failed(self, feed: Feed, exc: Exception, errors: list[str]) -> None:
        log.warning("news feed %s: %s", feed.name, exc)
        errors.append(f"{feed.name}: {exc}")
        self._state[feed.name] = {**self._state[feed.name], "state": "error", "error": str(exc)}

    def _take(
        self,
        ctx,
        index: CompanyIndex | None,
        item: NewsItem,
        seen_at: datetime,
        result: PollResult,
    ) -> None:
        store = ctx.store
        key, canonical = item.key, item.canonical_url
        title_key = (
            item.title_hash if len(normalize_title(item.title)) >= MIN_TITLE_FOR_DEDUPE else key
        )
        if store.news_seen(key, canonical, title_key):
            return
        matches = (
            match_companies(index, item.title, item.summary, item.provider_tickers)
            if index is not None
            else []
        )
        record: dict[str, Any] = {
            "key": key,
            "feed": item.feed,
            "url": item.url,
            "canonical_url": canonical,
            "title": item.title,
            "title_hash": title_key,
            "summary": item.summary,
            "published_at": _iso(item.published_at),
            "published_raw": item.published_raw,
            "seen_at": _iso(seen_at),
            "tickers": [m.ticker for m in matches],
            "ciks": [m.cik for m in matches],
            "matches": [m.view() for m in matches],
            "tags": tag(item.title, item.summary),
            "extra": item.extra,
            "score": None,
        }
        if self.scorer is not None:
            try:
                record["score"] = self.scorer.score(record)
            except Exception:  # noqa: BLE001 - a broken scorer never loses the item
                log.exception("news scorer %s failed", getattr(self.scorer, "name", "?"))
        if not store.add_news(record):
            return
        result.records.append(
            {
                "kind": "news",
                "source": item.feed,  # per feed, so the log counts each one
                "key": key,
                "seen_at": record["seen_at"],
                "data": record,
            }
        )
        if not matches:
            return
        published = item.published_at
        day = min(published, seen_at).date() if published else seen_at.date()
        summary = item.summary
        if len(summary) > EVENT_SUMMARY_MAX:
            summary = summary[: EVENT_SUMMARY_MAX - 1].rstrip() + "…"
        # One event per company named, so each one's context shows the item.
        for match in matches:
            result.events.append(
                MarketEvent(
                    source=NEWS,
                    kind="news",
                    key=f"{key}:{match.cik}",
                    event_date=day,
                    issuer_cik=match.cik,
                    issuer_name=match.name,
                    ticker=match.ticker,
                    title=item.title,
                    url=item.url,
                    seen_at=seen_at,
                    data={
                        "feed": item.feed,
                        "news_key": key,
                        "summary": summary,
                        "tags": record["tags"],
                        "method": match.method,
                        "matches": record["matches"],
                        "published_at": record["published_at"],
                    },
                )
            )
