"""Reading the SEC history, using a real slice of the 2023Q1 dataset."""

import io
import zipfile
from datetime import date

import pytest

from radar.backtest import datasets
from radar.backtest.datasets import (
    ensure_quarter,
    load_purchase_filings,
    normalize_symbol,
    parse_dataset_links,
    quarters_between,
)
from radar.backtest.marketcap import SharesOutstanding
from radar.backtest.runner import generate_signals
from radar.config import Settings
from tests.conftest import FIXTURES

SLICE = FIXTURES / "insider_2023q1"
ZIP_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2023q1_form345.zip"


def slice_zip(prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for table in datasets.TABLES:
            bundle.writestr(f"{prefix}{table}.tsv", (SLICE / f"{table}.tsv").read_bytes())
        bundle.writestr(f"{prefix}FORM_345_readme.htm", "readme")
    return buffer.getvalue()


def test_quarters_between():
    assert quarters_between(date(2019, 11, 18), date(2020, 5, 1)) == [
        (2019, 4),
        (2020, 1),
        (2020, 2),
    ]
    assert quarters_between(date(2023, 3, 31), date(2023, 3, 31)) == [(2023, 1)]
    assert len(quarters_between(date(2020, 1, 1), date(2025, 12, 31))) == 24


def test_dataset_links_come_from_the_real_page():
    links = parse_dataset_links((FIXTURES / "datasets_page_excerpt.html").read_text())
    assert len(links) == 83
    assert links[(2020, 1)] == (
        "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
        "2020q1_form345.zip"
    )
    # The SEC moved the newest files to another folder; that is why the URL comes from the page.
    assert "/datastandardsinnovation/" in links[(2026, 3)]
    assert all(
        quarter in links for quarter in quarters_between(date(2020, 1, 1), date(2025, 12, 31))
    )


def test_ensure_quarter_downloads_once_and_extracts_only_what_is_needed(make_client, recorder):
    recorder.add(ZIP_URL, slice_zip())
    client = make_client()

    folder = ensure_quarter(client, (2023, 1), {(2023, 1): ZIP_URL})
    again = ensure_quarter(client, (2023, 1), {(2023, 1): ZIP_URL})

    assert folder == again
    assert sorted(p.name for p in folder.iterdir()) == [
        "NONDERIV_TRANS.tsv",
        "REPORTINGOWNER.tsv",
        "SUBMISSION.tsv",
    ]
    assert len(recorder.calls) == 1


def test_ensure_quarter_falls_back_to_known_urls(make_client, recorder):
    recorder.add(ZIP_URL, slice_zip())
    folder = ensure_quarter(make_client(), (2023, 1), {})  # SEC page unavailable
    assert (folder / "SUBMISSION.tsv").exists()


def test_zip_member_paths_cannot_escape_the_cache(make_client, recorder, tmp_path):
    recorder.add(ZIP_URL, slice_zip(prefix="../../outside/"))
    folder = ensure_quarter(make_client(), (2023, 1), {(2023, 1): ZIP_URL})
    assert (folder / "SUBMISSION.tsv").exists()
    assert not (tmp_path / "outside").exists() and not (tmp_path / "cache" / "outside").exists()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AAPL", "AAPL"),
        ("amnb", "AMNB"),
        ("NYSE: KRC", "KRC"),
        ("NYSE:NYCB", "NYCB"),
        ("NASDAQ:RMR", "RMR"),
        ("(SIRI)", "SIRI"),
        ("[EXFY]", "EXFY"),
        ('"OMEX"', "OMEX"),
        ("HEI, HEI.A", "HEI"),
        ("PARAA,PARA", "PARAA"),
        ("AMC/APE", "AMC"),
        ("Z AND ZG", "Z"),
        ("WSO; WSOB", "WSO"),
        ("NYSE/TRN", "TRN"),
        ("NTIP-NYSE", "NTIP"),
        ("N O G", "NOG"),
        ("BRK.A", "BRK-A"),
        ("BRK.B", "BRK-B"),
        ("N/A", ""),
        ("n/a", ""),
        ("NONE", ""),
        ("None", ""),
        ("--", ""),
        ("[ N/A ]", ""),
        ("N.A.", ""),
        ("1314152", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_symbol(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.fixture(scope="module")
def loaded():
    return load_purchase_filings([SLICE], first_day=date(2022, 11, 18), last_day=date(2023, 3, 31))


def test_only_original_form4_open_market_purchases_are_loaded(loaded):
    filings, stats = loaded
    assert stats.form4_filings == 91  # 96 submissions in the slice, minus Form 3/5 and amendments
    assert stats.purchase_filings == len(filings) == 29
    assert all(p.shares > 0 and p.price > 0 for f in filings for p in f.purchases)
    assert all(p.date <= f.filing_date for f in filings for p in f.purchases)


def test_filing_date_and_roles_come_from_the_dataset(loaded):
    filings, _ = loaded
    ceo = next(f for f in filings if f.accession == "0001127602-23-003112")
    assert ceo.issuer_cik == "50863" and ceo.ticker == "INTC"
    assert ceo.filing_date == date(2023, 2, 2)  # filing, two days after the purchase
    assert ceo.purchases[0].date == date(2023, 1, 31)
    assert ceo.owner_names == ("GELSINGER PATRICK P",)
    assert ceo.is_ceo and not ceo.is_cfo and ceo.is_officer_or_director
    assert ceo.value == pytest.approx(250_470)

    cfo = next(f for f in filings if f.accession == "0001127602-23-003117")
    assert cfo.is_cfo and not cfo.is_ceo and cfo.officer_title == "EVP, CFO"


def test_rules_applied_to_history_use_the_filing_date(loaded):
    filings, _ = loaded
    signals = generate_signals(filings, Settings(), date(2023, 1, 1), date(2023, 3, 31))
    found = {(s.type, s.ticker, s.signal_date) for s in signals}
    assert ("big_officer_buy", "INTC", date(2023, 2, 2)) in found
    assert ("cluster_buy", "INTC", date(2023, 2, 2)) in found  # CEO and CFO on the same day
    assert ("cluster_buy", "CBNK", date(2023, 3, 15)) in found
    assert ("cluster_buy", "MTDR", date(2023, 3, 15)) in found

    matador = next(s for s in signals if s.ticker == "MTDR")
    assert matador.details["n_insiders"] == 3
    assert matador.details["last_buy"] == "2023-03-14"  # purchase the day before the signal
    # No signal is dated by the transaction: always by the filing, which comes later.
    assert all(s.signal_date.isoformat() >= s.details["last_buy"] for s in signals)


def test_signals_outside_the_requested_period_are_dropped(loaded):
    filings, _ = loaded
    signals = generate_signals(filings, Settings(), date(2023, 3, 1), date(2023, 3, 31))
    assert signals and all(s.signal_date >= date(2023, 3, 1) for s in signals)
    assert not any(s.ticker == "INTC" and s.type == "big_officer_buy" for s in signals)


def test_shares_outstanding_never_uses_figures_published_after_the_signal():
    shares = SharesOutstanding()
    shares.add_frame(
        {
            "data": [
                {"cik": 50863, "end": "2022-10-21", "val": 4_127_000_000},
                {"cik": 50863, "end": "2023-01-20", "val": 4_137_000_000},
                {"cik": 50863, "end": "2023-04-21", "val": 4_171_000_000},
            ]
        }
    )
    shares.finish()
    # On 2023-02-02 the 01-20 figure had not been published in a 10-K yet: the previous one applies.
    assert shares.as_of("0000050863", date(2023, 2, 2)) == 4_127_000_000
    assert shares.as_of("50863", date(2023, 3, 10)) == 4_137_000_000
    assert shares.as_of("50863", date(2021, 1, 1)) is None  # nothing published before
    assert shares.as_of("50863", date(2026, 1, 1)) is None  # figure too old
    assert shares.as_of("999", date(2023, 2, 2)) is None
