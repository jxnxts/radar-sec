"""Terminal events from the SEC filing history and the SEC price tape."""

from __future__ import annotations

import gzip
import json
from datetime import date

import pandas as pd

from radar.research.outcomes import (
    ACQUISITION,
    ACTIVE,
    BANKRUPTCY,
    DELISTED,
    STOPPED,
    UNKNOWN,
    OutcomeBook,
    classify,
    compact_submissions,
)
from radar.research.tape import SecTape

TODAY = date(2026, 11, 18)


def history(*rows: tuple[str, str, str]) -> dict:
    """rows: (filing date, form, 8-K items)."""
    return {
        "pages": [
            {
                "filingDate": [r[0] for r in rows],
                "form": [r[1] for r in rows],
                "items": [r[2] for r in rows],
                "accessionNumber": [f"0000000000-00-{i:06d}" for i in range(len(rows))],
                "primaryDocument": [f"doc{i}.htm" for i in range(len(rows))],
            }
        ]
    }


def test_merger_proxy_then_delisting_is_an_acquisition():
    payload = history(
        ("2020-03-01", "10-K", ""),
        ("2021-02-01", "DEFM14A", ""),
        ("2021-04-01", "8-K", "2.01,3.01,5.01"),
        ("2021-04-02", "25-NSE", ""),
    )
    outcome = classify(payload, after=date(2020, 6, 1), today=TODAY)
    assert outcome.kind == ACQUISITION
    assert outcome.terminal == date(2021, 4, 2)
    assert outcome.merger_doc == ("0000000000-00-000001", "doc1.htm")


def test_bankruptcy_wins_over_an_asset_sale():
    payload = history(
        ("2022-01-10", "8-K", "1.03,7.01"),
        ("2022-03-01", "DEFM14A", ""),
        ("2022-05-01", "15-12G", ""),
    )
    assert classify(payload, after=date(2021, 6, 1), today=TODAY).kind == BANKRUPTCY


def test_listing_deficiency_alone_is_not_an_acquisition():
    payload = history(("2022-01-10", "8-K", "3.01"), ("2022-03-01", "25", ""))
    outcome = classify(payload, after=date(2021, 6, 1), today=TODAY)
    assert outcome.kind == DELISTED
    assert outcome.evidence == "25"


def test_active_stopped_and_unknown():
    assert (
        classify(history(("2026-10-01", "10-Q", "")), after=date(2021, 1, 1), today=TODAY).kind
        == ACTIVE
    )
    stopped = classify(history(("2023-05-01", "10-Q", "")), after=date(2021, 1, 1), today=TODAY)
    assert (stopped.kind, stopped.terminal) == (STOPPED, date(2023, 5, 1))
    assert classify({}, after=date(2021, 1, 1), today=TODAY).kind == UNKNOWN
    assert (
        classify(history(("2020-05-01", "10-Q", "")), after=date(2021, 1, 1), today=TODAY).kind
        == UNKNOWN
    )


def test_outcome_book_reads_compact_files(tmp_path):
    raw = {"cik": 123, "name": "Acme", "tickers": ["ACME"]}
    page = history(("2021-02-01", "DEFM14A", ""), ("2021-04-02", "25-NSE", ""))["pages"][0]
    compact = compact_submissions(raw, [page])
    assert compact["cik"] == "0000000123"
    (tmp_path / "0000000123.json.gz").write_bytes(gzip.compress(json.dumps(compact).encode()))
    book = OutcomeBook(tmp_path, today=TODAY)
    assert book.outcome("0000000123", date(2020, 6, 1)).kind == ACQUISITION
    assert book.outcome("0000000999", date(2020, 6, 1)).kind == UNKNOWN


def test_tape_uses_the_median_of_the_window_and_filters_codes():
    tape = SecTape(
        pd.DataFrame(
            {
                "issuer_cik": ["1"] * 5,
                "trans_date": [
                    "2021-01-04",
                    "2021-01-05",
                    "2021-01-06",
                    "2021-01-07",
                    "2021-03-01",
                ],
                "code": ["P", "S", "F", "S", "D"],
                "price": [10.0, 10.5, 1000.0, 11.0, 25.0],
            }
        )
    )
    day, price = tape.near("1", date(2021, 1, 5), before=2, after=2)
    assert day == date(2021, 1, 5)
    assert price == 10.75  # median of 10, 10.5, 1000, 11: one mistyped price does not move it
    assert tape.near("1", date(2021, 3, 1), before=1, after=1) is None  # D is not a market price
    assert tape.near("1", date(2021, 3, 1), before=1, after=1, codes="D") == (
        date(2021, 3, 1),
        25.0,
    )
    assert tape.near("2", date(2021, 1, 5), before=5, after=5) is None
