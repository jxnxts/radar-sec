"""Measuring a signal's return without looking ahead.

Entry: close of the first trading session AFTER the filing date.
Exit: close of the first session on or after entry + N months.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from radar.backtest.prices import PriceSeries

OK = "ok"
NO_TICKER = "no_ticker"
NO_PRICES = "no_prices"
NO_ENTRY = "no_entry_price"
PRICE_MISMATCH = "price_mismatch"
SUSPECT_JUMP = "suspect_jump"
UNMEASURED = "unmeasured"  # replay records without a backtest row

# Outcome codes in report order (their labels live in the message catalogs).
STATUSES = (OK, NO_TICKER, NO_PRICES, NO_ENTRY, PRICE_MISMATCH, SUSPECT_JUMP)

# Quotes below this are OTC noise ($0.0001), not a base to detect a jump from.
_MIN_JUMP_BASE = 0.01


@dataclass
class Measurement:
    status: str
    entry_date: date | None = None
    entry_price: float | None = None  # adjusted
    price_ratio: float | None = None  # market close ÷ price reported in the Form 4
    returns: dict[int, float] = field(default_factory=dict)  # gross, per horizon in months
    exit_dates: dict[int, date] = field(default_factory=dict)
    missing_exit: list[int] = field(default_factory=list)  # horizons without an exit price
    jump: float | None = None  # largest suspicious daily jump found (multiple)


def _to_day(value: date) -> np.datetime64:
    return np.datetime64(value, "D")


def _as_date(value: np.datetime64) -> date:
    return pd.Timestamp(value).date()


def first_session_after(calendar: np.ndarray, day: date) -> np.datetime64 | None:
    """First trading session strictly after `day`."""
    index = int(np.searchsorted(calendar, _to_day(day), side="right"))
    return calendar[index] if index < len(calendar) else None


def market_price_ratio(
    series: PriceSeries, trade_date: date, reported_price: float, tolerance_days: int
) -> float | None:
    """Close traded on the purchase day ÷ price reported in the Form 4 (None if missing)."""
    if reported_price <= 0:
        return None
    index = int(np.searchsorted(series.dates, _to_day(trade_date), side="right")) - 1
    if index < 0:
        return None
    gap = (_to_day(trade_date) - series.dates[index]).astype(int)
    if gap > tolerance_days * 2:
        return None
    return float(series.raw_close[index] / reported_price)


def measure(
    series: PriceSeries | None,
    calendar: np.ndarray,
    filing_date: date,
    horizons: tuple[int, ...],
    *,
    tolerance_days: int = 5,
    trade_date: date | None = None,
    reported_price: float | None = None,
    ratio_bounds: tuple[float, float] = (0.5, 2.0),
    jump_ratio: float | None = 5.0,
    jump_below: float = 1.0,
) -> Measurement:
    if series is None or len(series) == 0:
        return Measurement(NO_PRICES)

    target = first_session_after(calendar, filing_date)
    if target is None:
        return Measurement(NO_ENTRY)
    # The stock may not have traded on that exact session; a few days later is accepted.
    limit = tolerance_days * 2  # calendar days ≈ sessions × 7/5, with slack for holidays
    i = int(np.searchsorted(series.dates, target, side="left"))
    if i >= len(series) or (series.dates[i] - target).astype(int) > limit:
        return Measurement(NO_ENTRY)

    ratio = None
    if trade_date is not None and reported_price:
        ratio = market_price_ratio(series, trade_date, reported_price, tolerance_days)
        if ratio is not None and not (ratio_bounds[0] <= ratio <= ratio_bounds[1]):
            return Measurement(PRICE_MISMATCH, price_ratio=ratio)

    entry_day = series.dates[i]
    entry_price = float(series.adj_close[i])
    result = Measurement(
        OK, entry_date=_as_date(entry_day), entry_price=entry_price, price_ratio=ratio
    )
    last_day = series.dates[-1]
    last_index = i
    for months in horizons:
        goal = np.datetime64((pd.Timestamp(entry_day) + pd.DateOffset(months=months)).date(), "D")
        j = int(np.searchsorted(series.dates, goal, side="left"))
        if j >= len(series):
            # The series ended before the exit: the stock stopped trading along the way.
            if (goal - last_day).astype(int) > limit:
                result.missing_exit.append(months)
                continue
            j = len(series) - 1
        result.returns[months] = float(series.adj_close[j] / entry_price - 1.0)
        result.exit_dates[months] = _as_date(series.dates[j])
        last_index = max(last_index, j)

    if jump_ratio:
        jump = suspect_jump(series, i, last_index, jump_ratio, jump_below)
        if jump is not None:
            return Measurement(SUSPECT_JUMP, price_ratio=ratio, jump=jump)
    return result


def suspect_jump(
    series: PriceSeries, start: int, end: int, ratio: float, below: float
) -> float | None:
    """Largest daily jump that looks like an unadjusted reverse split between `start` and `end`.

    When Yahoo misses a reverse split (1 for 25, for example), the earlier price
    is not corrected and the series "rises" 25 times overnight. This only happens
    with penny stocks, which are the ones that do reverse splits; real moves of
    that size in stocks above $1 are kept.
    """
    if end <= start:
        return None
    before = series.adj_close[start:end]
    after = series.adj_close[start + 1 : end + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        change = after / before
    suspicious = (change >= ratio) & (before < below) & (before >= _MIN_JUMP_BASE)
    return float(change[suspicious].max()) if suspicious.any() else None


def benchmark_return(series: PriceSeries, entry: date, exit_: date) -> float | None:
    """Index return exactly between the signal's entry and exit dates."""
    i = int(np.searchsorted(series.dates, _to_day(entry), side="left"))
    j = int(np.searchsorted(series.dates, _to_day(exit_), side="left"))
    if i >= len(series) or j >= len(series):
        return None
    return float(series.adj_close[j] / series.adj_close[i] - 1.0)
