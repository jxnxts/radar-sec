"""Phase-2 measurement (Yahoo path and survivorship correction) and calendar portfolios."""

from __future__ import annotations

import gzip
import json
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from radar.backtest.prices import build_series
from radar.research.measure import (
    COST,
    COST_PENNY,
    INSIDER_ENTRY_BIAS,
    OK_CORRECTED,
    Engine,
    cost_for,
)
from radar.research.outcomes import OutcomeBook
from radar.research.portfolio import (
    event_stats,
    monthly_portfolio,
    newey_west_t,
    ols_newey_west,
    portfolio_stats,
)
from radar.research.prices import PriceBook
from radar.research.tape import SecTape

DAYS = pd.bdate_range("2021-01-01", "2022-06-30")


def series(prices) -> object:
    prices = np.asarray(prices, float)
    return build_series(DAYS.date, prices, prices, np.zeros(len(prices)))


def growth(start: float, daily: float):
    return start * (1 + daily) ** np.arange(len(DAYS))


def book(**extra) -> PriceBook:
    return PriceBook(
        series={
            "SPY": series(growth(100, 0.0004)),
            "IWM": series(growth(50, 0.0003)),
            **{k: series(v) for k, v in extra.items()},
        }
    )


def write_history(folder, cik: str, rows) -> None:
    pages = [
        {
            "filingDate": [r[0] for r in rows],
            "form": [r[1] for r in rows],
            "items": [r[2] for r in rows],
            "accessionNumber": [f"acc-{i}" for i in range(len(rows))],
            "primaryDocument": ["d.htm"] * len(rows),
        }
    ]
    (folder / f"{cik}.json.gz").write_bytes(gzip.compress(json.dumps({"pages": pages}).encode()))


def empty_tape() -> SecTape:
    return SecTape(pd.DataFrame({"issuer_cik": [], "trans_date": [], "code": [], "price": []}))


def test_cost_tier():
    assert cost_for(4.99) == COST_PENNY
    assert cost_for(5.0) == COST
    assert cost_for(None) == COST


def test_yahoo_path_matches_the_phase1_rules(tmp_path):
    engine = Engine(book(ACME=growth(20, 0.001)), empty_tape(), OutcomeBook(tmp_path))
    pos = engine.position("0000000001", "ACME", date(2021, 3, 1), 20.0, date(2021, 2, 26))
    assert pos.status == "ok" and pos.source == "yahoo"
    assert pos.entry_date == date(2021, 3, 2)
    assert pos.how == {1: "yahoo", 3: "yahoo", 6: "yahoo"}
    assert pos.gross[3] > 0
    assert pos.cost == COST


def test_bankruptcy_without_prices_is_minus_100(tmp_path):
    cik = "0000000002"
    write_history(tmp_path, cik, [("2021-03-10", "8-K", "1.03"), ("2021-04-01", "25-NSE", "")])
    tape = SecTape(
        pd.DataFrame(
            {"issuer_cik": [cik], "trans_date": ["2021-03-03"], "code": ["S"], "price": [2.0]}
        )
    )
    engine = Engine(book(), tape, OutcomeBook(tmp_path, today=date(2026, 11, 18)))
    pos = engine.position(cik, "", date(2021, 3, 1), 2.1, date(2021, 2, 26))
    assert pos.status == OK_CORRECTED and pos.outcome == "bankruptcy"
    assert pos.entry_price == 2.0  # SEC tape entry
    # delisted within a month of entry: every horizon ends on the delisting date at −100%
    assert pos.gross == {1: -1.0, 3: -1.0, 6: -1.0}
    assert pos.exit_date[3] == date(2021, 4, 1)
    assert pos.cost == COST_PENNY


def test_acquisition_valued_at_the_form4_disposal_price(tmp_path):
    cik = "0000000003"
    write_history(tmp_path, cik, [("2021-03-15", "DEFM14A", ""), ("2021-05-03", "25-NSE", "")])
    tape = SecTape(
        pd.DataFrame(
            {"issuer_cik": [cik], "trans_date": ["2021-04-30"], "code": ["D"], "price": [30.0]}
        )
    )
    engine = Engine(book(), tape, OutcomeBook(tmp_path, today=date(2026, 11, 18)))
    pos = engine.position(cik, "GONE", date(2021, 3, 1), 20.0, date(2021, 2, 26))
    # no tape entry: the insider's price scaled by the train-period drift
    assert pos.entry_price == pytest.approx(20.0 * (1 + INSIDER_ENTRY_BIAS))
    assert pos.gross[3] == pytest.approx(30.0 / pos.entry_price - 1)
    assert pos.how[3].startswith("merger_form4_d")


def test_without_correction_unpriced_signals_stay_unmeasured(tmp_path):
    engine = Engine(book(), empty_tape(), OutcomeBook(tmp_path), correct=False)
    assert engine.position("0000000004", "GONE", date(2021, 3, 1), 5.0, None).gross == {}
    frame = engine.measure_frame(
        pd.DataFrame(
            [
                {
                    "cik": "0000000004",
                    "ticker": "",
                    "filing_date": date(2021, 3, 1),
                    "insider_price": 5.0,
                    "last_trade": None,
                }
            ]
        )
    )
    assert frame.loc[0, "status"] == "no_ticker"
    assert frame["net_3m"].isna().all()


def test_newey_west_and_ols():
    rng = np.random.default_rng(1)
    x = rng.normal(0.01, 0.02, 400)
    mean, t = newey_west_t(x, lag=0)
    assert mean == pytest.approx(x.mean())
    assert t == pytest.approx(x.mean() / (x.std(ddof=0) / math.sqrt(len(x))))
    bench = rng.normal(0, 0.03, 400)
    alpha, beta, t_alpha = ols_newey_west(0.005 + 1.5 * bench + rng.normal(0, 0.001, 400), bench)
    assert alpha == pytest.approx(0.005, abs=5e-4)
    assert beta == pytest.approx(1.5, abs=0.02)
    assert t_alpha > 10
    assert math.isnan(newey_west_t([0.1, 0.2])[1])


def test_calendar_portfolio_and_event_stats(tmp_path):
    engine = Engine(
        book(A=growth(10, 0.002), B=growth(30, 0.0)), empty_tape(), OutcomeBook(tmp_path)
    )
    events = pd.DataFrame(
        [
            {
                "cik": "1",
                "ticker": "A",
                "filing_date": date(2021, 2, 1),
                "insider_price": 10 * 1.002**21,
                "last_trade": date(2021, 1, 29),
            },
            {
                "cik": "2",
                "ticker": "B",
                "filing_date": date(2021, 2, 1),
                "insider_price": 30.0,
                "last_trade": date(2021, 1, 29),
            },
        ]
    )
    measured = engine.measure_frame(events)
    stats = event_stats(measured, 3)
    assert stats["n"] == 2 and stats["n_corrected"] == 0
    table = monthly_portfolio(
        measured,
        engine,
        3,
        np.zeros(len(engine.calendar)),
        date(2021, 1, 1),
        date(2021, 12, 31),
        min_positions=1,
    )
    march = table.loc[pd.Period("2021-03", "M")]
    # equal weight of +0.2%/day and 0%/day, compounded over March's sessions
    assert march.port == pytest.approx(np.prod([1.001] * 23) - 1, rel=0.02)
    assert march.n == 2
    summary = portfolio_stats(table)
    assert summary["months"] >= 3
    assert summary["mean_month"] > 0
    assert math.isnan(summary["t_spy"])  # fewer than 6 months: no t-stat
