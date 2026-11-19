"""Forward-test log: an append-only, point-in-time record of everything seen live.

Every signal the radar stores, every market event of the extra sources, every news
item (matched or not) and a daily closing-price snapshot go to
`data/forward/YYYY-MM-DD.jsonl.gz`, one JSON record per line:

    {"v": 1, "kind": "signal" | "event" | "news" | "price", "source": "...",
     "key": "...", "seen_at": "2026-11-19T21:56:03+00:00", "data": {...}}

`seen_at` is the UTC moment the radar first had the information; the partition is the
UTC day of `seen_at`. Files are only ever opened in append mode: each write adds a new
gzip member (a concatenation of gzip members is a valid gzip file), so a past day is
never rewritten. A write cut short by a crash leaves at most a truncated last member,
which the reader skips.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
import zlib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from radar.backtest.datasets import normalize_symbol
from radar.models import Signal

log = logging.getLogger(__name__)

VERSION = 1
SUFFIX = ".jsonl.gz"
SIGNAL = "signal"
EVENT = "event"
NEWS = "news"
PRICE = "price"
PRICES_SOURCE = "prices"
SNAPSHOT_STATE = "forward.price_snapshot"
SNAPSHOT_LOOKBACK_DAYS = 7

PriceFetch = Callable[[list[str], date, date], tuple[dict[str, Any], dict[str, str]]]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _day_of(seen_at: str) -> date:
    moment = datetime.fromisoformat(seen_at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).date()


class ForwardLog:
    """Daily-partitioned gzipped JSONL files under `root`; append and read only."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    def partition(self, day: date) -> Path:
        return self.root / f"{day.isoformat()}{SUFFIX}"

    def append(self, records: Iterable[dict[str, Any]]) -> int:
        """Append records to the partition of each one's `seen_at` day; returns how many."""
        by_day: dict[date, list[str]] = {}
        for record in records:
            if not record.get("seen_at"):
                raise ValueError("a forward record needs seen_at")
            line = json.dumps({"v": VERSION, **record}, default=str, ensure_ascii=False)
            by_day.setdefault(_day_of(record["seen_at"]), []).append(line)
        if not by_day:
            return 0
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            for day, lines in sorted(by_day.items()):
                payload = ("\n".join(lines) + "\n").encode("utf-8")
                # "ab": a new gzip member at the end; existing bytes are never touched.
                with open(self.partition(day), "ab") as raw:
                    raw.write(gzip.compress(payload, mtime=0))
                    raw.flush()
                    os.fsync(raw.fileno())
        return sum(len(lines) for lines in by_day.values())

    def days(self) -> list[date]:
        if not self.root.exists():
            return []
        out = []
        for path in self.root.glob(f"*{SUFFIX}"):
            try:
                out.append(date.fromisoformat(path.name[: -len(SUFFIX)]))
            except ValueError:
                continue
        return sorted(out)

    def read(self, day: date) -> Iterator[dict[str, Any]]:
        """Records of one day, in write order; a truncated tail is skipped."""
        path = self.partition(day)
        if not path.exists():
            return
        data = path.read_bytes()
        while data:
            decoder = zlib.decompressobj(wbits=31)  # one gzip member
            try:
                chunk = decoder.decompress(data)
            except zlib.error:
                log.warning("forward log %s: unreadable data at the end, skipped", path.name)
                return
            if not decoder.eof:
                log.warning("forward log %s: truncated last write, skipped", path.name)
                return
            for line in chunk.decode("utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)
            data = decoder.unused_data

    def summary(
        self, since: date | None = None, until: date | None = None
    ) -> dict[date, Counter[str]]:
        """Records per source for each day (signals as "signal:<source>", etc.)."""
        out: dict[date, Counter[str]] = {}
        for day in self.days():
            if (since and day < since) or (until and day > until):
                continue
            counts: Counter[str] = Counter()
            for record in self.read(day):
                counts[f"{record.get('kind', '?')}:{record.get('source', '?')}"] += 1
            out[day] = counts
        return out


def signal_record(signal: Signal, seen_at: datetime, *, alerted: bool) -> dict[str, Any]:
    from radar.sources.specs import SPECS
    from radar.sources.views import source_of

    spec = SPECS.get(signal.type)
    data = asdict(signal)
    data.pop("summary", None)  # AI text, written after the fact
    data.pop("summary_source", None)
    data["direction"] = spec.direction if spec else "long"
    data["fresh"] = alerted
    return {
        "kind": SIGNAL,
        "source": source_of(signal.type),
        "key": signal.dedupe_key,
        "seen_at": _iso(seen_at),
        "data": data,
    }


def event_record(event_id: int, event: Any) -> dict[str, Any]:
    seen = event.seen_at or datetime.now(UTC)
    return {
        "kind": EVENT,
        "source": event.source,
        "key": event.key,
        "seen_at": _iso(seen),
        "data": {
            "id": event_id,
            "kind": event.kind,
            "event_date": event.event_date.isoformat(),
            "cik": event.issuer_cik,
            "company": event.issuer_name,
            "ticker": event.ticker,
            "title": event.title,
            "url": event.url,
            "data": event.data,
        },
    }


def yahoo_closes(batch_size: int = 20, requests_per_second: float = 2.0) -> PriceFetch:
    """Daily closes from Yahoo, in small paced batches (see radar.backtest.prices)."""

    def fetch(symbols: list[str], start: date, end: date):
        from radar.backtest.prices import YahooProvider

        provider = YahooProvider()
        data: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for i in range(0, len(symbols), batch_size):
            if i:
                time.sleep(1.0 / requests_per_second)
            got, failed = provider.fetch(symbols[i : i + batch_size], start, end)
            data.update(got)
            errors.update(failed)
        return data, errors

    return fetch


class ForwardRecorder:
    """Writes the live radar's observations to the forward log.

    `conn` is the radar database (to pick the tickers that need a daily price);
    `fetch_closes` returns ({symbol: DataFrame with close, adj_close, split}, errors).
    """

    def __init__(
        self,
        log_: ForwardLog,
        *,
        conn=None,
        benchmarks: tuple[str, ...] = ("SPY",),
        price_snapshot: bool = True,
        snapshot_after_utc_hour: int = 21,
        price_signal_days: int = 200,
        price_event_days: int = 30,
        price_max_symbols: int = 3000,
        fetch_closes: PriceFetch | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        background: bool = True,
    ):
        self.log = log_
        self.conn = conn
        self.benchmarks = benchmarks
        self.price_snapshot = price_snapshot
        self.after_hour = snapshot_after_utc_hour
        self.signal_days = price_signal_days
        self.event_days = price_event_days
        self.max_symbols = price_max_symbols
        self.fetch_closes = fetch_closes or yahoo_closes()
        self._now = now
        self._background = background
        self._snapshot_thread: threading.Thread | None = None
        self._snapshot_day: date | None = None
        # Day of a finished snapshot not yet saved in the database (the snapshot thread
        # never touches SQLite; the collection thread saves it on its next call).
        self._completed: date | None = None

    # ------------------------------------------------------------ observations

    def signal(self, signal: Signal, *, alerted: bool, seen_at: datetime | None = None) -> None:
        self._write([signal_record(signal, seen_at or self._now(), alerted=alerted)])

    def events(self, stored: Iterable[tuple[int, Any]]) -> None:
        self._write([event_record(event_id, event) for event_id, event in stored])

    def records(self, records: Iterable[dict[str, Any]]) -> None:
        self._write(list(records))

    def _write(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        try:
            self.log.append(records)
        except Exception:  # noqa: BLE001 - the log never stops collection
            log.exception("could not append %d record(s) to the forward log", len(records))

    # ---------------------------------------------------------- price snapshot

    def _state(self):
        from radar.sources.store import SourceStore

        return SourceStore(self.conn) if self.conn is not None else None

    def snapshot_due(self, now: datetime | None = None) -> bool:
        if not self.price_snapshot or self.conn is None:
            return False
        now = (now or self._now()).astimezone(UTC)
        if now.weekday() >= 5 or now.hour < self.after_hour:
            return False
        if self._snapshot_day == now.date():
            return False
        store = self._state()
        done = store.get_state(SNAPSHOT_STATE) if store is not None else None
        if done == now.date().isoformat():
            self._snapshot_day = now.date()
            return False
        return True

    def symbols(self, today: date) -> list[str]:
        """Benchmarks, then tickers of recent signals, then of recent market events."""
        out: list[str] = []
        for symbol in self.benchmarks:
            if (s := normalize_symbol(symbol)) and s not in out:
                out.append(s)
        queries = [
            (
                "SELECT ticker, MAX(signal_date) AS d FROM signals WHERE signal_date >= ? "
                "AND COALESCE(ticker, '') <> '' GROUP BY ticker ORDER BY d DESC",
                today - timedelta(days=self.signal_days),
            ),
            (
                "SELECT ticker, MAX(event_date) AS d FROM market_events WHERE event_date >= ? "
                "AND COALESCE(ticker, '') <> '' GROUP BY ticker ORDER BY d DESC",
                today - timedelta(days=self.event_days),
            ),
        ]
        for sql, since in queries:
            try:
                rows = self.conn.execute(sql, (since.isoformat(),)).fetchall()
            except Exception:  # noqa: BLE001 - a table may not exist yet
                continue
            for row in rows:
                symbol = normalize_symbol(row[0])
                if symbol and symbol not in out:
                    out.append(symbol)
        return out[: self.max_symbols]

    def _save_completed(self) -> None:
        done, self._completed = self._completed, None
        if done is not None and (store := self._state()) is not None:
            store.set_state(SNAPSHOT_STATE, done.isoformat())

    def maybe_snapshot(self) -> bool:
        """Start today's price snapshot if it is due (in the background); True if started.

        Call from the thread that owns the database connection (the collection thread).
        """
        self._save_completed()
        if not self.snapshot_due():
            return False
        if self._snapshot_thread is not None and self._snapshot_thread.is_alive():
            return False
        now = self._now()
        self._snapshot_day = now.astimezone(UTC).date()
        symbols = self.symbols(self._snapshot_day)
        if self._background:
            self._snapshot_thread = threading.Thread(
                target=self.snapshot, args=(symbols, now), name="forward-prices", daemon=True
            )
            self._snapshot_thread.start()
        else:
            self.snapshot(symbols, now)
            self._save_completed()
        return True

    def snapshot(self, symbols: list[str], now: datetime) -> int:
        """Record the latest close of each symbol; returns how many were recorded."""
        today = now.astimezone(UTC).date()
        try:
            data, errors = self.fetch_closes(
                symbols, today - timedelta(days=SNAPSHOT_LOOKBACK_DAYS), today
            )
        except Exception:  # noqa: BLE001 - try again on the next cycle
            log.exception("price snapshot failed")
            self._snapshot_day = None
            return 0
        seen_at = _iso(self._now())
        records = []
        for symbol in symbols:
            frame = data.get(symbol)
            if frame is None or len(frame) == 0:
                continue
            last = frame.iloc[-1]
            day = frame.index[-1]
            records.append(
                {
                    "kind": PRICE,
                    "source": PRICES_SOURCE,
                    "key": f"{symbol}:{day.date().isoformat()}",
                    "seen_at": seen_at,
                    "data": {
                        "symbol": symbol,
                        "day": day.date().isoformat(),
                        "close": float(last["close"]),
                        "adj_close": float(last["adj_close"]),
                        "split": float(last["split"]) if "split" in last else 0.0,
                    },
                }
            )
        missing = sorted(set(symbols) - {r["data"]["symbol"] for r in records})
        records.append(
            {
                "kind": PRICE,
                "source": PRICES_SOURCE,
                "key": f"snapshot:{today.isoformat()}",
                "seen_at": seen_at,
                "data": {
                    "snapshot": True,
                    "requested": len(symbols),
                    "recorded": len(records),
                    "missing": missing[:500],
                    "errors": dict(list(errors.items())[:100]),
                },
            }
        )
        self._write(records)
        if records[:-1]:
            # Only a snapshot with prices counts as done; otherwise the next cycle retries.
            self._completed = today
        else:
            self._snapshot_day = None
        log.info("price snapshot: %d of %d symbols recorded", len(records) - 1, len(symbols))
        return len(records) - 1


def build_recorder(settings, db) -> ForwardRecorder | None:
    """The forward recorder for `settings.forward`, on the radar database; None if off."""
    cfg = settings.forward
    if not cfg.enabled:
        return None
    bt = settings.backtest
    return ForwardRecorder(
        ForwardLog(settings.forward_dir),
        conn=db.conn,
        benchmarks=(bt.benchmark, *bt.extra_benchmarks),
        price_snapshot=cfg.price_snapshot,
        snapshot_after_utc_hour=cfg.snapshot_after_utc_hour,
        price_signal_days=cfg.price_signal_days,
        price_event_days=cfg.price_event_days,
        price_max_symbols=cfg.price_max_symbols,
        fetch_closes=yahoo_closes(bt.price_batch_size, bt.price_requests_per_second),
    )
