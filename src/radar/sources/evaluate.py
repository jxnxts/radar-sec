"""Measurement and statistics for the new signals.

Same engine as the phase-1 backtest (Yahoo prices in the DuckDB cache, entry at the
close of the first session after the signal date, exits 1/3/6 months later), with
the cost rule of the plan: 0.2% round trip, 1.0% when the entry price is below US$ 5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from radar.backtest.metrics import t_stat, winsorized_mean
from radar.backtest.prices import PriceSeries
from radar.backtest.returns import OK, benchmark_return, measure
from radar.models import Signal

from .base import AVOID, LONG

COST = 0.002
COST_PENNY = 0.010
PENNY = 5.0
HORIZONS = (1, 3, 6)
BENCHMARKS = ("SPY", "IWM")
TRAIN = (date(2020, 1, 1), date(2022, 12, 31))
TEST = (date(2023, 1, 1), date(2025, 12, 31))
MIN_TEST_MONTHS = 12
MIN_TEST_SIGNALS = 50
LIQUID_MIN_PRICE = 5.0
LIQUID_MIN_CAP = 300_000_000.0


def signals_frame(signals: list[Signal]) -> pd.DataFrame:
    rows = []
    for s in signals:
        rows.append(
            {
                "type": s.type,
                "signal_date": s.signal_date,
                "year": s.signal_date.year,
                "cohort": s.signal_date.strftime("%Y-%m"),
                "cik": s.issuer_cik,
                "issuer": s.issuer_name,
                "ticker": s.ticker,
                "score": s.score,
                "key": s.dedupe_key,
                "accession": s.trigger_accession,
            }
        )
    return pd.DataFrame(rows)


def raw_close_on_or_before(series: PriceSeries | None, day: date) -> float | None:
    if series is None or not len(series):
        return None
    i = int(np.searchsorted(series.dates, np.datetime64(day, "D"), side="right")) - 1
    if i < 0 or (np.datetime64(day, "D") - series.dates[i]).astype(int) > 10:
        return None
    return float(series.raw_close[i])


def momentum(series: PriceSeries | None, day: date, sessions: int) -> float | None:
    """Adjusted return over the `sessions` sessions ending on `day` (inclusive)."""
    if series is None or not len(series):
        return None
    j = int(np.searchsorted(series.dates, np.datetime64(day, "D"), side="right")) - 1
    i = j - sessions
    if i < 0 or (np.datetime64(day, "D") - series.dates[j]).astype(int) > 5:
        return None
    return float(series.adj_close[j] / series.adj_close[i] - 1.0)


def measure_frame(
    frame: pd.DataFrame,
    prices: dict[str, PriceSeries],
    *,
    shares_as_of=None,
    tolerance_days: int = 5,
) -> pd.DataFrame:
    calendar = prices[BENCHMARKS[0]].dates
    records = []
    for row in frame.itertuples(index=False):
        record: dict = {"status": "no_ticker"}
        if row.ticker:
            series = prices.get(row.ticker)
            result = measure(
                series, calendar, row.signal_date, HORIZONS, tolerance_days=tolerance_days
            )
            record = {"status": result.status, "entry_date": result.entry_date}
            if result.status == OK:
                i = int(np.searchsorted(series.dates, np.datetime64(result.entry_date, "D")))
                entry_raw = float(series.raw_close[i])
                cost = COST_PENNY if entry_raw < PENNY else COST
                record["entry_raw_price"] = entry_raw
                record["cost"] = cost
                before = raw_close_on_or_before(series, row.signal_date)
                shares = (
                    shares_as_of(row.cik, row.signal_date) if shares_as_of and row.cik else None
                )
                record["market_cap"] = shares * before if shares and before else None
                for months, gross in result.returns.items():
                    exit_day = result.exit_dates[months]
                    record[f"ret_{months}m"] = gross - cost
                    for bench in BENCHMARKS:
                        index_return = benchmark_return(prices[bench], result.entry_date, exit_day)
                        key = bench.lower()
                        record[f"{key}_{months}m"] = index_return
                        if index_return is not None:
                            record[f"exc_{key}_{months}m"] = gross - cost - index_return
        records.append(record)
    measured = pd.DataFrame(records, index=frame.index)
    for months in HORIZONS:
        for column in [f"ret_{months}m"] + [
            f"{p}{b.lower()}_{months}m" for b in BENCHMARKS for p in ("", "exc_")
        ]:
            if column not in measured:
                measured[column] = np.nan
    for column in ("entry_raw_price", "market_cap", "cost", "entry_date"):
        if column not in measured:
            measured[column] = None
    return pd.concat([frame, measured], axis=1)


def horizon_stats(frame: pd.DataFrame, months: int, benchmark: str = "spy") -> dict:
    net = frame[f"ret_{months}m"]
    excess = frame[f"exc_{benchmark}_{months}m"]
    valid = net.notna() & excess.notna()
    net, excess = net[valid].astype(float), excess[valid].astype(float)
    if net.empty:
        return {"n": 0, "months": 0}
    cohorts = excess.groupby(frame.loc[valid, "cohort"]).mean()
    return {
        "n": int(len(net)),
        "months": int(len(cohorts)),
        "hit": float((net > 0).mean()),
        "beats": float((excess > 0).mean()),
        "mean": float(net.mean()),
        "median": float(net.median()),
        "index_mean": float(frame.loc[valid, f"{benchmark}_{months}m"].astype(float).mean()),
        "exc_mean": float(excess.mean()),
        "exc_median": float(excess.median()),
        "exc_winsor": winsorized_mean(excess),
        "t_cohort": t_stat(cohorts),
    }


def in_period(frame: pd.DataFrame, period: tuple[date, date]) -> pd.DataFrame:
    dates = pd.to_datetime(frame["signal_date"]).dt.date
    return frame[(dates >= period[0]) & (dates <= period[1])]


def liquid(frame: pd.DataFrame) -> pd.DataFrame:
    price = pd.to_numeric(frame["entry_raw_price"], errors="coerce")
    cap = pd.to_numeric(frame["market_cap"], errors="coerce")
    return frame[(price >= LIQUID_MIN_PRICE) & (cap >= LIQUID_MIN_CAP)]


@dataclass(frozen=True)
class Verdict:
    """`code`: use | maybe | discard | avoid | maybe_avoid | insufficient.

    `reason_key` and `values` render the reason in any language
    (`sources.report.reason.<key>` in the catalogs).
    """

    code: str
    reason_key: str
    values: dict = field(default_factory=dict)


def verdict(direction: str, test: dict, train: dict | None) -> Verdict:
    """The pre-registered verdict rule (research/new-signals-plan.md, section 2).

    `train=None` waives the train-sign check (Form 144 has no pre-2023 history).
    """
    n, months = test.get("n", 0), test.get("months", 0)
    if n < MIN_TEST_SIGNALS or months < MIN_TEST_MONTHS:
        return Verdict(
            "insufficient",
            "insufficient",
            {"n": n, "months": months, "min_n": MIN_TEST_SIGNALS, "min_months": MIN_TEST_MONTHS},
        )
    mean, median, t = test["exc_mean"], test["exc_median"], test["t_cohort"]
    t = 0.0 if t is None or math.isnan(t) else float(t)
    shown = {"t": f"{t:.1f}"}
    waived = train is None
    train_mean = train.get("exc_mean") if train and train.get("n") else None
    if direction == LONG:
        if mean > 0 and median > 0:
            agrees = waived or (train_mean is not None and train_mean > 0)
            if t >= 2.0 and agrees:
                return Verdict("use", "use", shown)
            return Verdict("maybe", "maybe_t" if t < 2.0 else "maybe_train", shown)
        return Verdict("discard", "discard_long", shown)
    if direction == AVOID:
        if mean < 0 and median < 0:
            agrees = waived or (train_mean is not None and train_mean < 0)
            if t <= -2.0 and agrees:
                return Verdict("avoid", "avoid", shown)
            return Verdict(
                "maybe_avoid", "maybe_avoid_t" if t > -2.0 else "maybe_avoid_train", shown
            )
        return Verdict("discard", "discard_avoid", shown)
    return Verdict("discard", "untested", shown)
