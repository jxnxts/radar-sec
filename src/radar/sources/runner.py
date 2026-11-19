"""Live loop of the extra sources.

`SourceRunner.tick()` runs inside the collection thread of the live engine, after the
Form 4/13D cycle. Each source has its own interval; a source that fails is logged and
retried at its next turn without stopping the others.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from radar.backtest.datasets import normalize_symbol, quarters_between
from radar.backtest.marketcap import SharesOutstanding
from radar.edgar import normalize_cik
from radar.models import Signal

from . import explain as _explain  # noqa: F401 - registers the catalogs
from .base import MarketEvent, PollResult
from .eightk.live import EightKSource
from .form144.live import Form144Source
from .news.live import NewsSource
from .registry import Registry
from .short.data import CusipMap
from .short.history import FinraClient, build_cusip_map
from .short.live import ShortSource
from .store import SourceStore
from .thirteenf.live import ThirteenFSource

log = logging.getLogger(__name__)

ALL_SOURCES = ("form144", "eightk", "thirteenf", "short", "news")


@dataclass
class SourceContext:
    """What a source needs from the rest of the radar, behind plain callables."""

    client: Any  # SecClient
    store: SourceStore
    finra: FinraClient
    today: date
    ticker_for: Callable[[str], str]
    registrant: Callable[[str], tuple[str, str, str] | None]
    prior_signal_dates: Callable[[str, str], list[date]]
    momentum: Callable[[str, date], float | None]
    shares_outstanding: Callable[[str, date], float | None]
    resolve_cusip: Callable[[str, date], tuple[str, str, str] | None]
    # The SEC registry itself, for sources that match names and tickers (news).
    registry: Registry | None = None

    @staticmethod
    def parse_date(value: str) -> date:
        return date.fromisoformat(value)


@dataclass
class SourceStatus:
    name: str
    interval_s: float
    state: str = "waiting"  # waiting | ok | error | off
    last_run_at: datetime | None = None
    last_ms: int | None = None
    last_error: str | None = None
    events: int = 0
    signals: int = 0
    note: str = ""

    def view(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "interval_s": self.interval_s,
            "last_run_at": self.last_run_at.isoformat(timespec="seconds")
            if self.last_run_at
            else None,
            "last_ms": self.last_ms,
            "last_error": self.last_error,
            "events": self.events,
            "signals": self.signals,
            "note": self.note,
        }


@dataclass
class TickResult:
    events: list[tuple[int, MarketEvent]] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)


class SourceRunner:
    def __init__(
        self,
        conn,
        client,
        *,
        enabled: tuple[str, ...] = ALL_SOURCES,
        cache_dir=None,
        momentum: Callable[[str, date], float | None] | None = None,
        prior_signal_dates: Callable[[str, str], list[date]] | None = None,
        today: Callable[[], date] = date.today,
        sources: list | None = None,
        finra: FinraClient | None = None,
        news_config=None,
    ):
        self.store = SourceStore(conn)
        self.client = client
        self._cache_dir = cache_dir or client.cache_dir
        self._today = today
        self._momentum = momentum or (lambda ticker, day: None)
        self._prior = prior_signal_dates or (lambda kind, cik: [])
        self._finra = finra or FinraClient(self._cache_dir)
        catalog = {
            "form144": Form144Source,
            "eightk": EightKSource,
            "thirteenf": ThirteenFSource,
            "short": ShortSource,
            "news": lambda: NewsSource(news_config),
        }
        self.sources = (
            sources
            if sources is not None
            else [catalog[name]() for name in enabled if name in catalog]
        )
        self.status = {s.name: SourceStatus(s.name, s.interval_s) for s in self.sources}
        self._next: dict[str, float] = {s.name: 0.0 for s in self.sources}
        self._registry: Registry | None = None
        self._shares: SharesOutstanding | None = None
        self._cusips: CusipMap | None = None

    # ---------------------------------------------------------- reference data

    def registry(self) -> Registry:
        if self._registry is None:
            try:
                self._registry = Registry.load(self.client)
            except Exception as exc:  # noqa: BLE001 - the SEC may be down; retry later
                log.warning("SEC ticker list unavailable: %s", exc)
                return Registry({})
        return self._registry

    def shares(self) -> SharesOutstanding:
        if self._shares is None:
            today = self._today()
            self._shares = SharesOutstanding.load(
                self.client, quarters_between(today - timedelta(days=400), today)
            )
        return self._shares

    def cusips(self) -> CusipMap:
        if self._cusips is None:
            self._cusips = build_cusip_map(self._cache_dir)
        return self._cusips

    def resolve_cusip(self, cusip: str, day: date) -> tuple[str, str, str] | None:
        symbol = normalize_symbol(self.cusips().symbol(cusip))
        if not symbol:
            return None
        who = self.registry().registrant(symbol)
        return (symbol, who[0], who[2]) if who else (symbol, "", "")

    def context(self) -> SourceContext:
        registry = self.registry()
        return SourceContext(
            client=self.client,
            store=self.store,
            finra=self._finra,
            today=self._today(),
            ticker_for=lambda cik: registry.ticker_for(normalize_cik(cik)),
            registrant=registry.registrant,
            prior_signal_dates=self._prior,
            momentum=self._momentum,
            shares_outstanding=lambda cik, day: self.shares().as_of(cik, day),
            resolve_cusip=self.resolve_cusip,
            registry=registry,
        )

    # -------------------------------------------------------------------- loop

    def due(self, now: float | None = None) -> list:
        now = time.monotonic() if now is None else now
        return [s for s in self.sources if self._next.get(s.name, 0.0) <= now]

    def tick(
        self, *, force: bool = False, on_event: Callable[[int, MarketEvent], None] | None = None
    ) -> TickResult:
        """Poll the sources that are due; store their events and return the new ones."""
        out = TickResult()
        sources = self.sources if force else self.due()
        if not sources:
            return out
        ctx = self.context()
        for source in sources:
            status = self.status[source.name]
            started = time.monotonic()
            try:
                result: PollResult = source.poll(ctx)
            except Exception as exc:  # noqa: BLE001 - one bad source never stops the loop
                log.exception("source %s failed", source.name)
                status.state = "error"
                status.last_error = f"{exc.__class__.__name__}: {exc}"[:300]
            else:
                status.state = "ok"
                status.last_error = None
                status.note = result.note
                for event in result.events:
                    event_id = self.store.add_event(event)
                    if event_id is None:
                        continue
                    status.events += 1
                    out.events.append((event_id, event))
                    if on_event is not None:
                        on_event(event_id, event)
                status.signals += len(result.signals)
                out.signals += result.signals
            finally:
                status.last_ms = int((time.monotonic() - started) * 1000)
                status.last_run_at = datetime.now(UTC)
                self._next[source.name] = time.monotonic() + source.interval_s
        return out

    def statuses(self) -> list[dict[str, Any]]:
        return [s.view() for s in self.status.values()]

    def close(self) -> None:
        self._finra.close()
        for source in self.sources:
            closer = getattr(source, "close", None)
            if callable(closer):
                closer()


def yahoo_momentum(ticker: str, day: date, sessions: int = 10) -> float | None:
    """Adjusted return over the `sessions` sessions up to `day` (live `squeeze_setup`)."""
    try:
        import yfinance as yf

        frame = yf.download(
            ticker,
            start=(day - timedelta(days=sessions * 3)).isoformat(),
            end=(day + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception:  # noqa: BLE001 - no price, no squeeze signal
        return None
    if frame is None or frame.empty or len(frame) <= sessions:
        return None
    closes = frame["Close"].to_numpy().reshape(-1)
    return float(closes[-1] / closes[-1 - sessions] - 1.0)


def build_runner(settings, db, client) -> SourceRunner | None:
    """The live runner for `settings.sources.enabled`, on the radar database; None if off."""
    enabled = tuple(settings.sources.enabled)
    if not enabled:
        return None
    return SourceRunner(
        db.conn,
        client,
        enabled=enabled,
        cache_dir=settings.cache_dir,
        momentum=yahoo_momentum,
        prior_signal_dates=db.prior_signal_dates,
        news_config=settings.news,
    )
