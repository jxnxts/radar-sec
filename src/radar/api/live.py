"""LIVE engine: runs the monitor cycle in the background and publishes what happens."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any

from radar.alerts import build_alerters
from radar.api import hub as events
from radar.api.hub import Hub
from radar.api.ranking import WINDOWS, build_ranking
from radar.api.views import filing_view, logo_url, price_symbol, signal_view
from radar.config import Settings
from radar.db import NEW, Database
from radar.edgar import normalize_cik
from radar.funds import FUND_EXCLUDED_TYPES, is_fund
from radar.http import SecClient, cache_path_for
from radar.models import FilingRef, Signal
from radar.sectors import UNKNOWN, SectorLookup, sector_for_sic
from radar.sources.base import MarketEvent
from radar.sources.runner import build_runner
from radar.sources.store import SourceStore
from radar.sources.views import company_context, event_view
from radar.summary import Summarizer
from radar.tickers import TICKERS_URL
from radar.watch import Watcher, WatchListener, WatchResult

log = logging.getLogger(__name__)

FEED_DAYS = 30
FEED_LIMIT = 60
TAPE_LIMIT = 60
TRACKED_DAYS = 14
TRACKED_LIMIT = 20
CHART_DAYS_BEFORE = 180

WatcherFactory = Callable[[Database, WatchListener], Watcher]


class LiveEngine:
    """Owner of the live collection.

    Collection runs in its own thread, with its own SQLite connection. The API
    reads through another connection, guarded by a lock; WAL mode lets both coexist.
    """

    mode = "live"

    def __init__(
        self,
        settings: Settings,
        hub: Hub,
        *,
        interval: float = 60.0,
        alerts: list[str] | None = None,
        watcher_factory: WatcherFactory | None = None,
        today: Callable[[], date] = date.today,
    ):
        self.settings = settings
        self.hub = hub
        self.interval = interval
        self._alerts = alerts
        self._factory = watcher_factory or self._default_factory
        self._today = today
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-collect")
        self._reader = Database(settings.db_path, check_same_thread=False)
        self._read_lock = threading.Lock()
        self._watcher: Watcher | None = None
        self._events: SourceStore | None = None
        self._client: SecClient | None = None
        self._sectors: SectorLookup | None = None
        self._stop: asyncio.Event | None = None
        self._closed = False
        # CIK → current ticker in the SEC registry: only confirmed tickers get a logo.
        self._tickers: dict[str, str] = self._cached_tickers()

        self._state = "starting"
        self._stage = "idle"
        self._pending = 0
        self._cycles = 0
        self._last_cycle_at: datetime | None = None
        self._last_cycle_ms: int | None = None
        self._next_cycle_at: datetime | None = None
        self._last_result: dict[str, int] | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------- collection

    def _default_factory(self, db: Database, listener: WatchListener) -> Watcher:
        client = SecClient(self.settings.cache_dir, config=self.settings.sec)
        return Watcher(
            self.settings,
            db,
            client,
            build_alerters(self._alerts, lang=self.settings.lang),
            Summarizer(db, self.settings.ai, lang=self.settings.lang),
            listener=listener,
            sources=build_runner(self.settings, db, client),
        )

    def _cached_tickers(self) -> dict[str, str]:
        """The ticker map the monitor already downloaded in another run, if any."""
        import json

        path = cache_path_for(self.settings.cache_dir, TICKERS_URL)
        try:
            data = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return {}
        tickers: dict[str, str] = {}
        try:
            for item in data.values():
                tickers.setdefault(normalize_cik(item["cik_str"]), item["ticker"])
        except (AttributeError, KeyError, TypeError):
            return {}
        return tickers

    def _logo_ok(self, cik: str, ticker: str) -> bool:
        current = self._tickers.get(normalize_cik(cik), "")
        return bool(current) and price_symbol(current) == price_symbol(ticker)

    def _setup(self) -> None:
        """Creates the monitor in the collection thread (which owns its SQLite connection)."""
        if self._watcher is not None:
            return
        db = Database(self.settings.db_path)
        self._watcher = self._factory(db, _Listener(self))
        self._client = self._watcher.client
        # One SIC cache per process: the monitor's (it also decides what is a fund).
        self._sectors = getattr(self._watcher, "sectors", None) or SectorLookup(self._client)
        had_tickers = bool(self._tickers)
        self._tickers = dict(self._watcher.tickers._load()) or self._tickers
        if self._tickers and not had_tickers:
            # First run on this machine: now the logos can be confirmed.
            self.hub.publish_threadsafe(events.FEED_RESET, self.snapshot())

    def _cycle(self) -> WatchResult:
        self._setup()
        assert self._watcher is not None
        result = self._watcher.run_once()
        self._fill_sectors()
        return result

    def _fill_sectors(self, limit: int = 40) -> None:
        assert self._watcher is not None and self._sectors is not None
        db = self._watcher.db
        since = self._today() - timedelta(days=max(WINDOWS) + 15)
        for cik in db.issuers_without_sector(since, limit):
            found = self._sectors.profile(cik)
            if found is not None:
                db.set_sector(cik, found.sic, sector_for_sic(found.sic), found.investment_company)
        self._sectors.flush()

    def _sector_now(self, cik: str) -> str:
        """The issuer's sector, asking the SEC if needed. Collection thread only."""
        if not cik or self._watcher is None or self._sectors is None:
            return ""
        db = self._watcher.db
        sector = db.sector_of(cik)
        if sector is None:
            found = self._sectors.lookup(cik)
            if found is None:
                return ""
            db.set_sector(cik, *found)
            sector = found[1]
        return sector

    def run_cycle(self) -> WatchResult:
        """Runs one cycle in the collection thread and waits for the result (used by tests)."""
        return self._executor.submit(self._cycle).result()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        while not self._stop.is_set():
            started = time.monotonic()
            self._state, self._next_cycle_at = "collecting", None
            self._publish_status()
            try:
                result = await loop.run_in_executor(self._executor, self._cycle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad cycle does not bring the server down
                log.exception("collection cycle failed; moving on to the next one")
                self._state, self._last_error = "error", f"{exc.__class__.__name__}: {exc}"[:300]
            else:
                self._record(result)
            elapsed = time.monotonic() - started
            self._cycles += 1
            self._stage, self._pending = "idle", 0
            self._last_cycle_at = datetime.now(UTC)
            self._last_cycle_ms = int(elapsed * 1000)
            wait = max(1.0, self.interval - elapsed)
            self._next_cycle_at = self._last_cycle_at + timedelta(seconds=wait)
            self._publish_status()
            self.hub.publish(events.RANKING_UPDATE, self.rankings())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    def _record(self, result: WatchResult) -> None:
        self._last_result = {
            "seen": result.seen,
            "new_filings": result.new_filings,
            "processed": result.processed,
            "backfilled": result.backfilled,
            "errors": result.errors,
            "signals": len(result.signals),
        }
        # Isolated errors (a slow feed, an unreadable filing) do not stop collection.
        self._state = "ok"
        self._last_error = None
        log.info(
            "collection: %d new filings of %d in the feed, %d processed, %d signals, %d errors",
            result.new_filings,
            result.seen,
            result.processed,
            len(result.signals),
            result.errors,
        )

    def _publish_status(self) -> None:
        self.hub.publish_threadsafe(events.SYSTEM_STATUS, self.status())

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop()
        # The collection SQLite connection can only be closed by the thread that created it.
        try:
            self._executor.submit(self._teardown).result(timeout=30)
        except Exception:
            log.exception("failed to shut down collection")
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._read_lock:
            self._reader.close()

    def _teardown(self) -> None:
        if self._watcher is not None:
            if self._sectors is not None:
                self._sectors.flush()
            self._watcher.db.close()
            self._watcher.client.close()

    # ----------------------------------------------------------------- reading

    def _hidden(self, signal: Signal) -> bool:
        """Insider buy signals of funds stored before the exclusion existed (or while the
        SEC registry was not answering) stay in the database but off the dashboard.
        Call with the read lock held."""
        if signal.type not in FUND_EXCLUDED_TYPES:
            return False
        stored = self._reader.issuer_profile(signal.issuer_cik) if signal.issuer_cik else None
        sic, investment_company = stored or (None, None)
        return is_fund(signal.issuer_name, sic, investment_company, self.settings.signals)

    def _visible(self, signals: list[Signal]) -> list[Signal]:
        return [s for s in signals if not self._hidden(s)]

    def _view(self, signal: Signal, sector: str | None = None) -> dict[str, Any]:
        if sector is None:
            sector = self._reader.sector_of(signal.issuer_cik) or "" if signal.issuer_cik else ""
        return signal_view(
            signal,
            signal_id=f"l{signal.id}",
            mode=self.mode,
            sector=sector or "",
            logo=self._logo_ok(signal.issuer_cik, signal.ticker),
            cached_ai=self._reader.cached_ai_summaries(signal.trigger_accession, signal.type),
        )

    def list_signals(
        self,
        *,
        limit: int = FEED_LIMIT,
        since: date | None = None,
        signal_type: str | None = None,
    ) -> list[dict[str, Any]]:
        since = since or self._today() - timedelta(days=FEED_DAYS)
        with self._read_lock:
            signals = self._visible(self._reader.list_signals(since=since, signal_type=signal_type))
            signals.sort(key=lambda s: (s.signal_date, s.id or 0), reverse=True)
            return [self._view(s) for s in signals[:limit]]

    def list_filings(self, limit: int = TAPE_LIMIT) -> list[dict[str, Any]]:
        with self._read_lock:
            return [filing_view(b) for b in self._reader.recent_filings(limit)]

    def signal_detail(self, signal_id: str) -> dict[str, Any] | None:
        if not signal_id.startswith("l") or not signal_id[1:].isdigit():
            return None
        with self._read_lock:
            signal = self._reader.get_signal(int(signal_id[1:]))
            if signal is None or self._hidden(signal):
                return None
            view = self._view(signal)
            cik = signal.issuer_cik
            purchases = self._reader.issuer_purchases(cik) if cik else []
            others = self._visible(self._reader.issuer_signals(cik)) if cik else []
            previous = [self._view(s) for s in others if s.id != signal.id]
        today = self._today()
        return {
            **view,
            "purchases": purchases,
            "previous_signals": previous,
            "chart": {
                "symbol": view["symbol"],
                "start": (signal.signal_date - timedelta(days=CHART_DAYS_BEFORE)).isoformat(),
                "end": today.isoformat(),
            },
        }

    def company(self, cik: str) -> dict[str, Any] | None:
        with self._read_lock:
            signals = self._visible(self._reader.issuer_signals(cik))
            purchases = self._reader.issuer_purchases(cik)
            sector = self._reader.sector_of(cik) or UNKNOWN
            views = [self._view(s, sector) for s in signals]
        if not signals and not purchases:
            return None
        ticker = views[0]["ticker"] if views else ""
        name = views[0]["company"] if views else ""
        return {
            "cik": cik,
            "name": name,
            "ticker": ticker,
            "symbol": price_symbol(ticker),
            "sector": sector,
            "logo": logo_url(ticker) if self._logo_ok(cik, ticker) else None,
            "signals": views,
            "purchases": purchases,
        }

    def ranking(self, days: int) -> dict[str, Any]:
        today = self._today()
        with self._read_lock:
            rows = self._reader.purchase_totals(today - timedelta(days=days))
            profiles = self._reader.issuer_profiles()
            first = self._reader.first_seen()
        # Funds are not ranked either: their directors' buying is not an insider bet.
        cfg = self.settings.signals
        rows = [
            r for r in rows if not is_fund(r["name"], *profiles.get(r["cik"], (None, None)), cfg)
        ]
        for row in rows:
            row["logo_ok"] = self._logo_ok(row["cik"], row["ticker"])
        return build_ranking(
            rows,
            days=days,
            as_of=today,
            basis="open_market_buys",
            coverage_since=first.date().isoformat() if first else None,
        )

    def rankings(self) -> dict[str, Any]:
        return {str(days): self.ranking(days) for days in WINDOWS}

    def tracked_tickers(self) -> list[str]:
        since = self._today() - timedelta(days=TRACKED_DAYS)
        with self._read_lock:
            signals = self._visible(self._reader.list_signals(since=since))
        symbols: list[str] = []
        for signal in sorted(signals, key=lambda s: (s.signal_date, s.id or 0), reverse=True):
            symbol = price_symbol(signal.ticker)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols[:TRACKED_LIMIT]

    def snapshot(self) -> dict[str, Any]:
        return {
            "signals": self.list_signals(),
            "filings": self.list_filings(),
            "ranking": self.rankings(),
            "market_events": self.list_events(),
        }

    # ------------------------------------------------------- extra sources

    def _source_store(self) -> SourceStore:
        """The source tables over the read connection (call with the read lock held)."""
        if self._events is None:
            self._events = SourceStore(self._reader.conn)
        return self._events

    def list_events(
        self, *, limit: int = TAPE_LIMIT, source: str | None = None, since: date | None = None
    ) -> list[dict[str, Any]]:
        with self._read_lock:
            rows = self._source_store().recent_events(limit=limit, source=source, since=since)
        return [event_view(row) for row in rows]

    def company_context(self, cik: str) -> dict[str, Any]:
        """Everything the radar knows about one company, across all sources."""
        with self._read_lock:
            signals = self._visible(self._reader.issuer_signals(cik))
            purchases = self._reader.issuer_purchases(cik)[:40]
            ticker = next((s.ticker for s in signals if s.ticker), "") or self._tickers.get(cik, "")
            context = company_context(self._source_store(), cik, ticker, today=self._today())
            views = [self._view(s) for s in signals]
        return {**context, "ticker": ticker, "signals": views, "insiders": purchases}

    def status(self) -> dict[str, Any]:
        ai = self.settings.ai
        with self._read_lock:
            used = self._reader.ai_calls_last_hour()
            totals = {
                "signals": self._reader.count_signals(),
                "filings": self._reader.count_filings(),
            }
            pending = self._reader.count_pending()
        if not ai.enabled:
            ai_state = "off"
        elif used >= ai.max_calls_per_hour:
            ai_state = "capped"
        else:
            ai_state = "ok"
        return {
            "mode": self.mode,
            "sec": {
                "state": self._state,
                "stage": self._stage,
                "interval_s": self.interval,
                "cycles": self._cycles,
                "last_cycle_at": _iso(self._last_cycle_at),
                "last_cycle_ms": self._last_cycle_ms,
                "next_cycle_at": _iso(self._next_cycle_at),
                "last": self._last_result,
                "last_error": self._last_error,
                "requests": self._client.requests_made if self._client else 0,
            },
            "queue": {"pending": max(pending, self._pending)},
            "ai": {
                "enabled": ai.enabled,
                "model": ai.model,
                "used_last_hour": used,
                "cap_per_hour": ai.max_calls_per_hour,
                "state": ai_state,
                "lang": self.settings.lang,
            },
            "totals": totals,
            "replay": None,
            "sources": self._watcher.sources.statuses()
            if self._watcher is not None and self._watcher.sources is not None
            else [],
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


class _Listener:
    """Receives the monitor's notices (in the collection thread) and publishes them to the hub."""

    def __init__(self, engine: LiveEngine):
        self.engine = engine

    def stage(self, name: str, pending: int) -> None:
        self.engine._stage, self.engine._pending = name, pending
        self.engine._publish_status()

    def filing(self, ref: FilingRef) -> None:
        engine = self.engine
        engine._pending = max(0, engine._pending - 1)
        assert engine._watcher is not None
        brief = engine._watcher.db.filing_brief(ref.accession)
        if brief is not None and brief["status"] != NEW:
            engine.hub.publish_threadsafe(events.FILING_NEW, filing_view(brief))

    def market_event(self, event_id: int, event: MarketEvent) -> None:
        row = {
            "id": event_id,
            "source": event.source,
            "kind": event.kind,
            "date": event.event_date.isoformat(),
            "cik": event.issuer_cik,
            "company": event.issuer_name,
            "ticker": event.ticker,
            "title": event.title,
            "data": event.data,
            "url": event.url,
            "seen_at": (event.seen_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        }
        self.engine.hub.publish_threadsafe(events.MARKET_EVENT_NEW, event_view(row))

    def signal(self, signal: Signal) -> None:
        engine = self.engine
        view = signal_view(
            signal,
            signal_id=f"l{signal.id}",
            mode=engine.mode,
            sector=engine._sector_now(signal.issuer_cik),
            logo=engine._logo_ok(signal.issuer_cik, signal.ticker),
            cached_ai=engine._watcher.db.cached_ai_summaries(signal.trigger_accession, signal.type)
            if engine._watcher
            else None,
        )
        engine.hub.publish_threadsafe(events.SIGNAL_NEW, view)
