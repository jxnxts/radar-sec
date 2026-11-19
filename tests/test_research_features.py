"""Insider features of phase 2, 10-K text measures and price providers (no network)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

import duckdb
import httpx
import numpy as np
import pandas as pd
import pytest

from radar.research.collect import cash_price
from radar.research.features import base_filings, cooldown, csuite_events, stake_increase
from radar.research.prices import TiingoProvider, YahooChartProvider
from radar.research.text import (
    cosine,
    html_to_text,
    jaccard,
    risk_factors,
    rolling_quintiles,
    tokens,
)


def _parquet(frame: pd.DataFrame, path) -> None:
    duckdb.from_df(frame).write_parquet(str(path))


def trade(acc, issuer, filed, traded, code="P", shares=1000.0, price=100.0, after=None, di="D"):
    return {
        "acc": acc,
        "filing_date": pd.Timestamp(filed),
        "issuer_cik": issuer,
        "issuer_name": "Acme",
        "symbol": "ACME",
        "trans_date": pd.Timestamp(traded),
        "code": code,
        "ad": "A" if code == "P" else "D",
        "shares": shares,
        "price": price,
        "shares_after": after,
        "di": di,
        "title": "Common Stock",
    }


def owner(acc, cik, rel="Officer", title="Chief Executive Officer", name="Doe Jane"):
    return {
        "acc": acc,
        "owner_cik": cik,
        "owner_name": name,
        "rel": rel,
        "title": title,
        "remarks": "",
    }


@pytest.fixture
def tables(tmp_path):
    trades = [
        # owner 1 bought in March of 2017, 2018 and 2019 (routine in March), and in 2020
        trade("a17", "9", "2017-03-10", "2017-03-08"),
        trade("a18", "9", "2018-03-10", "2018-03-08"),
        trade("a19", "9", "2019-03-10", "2019-03-08"),
        trade("r20", "9", "2020-03-10", "2020-03-09", after=2000.0),
        trade("o20", "9", "2020-07-10", "2020-07-09", after=10_000.0),
        # owner 2: first purchase ever, doubles the position
        trade("f20", "9", "2020-07-11", "2020-07-10", after=2000.0),
        # owner 3 (CFO) the next day: closes a CEO + CFO cluster with owner 2
        trade("c20", "9", "2020-07-12", "2020-07-11", shares=500.0, after=600.0),
        # a 10% owner only: never a base filing
        trade("t20", "9", "2020-07-12", "2020-07-11"),
    ]
    owners = [owner(a, "1") for a in ("a17", "a18", "a19", "r20", "o20")]
    owners += [
        owner("f20", "2"),
        owner("c20", "3", title="CFO", name="Roe Rick"),
        owner("t20", "4", rel="TenPercentOwner", title="", name="Big Fund LP"),
    ]
    _parquet(pd.DataFrame(trades), tmp_path / "trades.parquet")
    _parquet(pd.DataFrame(owners), tmp_path / "owners.parquet")
    return tmp_path / "trades.parquet", tmp_path / "owners.parquet"


def test_stake_increase():
    lines = pd.DataFrame(
        {"di": ["D", "D"], "shares": [100.0, 100.0], "shares_after": [900.0, 1000.0]}
    )
    assert stake_increase(lines) == pytest.approx(200 / 800)
    assert stake_increase(
        pd.DataFrame({"di": ["D"], "shares": [5.0], "shares_after": [5.0]})
    ) == float("inf")
    assert np.isnan(
        stake_increase(pd.DataFrame({"di": ["D"], "shares": [5.0], "shares_after": [None]}))
    )


def test_base_filing_features(tables):
    base = base_filings(*tables, since="2020-01-01").set_index("acc")
    assert set(base.index) == {"r20", "o20", "f20", "c20"}  # the 10% owner is out
    assert base.loc["r20", "routine"] and not base.loc["r20", "opportunistic"]
    assert base.loc["r20", "cmp_classified"]
    # July trade by the same owner: classified (traded in each of the 3 prior years), not routine
    assert base.loc["o20", "opportunistic"]
    assert not base.loc["o20", "first_buy"]  # bought in March 2020
    assert base.loc["f20", "first_buy"] and not base.loc["f20", "cmp_classified"]
    assert base.loc["f20", "stake_inc"] == pytest.approx(1.0)
    assert base.loc["c20", "is_cfo"]


def test_csuite_cluster(tables):
    events = csuite_events(*tables, since="2020-01-01")
    assert len(events) == 1
    event = events.iloc[0]
    assert event.filing_date == pd.Timestamp("2020-07-12")
    assert event.ceo_and_cfo and event.n_insiders == 3
    assert event.value == pytest.approx(1000 * 100 * 2 + 500 * 100)


def test_cooldown_keeps_the_first_event_per_issuer():
    frame = pd.DataFrame(
        {
            "cik": ["1", "1", "1", "2"],
            "filing_date": [
                date(2021, 1, 1),
                date(2021, 1, 20),
                date(2021, 2, 5),
                date(2021, 1, 2),
            ],
        }
    )
    kept = cooldown(frame)
    assert list(zip(kept.cik, kept.filing_date, strict=True)) == [
        ("1", date(2021, 1, 1)),
        ("1", date(2021, 2, 5)),
        ("2", date(2021, 1, 2)),
    ]


def test_text_measures():
    html = (
        b"<html><head><script>var x=1;</script></head><body><ix:header>hidden 123</ix:header>"
        b"<p>Item 1A. Risk Factors ... see page 12</p><p>Item 1A. Risk Factors "
        + b"risk " * 600
        + b"</p><p>Item 1B. Unresolved Staff Comments none</p></body></html>"
    )
    text = html_to_text(html)
    assert "var x" not in text
    section = risk_factors(text)
    assert section.split().count("risk") == 600
    words = tokens("The 2025 results, a risk-factor list; THE end.")
    assert words == Counter({"the": 2, "results": 1, "risk-factor": 1, "list": 1, "end": 1})
    a, b = Counter({"x": 2, "y": 1}), Counter({"x": 2, "y": 1})
    assert cosine(a, b) == pytest.approx(1.0)
    assert jaccard(a, Counter({"x": 1, "z": 1})) == pytest.approx(1 / 3)
    assert np.isnan(cosine(a, Counter()))


def test_rolling_quintiles_use_only_earlier_filings():
    dates = pd.Series(pd.date_range("2020-01-01", periods=400, freq="D"))
    values = pd.Series(np.linspace(0.9, 1.0, 400))
    q = rolling_quintiles(dates, values)
    assert np.isnan(q[:200]).all()  # fewer than 200 earlier filings
    assert q[300] == 5  # higher than every earlier filing: least change


def test_cash_price_regex():
    text = (
        "each share will be converted into the right to receive $25.50 in cash, without interest. "
        "Holders will receive $25.50 per share in cash. The fee is $3.00 per share in cash once."
    )
    assert cash_price(text) == 25.50
    assert cash_price("a stock-for-stock exchange of 0.5 shares") is None


def chart_payload():
    return {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": -18000},
                    "timestamp": [
                        1609770600,
                        1609857000,
                        1609943400,
                    ],  # 2021-01-04..06 at the open (NY)
                    "indicators": {
                        "quote": [{"close": [10.0, 11.0, None]}],
                        "adjclose": [{"adjclose": [9.5, 10.5, None]}],
                    },
                    "events": {
                        "splits": {
                            "1609857000": {"date": 1609857000, "numerator": 2, "denominator": 1}
                        }
                    },
                }
            ]
        }
    }


def test_yahoo_chart_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        if "ACME" in request.url.path:
            return httpx.Response(200, json=chart_payload())
        if "SLOW" in request.url.path:
            return httpx.Response(429)
        return httpx.Response(404, json={"chart": {"result": None}})

    provider = YahooChartProvider(workers=1, transport=httpx.MockTransport(handler))
    data, errors = provider.fetch(["ACME", "GONE", "SLOW"], date(2021, 1, 1), date(2021, 1, 10))
    table = data["ACME"]
    assert list(table.index.date) == [date(2021, 1, 4), date(2021, 1, 5)]
    assert table.loc["2021-01-05", "split"] == 2.0
    assert errors == {"GONE": "no data", "SLOW": "too many requests"}


def test_tiingo_provider_needs_a_key_and_split_adjusts(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(ValueError):
        TiingoProvider()
    rows = [
        {"date": "2021-01-04T00:00:00.000Z", "close": 100.0, "adjClose": 49.0, "splitFactor": 1.0},
        {"date": "2021-01-05T00:00:00.000Z", "close": 51.0, "adjClose": 50.0, "splitFactor": 2.0},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Token k"
        return httpx.Response(200, content=json.dumps(rows))

    data, _ = TiingoProvider("k", transport=httpx.MockTransport(handler)).fetch(
        ["ACME"], date(2021, 1, 1), date(2021, 1, 10)
    )
    table = data["ACME"]
    assert table["close"].tolist() == [50.0, 51.0]  # raw close divided by the later split
    assert table["split"].tolist() == [0.0, 2.0]
