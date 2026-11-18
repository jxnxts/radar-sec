"""Daily prices (Yahoo Finance via yfinance) with a local DuckDB cache."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Yahoo messages that signal a transient failure rather than "ticker has no data".
_TRANSIENT = ("rate limit", "too many requests", "timed out", "timeout", "connection", "429")


@dataclass(frozen=True)
class PriceSeries:
    """A ticker's series, ready for lookup by date."""

    dates: np.ndarray  # datetime64[D], ascending
    adj_close: np.ndarray  # adjusted for splits and dividends (for returns)
    raw_close: np.ndarray  # price as traded on the day (to check against the Form 4)

    def __len__(self) -> int:
        return len(self.dates)


@dataclass
class FetchReport:
    requested: int = 0
    cached: int = 0
    downloaded: int = 0
    no_data: int = 0
    failed: list[str] = field(default_factory=list)


class PriceProvider(Protocol):
    def fetch(
        self, tickers: list[str], start: date, end: date
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """Returns ({ticker: table with close, adj_close, split}, {ticker: error})."""
        ...


class _ErrorCollector(logging.Handler):
    """Captures the error messages that yfinance only publishes through logging."""

    _LINE = re.compile(r"^\[(.+?)\]: (.*)$", re.S)

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.errors: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        match = self._LINE.match(record.getMessage().strip())
        if match:
            for ticker in re.findall(r"'([^']+)'", match.group(1)):
                self.errors[ticker.upper()] = match.group(2)


class YahooProvider:
    def fetch(
        self, tickers: list[str], start: date, end: date
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        import yfinance as yf

        # yfinance reports the reason for each failure only through its logger. We
        # listen to the logger during the download to tell "ticker has no data" from
        # "rate limited", and to avoid dumping hundreds of warnings on the terminal.
        logger = logging.getLogger("yfinance")
        collector = _ErrorCollector()
        previous = (logger.level, logger.propagate)
        logger.addHandler(collector)
        logger.setLevel(logging.ERROR)
        logger.propagate = False
        try:
            raw = yf.download(
                tickers,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # yfinance treats the end as exclusive
                auto_adjust=False,
                actions=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        finally:
            logger.removeHandler(collector)
            logger.setLevel(previous[0])
            logger.propagate = previous[1]

        errors = collector.errors
        data: dict[str, pd.DataFrame] = {}
        if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
            return data, errors
        available = set(raw.columns.get_level_values(0))
        for ticker in tickers:
            if ticker not in available:
                continue
            frame = raw[ticker]
            if "Close" not in frame or "Adj Close" not in frame:
                continue
            table = pd.DataFrame(
                {
                    "close": frame["Close"],
                    "adj_close": frame["Adj Close"],
                    "split": frame["Stock Splits"] if "Stock Splits" in frame else 0.0,
                }
            ).dropna(subset=["close", "adj_close"])
            table = table[(table["close"] > 0) & (table["adj_close"] > 0)]
            if not table.empty:
                table.index = pd.to_datetime(table.index).tz_localize(None).normalize()
                data[ticker] = table
        return data, errors


class PriceStore:
    """Stores the downloaded prices; each ticker is requested from Yahoo once per period."""

    def __init__(self, path: Path, provider: PriceProvider | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.provider = provider or YahooProvider()
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS prices "
            "(ticker VARCHAR, day DATE, close DOUBLE, adj_close DOUBLE, split DOUBLE)"
        )
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS coverage (ticker VARCHAR PRIMARY KEY, first_day DATE, "
            "last_day DATE, n_rows INTEGER, fetched_at TIMESTAMP)"
        )

    def close(self) -> None:
        self.con.close()

    def _covered(self, start: date, end: date) -> set[str]:
        rows = self.con.execute(
            "SELECT ticker FROM coverage WHERE first_day <= ? AND last_day >= ?", [start, end]
        ).fetchall()
        return {r[0] for r in rows}

    def _save(self, ticker: str, table: pd.DataFrame | None, start: date, end: date) -> None:
        self.con.execute("DELETE FROM prices WHERE ticker = ?", [ticker])
        n_rows = 0
        if table is not None and not table.empty:
            rows = pd.DataFrame(
                {
                    "ticker": ticker,
                    "day": table.index.date,
                    "close": table["close"].to_numpy(dtype=float),
                    "adj_close": table["adj_close"].to_numpy(dtype=float),
                    "split": table["split"].fillna(0.0).to_numpy(dtype=float),
                }
            )
            self.con.register("incoming", rows)
            self.con.execute("INSERT INTO prices SELECT * FROM incoming")
            self.con.unregister("incoming")
            n_rows = len(rows)
        self.con.execute(
            "INSERT OR REPLACE INTO coverage VALUES (?, ?, ?, ?, now())",
            [ticker, start, end, n_rows],
        )

    def ensure(
        self,
        tickers: list[str],
        start: date,
        end: date,
        *,
        fetch_end: date | None = None,
        batch_size: int = 20,
        retries: int = 5,
        pause: float = 10.0,
        retry_wait: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        progress: Callable[[int, int], None] | None = None,
    ) -> FetchReport:
        """Downloads whatever is not yet cached for the requested period.

        `end` is how far the returns need prices. `fetch_end` (usually today) is
        how far to download: Yahoo's "Close" is already adjusted for every split
        up to the query date, so we need the list of splits up to that same date
        to undo the adjustment.

        `pause` is the interval between the start of one batch and the next:
        Yahoo blocks bursts, so what matters is the average pace. If it still
        rate-limits us, the batch waits (60s, 120s, 240s...) and retries only the
        missing tickers, instead of marking them as "no data".
        """
        fetch_end = max(fetch_end or end, end)
        wanted = sorted(set(tickers))
        covered = self._covered(start, end)
        pending = [t for t in wanted if t not in covered]
        report = FetchReport(requested=len(wanted), cached=len(wanted) - len(pending))

        done = 0
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            size = len(batch)
            started = clock()
            for attempt in range(retries + 1):
                try:
                    data, errors = self.provider.fetch(batch, start, fetch_end)
                except Exception as exc:  # yfinance fails in many different ways
                    log.warning("price batch failed (%s: %s)", exc.__class__.__name__, exc)
                    data, errors = {}, {ticker: "connection error" for ticker in batch}

                transient: list[str] = []
                for ticker in batch:
                    table = data.get(ticker)
                    message = errors.get(ticker, "").lower()
                    if table is None and any(mark in message for mark in _TRANSIENT):
                        transient.append(ticker)
                        continue
                    self._save(ticker, table, start, fetch_end)
                    if table is None:
                        report.no_data += 1
                    else:
                        report.downloaded += 1
                batch = transient
                if not batch:
                    break
                if attempt < retries:
                    wait = min(retry_wait * (2**attempt), 600.0)
                    log.warning(
                        "Yahoo rate-limited the requests (%d tickers pending in the batch); "
                        "waiting %.0fs",
                        len(batch),
                        wait,
                    )
                    sleep(wait)
            report.failed += batch
            done += size
            if progress:
                progress(done, len(pending))
            if done < len(pending):
                sleep(max(0.0, pause - (clock() - started)))
        return report

    def load(self, tickers: list[str]) -> dict[str, PriceSeries]:
        wanted = pd.DataFrame({"ticker": sorted(set(tickers))})
        self.con.register("wanted", wanted)
        frame = self.con.execute(
            "SELECT p.ticker, p.day, p.close, p.adj_close, p.split FROM prices p "
            "JOIN wanted w ON w.ticker = p.ticker ORDER BY p.ticker, p.day"
        ).df()
        self.con.unregister("wanted")
        return {
            ticker: build_series(group["day"], group["close"], group["adj_close"], group["split"])
            for ticker, group in frame.groupby("ticker", sort=False)
        }


def build_series(days, close, adj_close, split) -> PriceSeries:
    """Builds the series and undoes the split adjustment to get the price traded that day.

    Yahoo's "Close" is already divided by the splits that happened later.
    Multiplying by the future splits gets us back to the price the insider actually saw.
    """
    dates = pd.to_datetime(pd.Series(days)).to_numpy(dtype="datetime64[D]")
    close_arr = np.asarray(close, dtype=float)
    adj_arr = np.asarray(adj_close, dtype=float)
    ratios = np.asarray(split, dtype=float)
    ratios = np.where(np.isfinite(ratios) & (ratios > 0), ratios, 1.0)
    from_here = np.cumprod(ratios[::-1])[::-1]  # product of the splits from t onwards
    after = np.append(from_here[1:], 1.0)  # only the ones after t
    return PriceSeries(dates=dates, adj_close=adj_arr, raw_close=close_arr * after)
