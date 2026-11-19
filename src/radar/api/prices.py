"""Quotes for the dashboard, behind an interface so the source can be swapped.

True real-time data is paid. The default source is Yahoo Finance (yfinance),
polled periodically and delayed by about 15 minutes; the dashboard says so.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from radar.api import hub as events
from radar.api.hub import Hub

log = logging.getLogger(__name__)

INDICES: dict[str, str] = {
    "SPY": "S&P 500",
    "IWM": "Russell 2000",
    "QQQ": "Nasdaq 100",
    "^VIX": "VIX",
}
SPARK_POINTS = 40
# Latest prices asked by the liquidity check stay cached this long (seconds).
LAST_PRICE_TTL = 12 * 3600
LAST_PRICE_BATCH = 50


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float | None
    as_of: str  # ISO, with timezone, of the last known trade
    spark: list[float] = field(default_factory=list)  # the latest session, downsampled

    @property
    def change_pct(self) -> float | None:
        if not self.prev_close:
            return None
        return self.price / self.prev_close - 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["change"] = (self.price - self.prev_close) if self.prev_close else None
        data["change_pct"] = self.change_pct
        data["name"] = INDICES.get(self.symbol, "")
        return data


@dataclass
class Bar:
    t: str  # YYYY-MM-DD
    o: float
    h: float
    l: float  # noqa: E741 (field name in the JSON: open, high, low, close)
    c: float
    v: float | None = None


class PriceSource(Protocol):
    name: str
    delay_minutes: int

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Last known quote for each symbol (the ones that fail are left out)."""
        ...

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Daily bars from `start` to `end` inclusive.

        Adjusted for splits but not for dividends: that way the chart shows the
        price the insider paid, not a price rewritten by the payouts.
        """
        ...


def downsample(values: list[float], points: int = SPARK_POINTS) -> list[float]:
    if len(values) <= points:
        return [round(v, 4) for v in values]
    step = (len(values) - 1) / (points - 1)
    return [round(values[round(i * step)], 4) for i in range(points)]


class YahooPriceSource:
    """Yahoo Finance via yfinance. No key, no guarantees and delayed."""

    name = "Yahoo Finance"
    delay_minutes = 15

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        import pandas as pd
        import yfinance as yf

        if not symbols:
            return {}
        raw = yf.download(
            symbols,
            period="5d",
            interval="5m",
            group_by="ticker",
            auto_adjust=False,
            prepost=False,
            threads=True,
            progress=False,
        )
        out: dict[str, Quote] = {}
        if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
            return out
        available = set(raw.columns.get_level_values(0))
        for symbol in symbols:
            if symbol not in available or "Close" not in raw[symbol]:
                continue
            close = raw[symbol]["Close"].dropna()
            if close.empty:
                continue
            days = close.index.normalize()
            last_day = days[-1]
            today = close[days == last_day]
            before = close[days < last_day]
            stamp = close.index[-1].to_pydatetime() + timedelta(minutes=5)
            out[symbol] = Quote(
                symbol=symbol,
                price=round(float(today.iloc[-1]), 4),
                prev_close=round(float(before.iloc[-1]), 4) if not before.empty else None,
                as_of=stamp.isoformat(timespec="seconds"),
                spark=downsample([float(v) for v in today.tolist()]),
            )
        return out

    def last_closes(self, symbols: list[str]) -> dict[str, tuple[float, str]]:
        """Latest daily close of each symbol, with its date (lighter than `quotes`)."""
        import pandas as pd
        import yfinance as yf

        if not symbols:
            return {}
        raw = yf.download(
            symbols,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
        out: dict[str, tuple[float, str]] = {}
        if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
            return out
        available = set(raw.columns.get_level_values(0))
        for symbol in symbols:
            if symbol not in available or "Close" not in raw[symbol]:
                continue
            close = raw[symbol]["Close"].dropna()
            if not close.empty:
                out[symbol] = (round(float(close.iloc[-1]), 4), close.index[-1].date().isoformat())
        return out

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        import yfinance as yf

        frame = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # yfinance treats the end as exclusive
            interval="1d",
            auto_adjust=False,
            progress=False,
            multi_level_index=False,
        )
        if frame is None or frame.empty:
            return []
        frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
        return [
            Bar(
                t=index.date().isoformat(),
                o=round(float(row.Open), 4),
                h=round(float(row.High), 4),
                l=round(float(row.Low), 4),
                c=round(float(row.Close), 4),
                v=float(row.Volume) if row.Volume == row.Volume else None,
            )
            for index, row in frame.iterrows()
        ]


class BacktestHistory:
    """Closing prices already downloaded by the backtest (DuckDB), as an offline fallback."""

    name = "backtest cache"

    def __init__(self, path: Path):
        self.path = path

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        if not self.path.exists():
            return []
        import duckdb

        try:
            con = duckdb.connect(str(self.path), read_only=True)
        except duckdb.Error as exc:  # file in use by a running backtest
            log.debug("backtest price cache unavailable: %s", exc)
            return []
        try:
            rows = con.execute(
                "SELECT day, close FROM prices WHERE ticker = ? AND day BETWEEN ? AND ? "
                "ORDER BY day",
                [symbol, start, end],
            ).fetchall()
        finally:
            con.close()
        return [
            Bar(t=day.isoformat(), o=round(c, 4), h=round(c, 4), l=round(c, 4), c=round(c, 4))
            for day, c in rows
        ]


def _last_close(fallback: BacktestHistory, symbol: str) -> tuple[float, str] | None:
    today = date.today()
    bars = fallback.history(symbol, today - timedelta(days=10), today)
    return (bars[-1].c, bars[-1].t) if bars else None


class PriceService:
    """Polls the source in the background, keeps the latest quotes and publishes `price.tick`."""

    def __init__(
        self,
        source: PriceSource,
        hub: Hub,
        *,
        cache_dir: Path | None = None,
        interval: float = 60.0,
        fallback: BacktestHistory | None = None,
        tracked: Any = None,
    ):
        self.source = source
        self.hub = hub
        self.interval = interval
        self.cache_dir = cache_dir
        self.fallback = fallback
        self._tracked = tracked or (lambda: [])
        # yfinance keeps global state: every query goes through a single thread.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-prices")
        self._stop: asyncio.Event | None = None
        self.quotes: dict[str, dict[str, Any]] = {}
        self.state = "starting"
        self.error: str | None = None
        self.last_tick_at: datetime | None = None

    # ---------------------------------------------------------------- quotes

    def symbols(self) -> list[str]:
        wanted = list(INDICES)
        for symbol in self._tracked():
            if symbol not in wanted:
                wanted.append(symbol)
        return wanted

    def refresh(self) -> dict[str, Any]:
        """One query to the source. Returns the payload of the `price.tick` event."""
        symbols = self.symbols()
        try:
            quotes = self.source.quotes(symbols)
        except Exception as exc:  # yfinance fails in many different ways
            self.state, self.error = "error", f"{exc.__class__.__name__}: {exc}"[:200]
            log.warning("quotes unavailable: %s", self.error)
            return self.tick()
        if quotes:
            self.quotes.update({symbol: quote.to_dict() for symbol, quote in quotes.items()})
            self.quotes = {s: q for s, q in self.quotes.items() if s in symbols}
            self.state, self.error = "ok", None
            self.last_tick_at = datetime.now(UTC)
        else:
            self.state, self.error = "error", "the source returned no quotes"
        return self.tick()

    def tick(self) -> dict[str, Any]:
        return {"quotes": self.quotes, **self.status()}

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "source": self.source.name,
            "delay_minutes": self.source.delay_minutes,
            "interval_s": self.interval,
            "last_tick_at": (
                self.last_tick_at.isoformat(timespec="seconds") if self.last_tick_at else None
            ),
            "error": self.error,
        }

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        while not self._stop.is_set():
            started = time.monotonic()
            tick = await loop.run_in_executor(self._executor, self.refresh)
            self.hub.publish(events.PRICE_TICK, tick)
            wait = max(5.0, self.interval - (time.monotonic() - started))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def close(self) -> None:
        self.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------- latest prices

    def _last_file(self) -> Path | None:
        return self.cache_dir / "last-prices.json" if self.cache_dir is not None else None

    def _read_last(self) -> dict[str, Any]:
        path = self._last_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_last(self, data: dict[str, Any]) -> None:
        path = self._last_file()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _fetch_last(self, symbols: list[str]) -> dict[str, tuple[float, str]]:
        """Asks the source (in the yfinance thread) for the latest price of each symbol."""
        found: dict[str, tuple[float, str]] = {}
        closes = getattr(self.source, "last_closes", None)
        for start in range(0, len(symbols), LAST_PRICE_BATCH):
            batch = symbols[start : start + LAST_PRICE_BATCH]
            try:
                if closes is not None:
                    found.update(closes(batch))
                else:
                    found.update(
                        {s: (q.price, q.as_of) for s, q in self.source.quotes(batch).items()}
                    )
            except Exception as exc:  # yfinance fails in many different ways
                log.warning("latest prices unavailable: %s", exc)
        return found

    def latest_prices(self, symbols: list[str]) -> dict[str, tuple[float, str]]:
        """Latest price and its date for each symbol: (price, as_of ISO).

        In order: the quotes already polled, a disk cache of `LAST_PRICE_TTL`, the
        source (one batched query) and, offline, the backtest's closing prices.
        Symbols with no price anywhere are left out. Safe to call from any thread.
        """
        wanted = [s for s in dict.fromkeys(symbols) if s]
        out: dict[str, tuple[float, str]] = {}
        for symbol in wanted:
            quote = self.quotes.get(symbol)
            if quote and quote.get("price"):
                out[symbol] = (float(quote["price"]), str(quote.get("as_of") or ""))
        cache = self._read_last()
        now = time.time()
        for symbol in wanted:
            entry = cache.get(symbol)
            if symbol not in out and entry and now - entry.get("fetched_at", 0) < LAST_PRICE_TTL:
                out[symbol] = (float(entry["price"]), str(entry.get("as_of") or ""))
        missing = [s for s in wanted if s not in out]
        if missing:
            try:
                fetched = self._executor.submit(self._fetch_last, missing).result(timeout=120)
            except Exception as exc:
                log.warning("latest prices unavailable: %s", exc)
                fetched = {}
            for symbol, (price, as_of) in fetched.items():
                cache[symbol] = {"price": price, "as_of": as_of, "fetched_at": now}
                out[symbol] = (price, as_of)
            if fetched:
                self._write_last(cache)
            if self.fallback is not None:
                for symbol in missing:
                    if symbol not in out and (last := _last_close(self.fallback, symbol)):
                        out[symbol] = last
        return out

    # --------------------------------------------------------------- history

    def _cache_file(self, symbol: str, start: date, end: date) -> Path | None:
        if self.cache_dir is None:
            return None
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in symbol)
        return self.cache_dir / "price-history" / f"{safe}_{start}_{end}.json"

    def history(self, symbol: str, start: date, end: date) -> dict[str, Any]:
        """Daily bars for the symbol. Closed periods stay cached forever."""
        today = date.today()
        end = min(end, today)
        closed = end < today - timedelta(days=3)
        path = self._cache_file(symbol, start, end)
        if path is not None and path.exists():
            age = time.time() - path.stat().st_mtime
            if closed or age < 15 * 60:
                return json.loads(path.read_text(encoding="utf-8"))

        bars: list[Bar] = []
        source, kind, error = self.source.name, "ohlc", None
        try:
            bars = self._executor.submit(self.source.history, symbol, start, end).result(timeout=40)
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"[:200]
            log.warning("history for %s unavailable: %s", symbol, error)
        if not bars and self.fallback is not None:
            bars = self.fallback.history(symbol, start, end)
            if bars:
                source, kind, error = self.fallback.name, "close", None

        payload = {
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "source": source,
            "kind": kind,
            "delay_minutes": self.source.delay_minutes,
            "bars": [asdict(bar) for bar in bars],
            "error": error,
        }
        # An empty answer is not cached: it may just be a transient source failure.
        if path is not None and bars:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        return payload
