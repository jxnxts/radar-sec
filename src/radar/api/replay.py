"""REPLAY engine: plays the backtest's historical signals back in accelerated time.

The simulated clock advances `days_per_minute` days per real minute. Each signal
is published when the clock passes its moment. The room never goes more than
`max_idle` seconds without a signal (nights and weekends are skipped), and two
signals never come out back to back: the operator needs a few seconds to read each.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import statistics
import time
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any

from radar.api import hub as events
from radar.api.hub import Hub
from radar.api.ranking import WINDOWS, build_ranking
from radar.api.views import filing_view, logo_url, price_symbol, signal_view
from radar.backtest.replay import ReplayRecord, read_replay
from radar.backtest.returns import OK, UNMEASURED
from radar.edgar import filing_index_url
from radar.sectors import UNKNOWN

log = logging.getLogger(__name__)

FEED_LIMIT = 60
TAPE_LIMIT = 60
PREROLL_DAYS = 30
CHART_DAYS_BEFORE = 150
CHART_DAYS_AFTER = 200
SPEEDS = (0.5, 1.0, 2.0, 5.0, 10.0)
# The SEC accepts filings from 6am to 10pm (New York time).
_DAY_START = 6 * 3600 + 30 * 60
_DAY_SPAN = 15 * 3600


def _moment(record: ReplayRecord) -> datetime:
    """Simulated time of the signal within the day: fixed per filing, spread over the day."""
    digest = hashlib.sha256(f"{record.type}:{record.accession}".encode()).digest()
    offset = _DAY_START + int.from_bytes(digest[:4], "big") % _DAY_SPAN
    return datetime.combine(record.date, clock_time()) + timedelta(seconds=offset)


class ReplayEngine:
    mode = "replay"

    def __init__(
        self,
        records: list[ReplayRecord],
        hub: Hub,
        *,
        start: date | None = None,
        days_per_minute: float = 2.0,
        min_gap: float = 3.0,
        max_idle: float = 6.0,
        source: str = "",
        today: date | None = None,
    ):
        if not records:
            raise ValueError("empty replay file")
        timed = sorted(((_moment(r), r) for r in records), key=lambda item: item[0])
        self._times = [t for t, _ in timed]
        self._records = [r for _, r in timed]
        self._by_cik: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(self._records):
            self._by_cik[record.cik].append(index)
        self.hub = hub
        self.days_per_minute = days_per_minute
        self.min_gap = min_gap
        self.max_idle = max_idle
        self.source = source
        self.speed = 1.0
        self.paused = False
        self.loops = 0
        self._today = today or date.today()
        self._stop: asyncio.Event | None = None
        self._since_emit = float("inf")
        self.cursor = 0
        self.sim_time = self._times[0]
        self._session_start = 0
        self._excess: list[float] = []
        self._unmeasured = 0
        self._position(start or self.first_date)

    @classmethod
    def from_file(cls, path: Path, hub: Hub, **options: Any) -> ReplayEngine:
        return cls(list(read_replay(path)), hub, source=path.name, **options)

    @property
    def first_date(self) -> date:
        return self._records[0].date

    @property
    def last_date(self) -> date:
        return self._records[-1].date

    # ------------------------------------------------------------------- clock

    def _position(self, day: date) -> None:
        day = min(max(day, self.first_date), self.last_date)
        self.sim_time = datetime.combine(day, clock_time(6, 0))
        self.cursor = bisect_left(self._times, self.sim_time)
        self._session_start = self.cursor
        self._since_emit = float("inf")
        self._excess, self._unmeasured = [], 0

    def seek(self, day: date) -> None:
        """Jumps to a date and tells the clients to replace what they are showing."""
        self._position(day)
        self.hub.publish_threadsafe(events.FEED_RESET, self.snapshot())
        self._publish_status()

    def control(
        self, *, paused: bool | None = None, speed: float | None = None, seek: date | None = None
    ) -> dict[str, Any]:
        if paused is not None:
            self.paused = paused
        if speed is not None:
            self.speed = min(max(speed, SPEEDS[0]), SPEEDS[-1])
        if seek is not None:
            self.seek(seek)
        else:
            self._publish_status()
        return self.status()["replay"]

    def advance(self, seconds: float) -> int:
        """Advances the simulated clock by the equivalent of `seconds` real seconds.

        Returns how many signals were published.
        """
        if self.paused:
            return 0
        rate = self.days_per_minute * self.speed * 86_400 / 60  # simulated seconds per real second
        self._since_emit += seconds
        target = self.sim_time + timedelta(seconds=seconds * rate)
        emitted = 0
        while True:
            if self.cursor >= len(self._records):
                if self._since_emit < self.max_idle:
                    break  # the last signal stays on screen a little before starting over
                self.loops += 1
                self.seek(self.first_date)
                return emitted
            due = self._times[self.cursor]
            if due > target:
                if self._since_emit < self.max_idle:
                    break
                # Silence too long (night, weekend): jump straight to the next one.
                target = due
            if self._since_emit < self.min_gap / self.speed:
                target = due  # the clock waits for the operator to read the previous signal
                break
            self.sim_time = due
            self._emit(self.cursor)
            self.cursor += 1
            self._since_emit = 0.0
            emitted += 1
        self.sim_time = max(self.sim_time, target)
        return emitted

    def _emit(self, index: int) -> None:
        record = self._records[index]
        for entry in self._tape_entries(index):
            self.hub.publish_threadsafe(events.FILING_NEW, entry)
        self.hub.publish_threadsafe(events.SIGNAL_NEW, self._view(index))
        horizon = (record.outcome.get("horizons") or {}).get("6") or {}
        if record.outcome.get("status") == OK and horizon.get("excess") is not None:
            self._excess.append(horizon["excess"])
        else:
            self._unmeasured += 1
        self.hub.publish_threadsafe(events.RANKING_UPDATE, self.rankings())

    async def run(self, tick: float = 0.25) -> None:
        self._stop = asyncio.Event()
        last = time.monotonic()
        last_status = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            emitted = self.advance(now - last)
            last = now
            if emitted or now - last_status >= 1.0:
                self._publish_status()
                last_status = now
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=tick)
            except TimeoutError:
                pass

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def close(self) -> None:
        self.stop()

    def _publish_status(self) -> None:
        self.hub.publish_threadsafe(events.SYSTEM_STATUS, self.status())

    # ----------------------------------------------------------------- reading

    def _view(self, index: int) -> dict[str, Any]:
        record = self._records[index]
        signal = record.to_signal()
        return signal_view(
            signal,
            signal_id=f"r{index}",
            mode=self.mode,
            published_at=self._times[index],
            sector=record.sector or UNKNOWN,
            outcome=record.outcome or {"status": UNMEASURED},
            logo=record.ticker_current,
        )

    def _tape_entries(self, index: int) -> list[dict[str, Any]]:
        """The purchases behind the signal, as filing tape entries."""
        record = self._records[index]
        entries = []
        for row in record.purchases[-4:]:
            accession = row.get("accession") or record.accession
            entries.append(
                filing_view(
                    {
                        "accession": f"{accession}:{row.get('date')}",
                        "form": "4",
                        "company": record.name,
                        "ticker": record.ticker,
                        "cik": record.cik,
                        "filed_date": row.get("date"),
                        "accepted_at": None,
                        "url": filing_index_url(record.cik, accession) if record.cik else None,
                        "kind": "buy",
                        "who": row.get("name", ""),
                        "role": row.get("role", ""),
                        "value": row.get("value"),
                    }
                )
            )
        return entries

    def _emitted(self, limit: int) -> range:
        """Indices of the latest signals the clock has passed, newest first."""
        floor = bisect_left(self._times, self.sim_time - timedelta(days=PREROLL_DAYS))
        return range(self.cursor - 1, max(floor, self.cursor - limit) - 1, -1)

    def list_signals(
        self,
        *,
        limit: int = FEED_LIMIT,
        since: date | None = None,
        signal_type: str | None = None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for index in range(self.cursor - 1, -1, -1):
            record = self._records[index]
            if since is not None and record.date < since:
                break
            if since is None and self.sim_time - self._times[index] > timedelta(days=PREROLL_DAYS):
                break
            if signal_type and record.type != signal_type:
                continue
            out.append(self._view(index))
            if len(out) >= limit:
                break
        return out

    def list_filings(self, limit: int = TAPE_LIMIT) -> list[dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for index in self._emitted(limit):
            for entry in reversed(self._tape_entries(index)):
                # The same Form 4 can be part of a cluster and of an officer buy.
                entries.setdefault(entry["accession"], entry)
            if len(entries) >= limit:
                break
        return list(entries.values())[:limit]

    def signal_detail(self, signal_id: str) -> dict[str, Any] | None:
        if not signal_id.startswith("r") or not signal_id[1:].isdigit():
            return None
        index = int(signal_id[1:])
        if not 0 <= index < len(self._records):
            return None
        record = self._records[index]
        view = self._view(index)
        previous = [
            self._view(other)
            for other in reversed(self._by_cik[record.cik])
            if other < index and other != index
        ]
        end = min(record.date + timedelta(days=CHART_DAYS_AFTER), self._today)
        return {
            **view,
            "purchases": [{**row, "filed_date": None} for row in reversed(record.purchases)],
            "previous_signals": previous[:12],
            "chart": {
                "symbol": view["symbol"],
                "start": (record.date - timedelta(days=CHART_DAYS_BEFORE)).isoformat(),
                "end": end.isoformat(),
            },
        }

    def company(self, cik: str) -> dict[str, Any] | None:
        indices = [i for i in self._by_cik.get(cik, []) if i < self.cursor]
        if not indices:
            return None
        last = self._records[indices[-1]]
        purchases = [row for i in reversed(indices) for row in reversed(self._records[i].purchases)]
        return {
            "cik": cik,
            "name": last.name,
            "ticker": last.ticker,
            "symbol": price_symbol(last.ticker),
            "sector": last.sector or UNKNOWN,
            "logo": logo_url(last.ticker) if last.ticker_current else None,
            "signals": [self._view(i) for i in reversed(indices)],
            "purchases": purchases[:200],
        }

    def ranking(self, days: int) -> dict[str, Any]:
        today = self.sim_time.date()
        floor = bisect_left(self._times, self.sim_time - timedelta(days=days))
        rows: dict[str, dict[str, Any]] = {}
        for index in range(floor, self.cursor):
            record = self._records[index]
            row = rows.setdefault(
                record.cik or record.name,
                {
                    "cik": record.cik,
                    "name": record.name,
                    "ticker": record.ticker,
                    "sector": record.sector or UNKNOWN,
                    "value": 0.0,
                    "insiders": 0,
                    "filings": 0,
                    "last_date": record.date.isoformat(),
                    "logo_ok": record.ticker_current,
                },
            )
            # A cluster and an officer buy on the same day report the same purchases.
            row["value"] = max(row["value"], record.details.get("total_value") or 0.0)
            row["insiders"] = max(row["insiders"], record.details.get("n_insiders") or 1)
            row["filings"] += 1
            row["last_date"] = record.date.isoformat()
        return build_ranking(rows.values(), days=days, as_of=today, basis="replayed_signals")

    def rankings(self) -> dict[str, Any]:
        return {str(days): self.ranking(days) for days in WINDOWS}

    def tracked_tickers(self) -> list[str]:
        return []  # today's quote next to a years-old signal would only confuse

    def snapshot(self) -> dict[str, Any]:
        return {
            "signals": self.list_signals(),
            "filings": self.list_filings(),
            "ranking": self.rankings(),
        }

    def status(self) -> dict[str, Any]:
        measured = len(self._excess)
        return {
            "mode": self.mode,
            "sec": None,
            "queue": None,
            "ai": None,
            "totals": {"signals": len(self._records), "filings": None},
            "replay": {
                "clock": self.sim_time.isoformat(timespec="seconds"),
                "date": self.sim_time.date().isoformat(),
                "speed": self.speed,
                "speeds": list(SPEEDS),
                "paused": self.paused,
                "days_per_minute": self.days_per_minute * self.speed,
                "position": self.cursor,
                "total": len(self._records),
                "start": self.first_date.isoformat(),
                "end": self.last_date.isoformat(),
                "loops": self.loops,
                "source": self.source,
                "scoreboard": {
                    "shown": self.cursor - self._session_start,
                    "measured": measured,
                    "unmeasured": self._unmeasured,
                    "beat_spy_6m": sum(1 for value in self._excess if value > 0),
                    "median_excess_6m": statistics.median(self._excess) if measured else None,
                },
            },
        }
