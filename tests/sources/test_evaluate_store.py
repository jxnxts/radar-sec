from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np
import pandas as pd

from radar.backtest.prices import build_series
from radar.models import Signal
from radar.sources import evaluate as ev
from radar.sources.base import AVOID, LONG, MarketEvent, cooldown_filter, split_display_name
from radar.sources.store import SourceStore, migrate


def _series(start: str, prices: list[float]):
    days = pd.bdate_range(start, periods=len(prices))
    zeros = [0.0] * len(prices)
    return build_series(days, prices, prices, zeros)


def _signal(kind: str, day: date, ticker: str, cik: str = "1") -> Signal:
    return Signal(
        type=kind,
        dedupe_key=f"{kind}:{ticker}:{day}",
        issuer_cik=cik,
        issuer_name="X",
        ticker=ticker,
        signal_date=day,
        score=50.0,
        explanation="",
        trigger_accession="",
    )


def test_penny_stocks_pay_the_higher_cost():
    flat = [10.0] * 200
    prices = {
        "SPY": _series("2024-01-01", flat),
        "IWM": _series("2024-01-01", flat),
        "BIG": _series("2024-01-01", [10.0] * 200),
        "PENNY": _series("2024-01-01", [2.0] * 200),
    }
    frame = ev.signals_frame(
        [
            _signal("t", date(2024, 1, 3), "BIG"),
            _signal("t", date(2024, 1, 3), "PENNY"),
            _signal("t", date(2024, 1, 3), ""),
        ]
    )
    measured = ev.measure_frame(frame, prices)
    big, penny, none = measured.to_dict("records")
    assert big["status"] == "ok" and round(big["ret_1m"], 6) == -0.002
    assert round(penny["ret_1m"], 6) == -0.010
    assert round(penny["exc_spy_1m"], 6) == -0.010
    assert none["status"] == "no_ticker"


def test_momentum_uses_only_past_prices():
    series = _series("2024-01-01", [10.0] * 10 + [12.0] + [100.0] * 5)
    day = pd.Timestamp(series.dates[10]).date()
    assert round(ev.momentum(series, day, 10), 6) == 0.2


def _stats(n=100, months=24, mean=0.01, median=0.01, t=2.5):
    return {"n": n, "months": months, "exc_mean": mean, "exc_median": median, "t_cohort": t}


def test_verdict_rules():
    assert ev.verdict(LONG, _stats(), _stats()).code == "use"
    assert ev.verdict(LONG, _stats(t=1.0), _stats()).code == "maybe"
    assert ev.verdict(LONG, _stats(), _stats(mean=-0.01)).code == "maybe"
    assert ev.verdict(LONG, _stats(median=-0.01), _stats()).code == "discard"
    assert (
        ev.verdict(AVOID, _stats(mean=-0.02, median=-0.01, t=-2.4), _stats(mean=-0.01)).code
        == "avoid"
    )
    assert (
        ev.verdict(AVOID, _stats(mean=-0.02, median=-0.01, t=-1.0), _stats(mean=-0.01)).code
        == "maybe_avoid"
    )
    assert ev.verdict(AVOID, _stats(), _stats()).code == "discard"
    assert ev.verdict(LONG, _stats(n=40), _stats()).code == "insufficient"
    assert ev.verdict(LONG, _stats(months=11), _stats()).code == "insufficient"
    assert ev.verdict(LONG, _stats(), None).code == "use"  # Form 144: no train period


def test_horizon_stats_counts_monthly_cohorts():
    frame = pd.DataFrame(
        {
            "cohort": ["2024-01", "2024-01", "2024-02"],
            "ret_1m": [0.1, 0.0, -0.1],
            "spy_1m": [0.0, 0.0, 0.0],
            "exc_spy_1m": [0.1, 0.0, -0.1],
        }
    )
    stats = ev.horizon_stats(frame, 1)
    assert stats["n"] == 3 and stats["months"] == 2
    assert np.isclose(stats["exc_mean"], 0.0)


def test_cooldown_filter_and_display_names():
    d = date(2024, 1, 1)
    kept = cooldown_filter(
        [
            _signal("a", d, "X"),
            _signal("a", date(2024, 1, 20), "X"),
            _signal("a", date(2024, 2, 5), "X"),
            _signal("b", d, "X"),
        ],
        30,
    )
    assert [(s.type, s.signal_date) for s in kept] == [("a", d), ("b", d), ("a", date(2024, 2, 5))]
    assert split_display_name("RESMED INC  (RMD, RSMDF)  (CIK 0000943819)") == (
        "RESMED INC",
        ["RMD", "RSMDF"],
        "943819",
    )
    assert split_display_name("Seagen Inc.  (CIK 0001060736)") == ("Seagen Inc.", [], "1060736")


def test_store_migrations_and_events():
    conn = sqlite3.connect(":memory:")
    store = SourceStore(conn)
    assert migrate(conn) == 1  # idempotent
    event = MarketEvent(
        source="eightk",
        kind="8k",
        key="acc-1",
        event_date=date(2024, 1, 2),
        issuer_cik="1",
        issuer_name="ACME",
        ticker="ACME",
        title="8-K",
        data={"items": ["2.02"]},
    )
    first = store.add_event(event)
    assert first is not None and store.add_event(event) is None
    assert store.has_event("eightk", "acc-1")
    rows = store.company_events("1", since=date(2023, 1, 1))
    assert rows[0]["data"]["items"] == ["2.02"] and rows[0]["ticker"] == "ACME"
    assert store.recent_events(source="eightk")[0]["key"] == "acc-1"
    assert store.count_events() == {"eightk": 1}
    store.set_state("k", {"a": 1})
    assert store.get_state("k") == {"a": 1} and store.get_state("missing", 7) == 7
