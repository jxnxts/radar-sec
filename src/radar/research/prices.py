"""Price sources for phase 2, all behind `radar.backtest.prices.PriceProvider`.

- `YahooChartProvider`: Yahoo's chart endpoint, one request per ticker. Much faster than the
  batch download for long lists full of delisted tickers (an unknown ticker is a quick 404).
- `TiingoProvider`: ready for a paid/free Tiingo key (`TIINGO_API_KEY`), which also covers
  delisted tickers. Not used unless asked for; no key is needed to run phase 2.
- `PriceBook`: read-only view over one or more DuckDB price stores.

To plug another vendor (Polygon, ...), write a class with
`fetch(tickers, start, end) -> ({ticker: DataFrame[close, adj_close, split]}, {ticker: error})`.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import httpx
import pandas as pd

from radar.backtest.prices import PriceSeries, build_series

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


def _clean(table: pd.DataFrame) -> pd.DataFrame | None:
    table = table[~table.index.duplicated(keep="last")].dropna(subset=["close", "adj_close"])
    table = table[(table["close"] > 0) & (table["adj_close"] > 0)]
    return None if table.empty else table


class YahooChartProvider:
    def __init__(
        self, workers: int = 3, timeout: float = 20.0, transport: httpx.BaseTransport | None = None
    ):
        self.workers = workers
        self.client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout, transport=transport
        )

    def one(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame | None, str]:
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp()) + 86_400
        params = {
            "period1": p1,
            "period2": p2,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        try:
            response = self.client.get(CHART_URL.format(ticker=ticker), params=params)
        except httpx.HTTPError as exc:
            return None, f"connection error: {exc}"
        if response.status_code == 429:
            return None, "too many requests"
        if response.status_code >= 500:
            return None, f"connection error {response.status_code}"
        try:
            result = (response.json().get("chart") or {}).get("result")
        except ValueError:
            return None, "no data"
        if not result or not result[0].get("timestamp"):
            return None, "no data"
        result = result[0]
        offset = (result.get("meta") or {}).get("gmtoffset", 0)

        def day(ts: int) -> date:
            return datetime.fromtimestamp(ts + offset, tz=UTC).date()

        days = pd.to_datetime([day(ts) for ts in result["timestamp"]])
        close = result["indicators"]["quote"][0].get("close")
        adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose") or close
        split = pd.Series(0.0, index=days)
        for event in ((result.get("events") or {}).get("splits") or {}).values():
            when = pd.Timestamp(day(event["date"]))
            if when in split.index and event.get("denominator"):
                split[when] = event["numerator"] / event["denominator"]
        table = pd.DataFrame(
            {"close": close, "adj_close": adjusted, "split": split.to_numpy()}, index=days
        )
        table = _clean(table)
        return table, "" if table is not None else "no data"

    def fetch(self, tickers: list[str], start: date, end: date):
        data: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(self.workers) as pool:
            results = pool.map(lambda ticker: self.one(ticker, start, end), tickers)
            for ticker, (table, error) in zip(tickers, results, strict=True):
                if table is not None:
                    data[ticker] = table
                elif error:
                    errors[ticker] = error
        return data, errors


class TiingoProvider:
    """Tiingo end-of-day prices (includes delisted tickers). Needs `TIINGO_API_KEY`."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key or os.environ.get("TIINGO_API_KEY", "")
        if not self.api_key:
            raise ValueError("TIINGO_API_KEY is not set")
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def fetch(self, tickers: list[str], start: date, end: date):
        data: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        for ticker in tickers:
            try:
                response = self.client.get(
                    TIINGO_URL.format(ticker=ticker.replace("-", ".")),
                    params={"startDate": start.isoformat(), "endDate": end.isoformat()},
                    headers={"Authorization": f"Token {self.api_key}"},
                )
            except httpx.HTTPError as exc:
                errors[ticker] = f"connection error: {exc}"
                continue
            if response.status_code == 429:
                errors[ticker] = "too many requests"
                continue
            if response.status_code != 200 or not response.json():
                errors[ticker] = "no data"
                continue
            rows = response.json()
            frame = pd.DataFrame(rows)
            frame.index = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
            # Tiingo's raw close is as traded; the provider contract wants a split-adjusted close.
            factor = frame["splitFactor"].where(frame["splitFactor"] > 0, 1.0)
            later = factor[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
            table = pd.DataFrame(
                {
                    "close": frame["close"] / later,
                    "adj_close": frame["adjClose"],
                    "split": frame["splitFactor"].where(factor != 1.0, 0.0),
                }
            )
            table = _clean(table)
            if table is None:
                errors[ticker] = "no data"
            else:
                data[ticker] = table
        return data, errors


def provider_by_name(name: str):
    """`yahoo` (batch download), `yahoo-chart` (default for phase 2) or `tiingo`."""
    if name == "yahoo":
        from radar.backtest.prices import YahooProvider

        return YahooProvider()
    if name == "yahoo-chart":
        return YahooChartProvider()
    if name == "tiingo":
        return TiingoProvider()
    raise ValueError(f"unknown price provider '{name}' (yahoo, yahoo-chart, tiingo)")


class PriceBook:
    """Daily series from one or more price stores; the first store that has a ticker wins."""

    def __init__(
        self, paths: list[Path] | None = None, series: dict[str, PriceSeries] | None = None
    ):
        self.series: dict[str, PriceSeries] = dict(series or {})
        for path in paths or []:
            if not path.exists():
                continue
            con = duckdb.connect(str(path), read_only=True)
            frame = con.execute(
                "SELECT ticker, day, close, adj_close, split FROM prices ORDER BY ticker, day"
            ).df()
            con.close()
            for ticker, group in frame.groupby("ticker", sort=False):
                if ticker not in self.series:
                    self.series[ticker] = build_series(
                        group["day"], group["close"], group["adj_close"], group["split"]
                    )

    def get(self, ticker: str) -> PriceSeries | None:
        return self.series.get(ticker) if ticker else None
