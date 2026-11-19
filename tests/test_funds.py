"""Funds and similar vehicles are kept out of the insider buy signals."""

import json
from datetime import date

import pytest

from radar.config import SignalConfig
from radar.db import Database
from radar.funds import (
    FundClassifier,
    IssuerProfile,
    files_as_investment_company,
    is_fund,
    looks_like_fund_name,
    split_funds,
)
from radar.models import Signal
from radar.sectors import SectorLookup, cached_profiles

CFG = SignalConfig()


@pytest.mark.parametrize(
    "name",
    [
        "BNY MELLON STRATEGIC MUNICIPALS, INC.",  # LEO
        "BNY MELLON STRATEGIC MUNICIPAL BOND FUND, INC.",  # DSM
        "PIMCO Dynamic Income Fund",
        "Nuveen Municipal Value Fund",
        "BlackRock Municipal Income Trust",
        "Eaton Vance Tax-Advantaged Dividend Income Fund",
        "Macquarie Global Infrastructure Total Return Fund Inc.",
        "ADAMS DIVERSIFIED EQUITY FUND, INC.",
        "GABELLI EQUITY TRUST INC",
        "Bluerock Private Real Estate Fund",
        "First Trust Senior Floating Rate Income Fund II",
        "Some Closed-End Vehicle",
        "Western Asset Diversified Income Fund",
    ],
)
def test_obvious_fund_names_are_recognized(name):
    assert looks_like_fund_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "Fundamental Global Inc.",
        "Funding Circle",
        "Permian Basin Royalty Trust",
        "Mesabi Trust",
        "Texas Pacific Land Trust",
        "Universal Health Realty Income Trust",  # a REIT
        "Wheeler Real Estate Investment Trust, Inc.",
        "Northern Trust Corp",
        "Municipal Mortgage & Equity LLC",
        "Income Opportunity Realty Investors",
        "Hercules Capital, Inc.",  # a BDC: an operating company
        "Eagle Point Credit Co",  # a fund, but the name alone does not say so
        "Credit Acceptance Corp",
        "Equity Bancshares Inc",
        "Global Payments Inc",
        "Value Line Inc",
        "Private Bancorp",
        "Boeing Co",
        "",
        None,
    ],
)
def test_operating_company_names_are_not_funds(name):
    assert not looks_like_fund_name(name)


@pytest.mark.parametrize(
    ("name", "sic", "investment_company", "expected"),
    [
        ("Anything Inc.", "6722", None, True),  # open-end investment office
        ("Anything Inc.", "6726", False, True),  # closed-end investment office
        ("Some REIT Inc.", "6798", None, False),  # REITs are operating companies
        ("Nuveen Municipal Value Fund", "2834", None, False),  # a real SIC wins over the name
        ("BNY MELLON STRATEGIC MUNICIPALS, INC.", "0000", True, True),  # LEO: fund filings
        ("Eagle Point Credit Co", "", True, True),  # fund filings, plain name
        ("Eagle Point Credit Co", "", False, False),
        ("Eagle Point Credit Co", None, None, False),  # no registry answer, plain name
        ("PIMCO Dynamic Income Fund", None, None, True),  # no registry answer: name decides
        ("PIMCO Dynamic Income Fund", "0000", False, True),  # no SIC: name decides
        ("Boeing Co", "3721", False, False),
    ],
)
def test_is_fund_order(name, sic, investment_company, expected):
    assert is_fund(name, sic, investment_company, CFG) is expected


def test_the_exclusion_and_the_heuristic_can_be_turned_off():
    off = SignalConfig(exclude_funds=False)
    assert not is_fund("PIMCO Dynamic Income Fund", "6726", True, off)
    no_names = SignalConfig(fund_name_heuristic=False)
    assert not is_fund("PIMCO Dynamic Income Fund", "", None, no_names)
    assert is_fund("PIMCO Dynamic Income Fund", "", True, no_names)


def test_fund_sic_codes_come_from_the_config_even_as_numbers():
    cfg = SignalConfig(fund_sic_codes=(6798,))  # type: ignore[arg-type]  (TOML integers)
    assert is_fund("Some REIT", "6798", None, cfg)
    assert not is_fund("Anything", "6726", None, cfg)


def test_registered_fund_reports_mark_an_investment_company():
    assert files_as_investment_company(["4", "N-CSR", "DEF 14A"])
    assert files_as_investment_company(["nport-p"])
    assert not files_as_investment_company(["10-Q", "8-K", "4", "N-2", "N-PX"])
    assert not files_as_investment_company([])


def signal(kind: str, cik: str, name: str) -> Signal:
    return Signal(
        type=kind,
        dedupe_key=f"{kind}:{cik}",
        issuer_cik=cik,
        issuer_name=name,
        ticker="",
        signal_date=date(2026, 10, 22),
        score=60.0,
        explanation="",
        trigger_accession=f"acc-{cik}",
        details={},
    )


def test_only_insider_buy_signals_of_funds_are_dropped():
    profiles = {"818972": IssuerProfile("0000", True), "12927": IssuerProfile("3721", False)}
    asked: list[str] = []

    def profile_of(cik):
        asked.append(cik)
        return profiles.get(cik)

    classifier = FundClassifier(CFG, profile_of)
    leo = signal("cluster_buy", "818972", "BNY MELLON STRATEGIC MUNICIPALS, INC.")
    boeing = signal("cluster_buy", "12927", "BOEING CO")
    leo_officer = signal("big_officer_buy", "818972", "BNY MELLON STRATEGIC MUNICIPALS, INC.")
    leo_13d = signal("activist_13d", "818972", "BNY MELLON STRATEGIC MUNICIPALS, INC.")
    late = signal("late_filing_nt", "818972", "BNY MELLON STRATEGIC MUNICIPALS, INC.")

    kept, dropped = split_funds([leo, boeing, leo_officer, leo_13d, late], classifier)
    assert dropped == [leo, leo_officer]
    assert kept == [boeing, leo_13d, late]
    assert asked.count("818972") == 1  # one registry question per company
    assert split_funds([leo], None) == ([leo], [])


def test_without_a_registry_answer_the_classifier_asks_again_next_time():
    answers = iter([None, IssuerProfile("0000", True)])
    classifier = FundClassifier(CFG, lambda cik: next(answers))
    assert not classifier("1604174", "Eagle Point Credit Co")
    assert classifier("1604174", "Eagle Point Credit Co")


# ------------------------------------------------------------ SEC registry


def submissions(sic: str, forms: list[str]) -> str:
    return json.dumps({"sic": sic, "filings": {"recent": {"form": forms}}})


def test_profile_reads_sic_and_fund_filings_from_the_registry(make_client, recorder, tmp_path):
    leo = "https://data.sec.gov/submissions/CIK0000818972.json"
    boeing = "https://data.sec.gov/submissions/CIK0000012927.json"
    recorder.add(leo, submissions("0000", ["40-17F2", "3", "4", "N-CSR"]))
    recorder.add(boeing, submissions("3721", ["4", "8-K", "10-Q"]))
    client = make_client()
    lookup = SectorLookup(client, flush_every=1)

    assert lookup.profile("818972") == IssuerProfile("0000", True)
    assert lookup.profile("0000012927") == IssuerProfile("3721", False)
    assert lookup.profile("999") is None  # the SEC did not answer
    assert recorder.urls().count(leo) == 1

    cache = tmp_path / "cache"
    assert json.loads((cache / "investment-companies.json").read_text()) == {
        "12927": False,
        "818972": True,
    }
    again = SectorLookup(client)  # another run: everything from disk
    assert again.profile("818972") == IssuerProfile("0000", True)
    assert recorder.urls().count(leo) == 1
    # REPLAY reads the same caches without ever asking the SEC.
    offline = cached_profiles(cache)
    assert offline("818972") == IssuerProfile("0000", True)
    assert offline("555") is None


def test_an_issuer_without_sic_cached_before_the_fund_check_is_asked_once_more(
    make_client, recorder, tmp_path
):
    url = "https://data.sec.gov/submissions/CIK0001604174.json"
    recorder.add(url, submissions("", ["497AD", "NPORT-P"]))
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    (cache / "sectors.json").write_text(json.dumps({"1604174": "", "12927": "3721"}))
    lookup = SectorLookup(make_client())

    assert lookup.profile("12927") == IssuerProfile("3721", None)  # real SIC: not asked again
    assert lookup.profile("1604174") == IssuerProfile("", True)
    assert lookup.profile("1604174") == IssuerProfile("", True)
    assert recorder.urls() == [url]


# ---------------------------------------------------------------- database


def test_issuers_without_a_sic_are_checked_for_fund_filings(tmp_path):
    with Database(tmp_path / "radar.sqlite") as db:
        for cik in ("1", "2", "3", "4"):
            db.add_signal(signal("cluster_buy", cik, f"Company {cik}"))
        db.set_sector("1", "3721", "Industrials")  # real SIC: done
        db.set_sector("2", "", "Unclassified")  # no SIC, never checked: look again
        db.set_sector("3", "0000", "Unclassified", True)  # checked: a fund
        pending = db.issuers_without_sector(date(2026, 10, 1))
        assert sorted(pending) == ["2", "4"]
        assert db.issuer_profile("3") == ("0000", True)
        assert db.issuer_profile("1") == ("3721", None)
        assert db.issuer_profile("9") is None
        assert db.issuer_profiles()["3"] == ("0000", True)


def test_migration_to_v3_adds_the_fund_column(tmp_path):
    import sqlite3

    path = tmp_path / "radar.sqlite"
    with Database(path) as db:
        db.set_sector("1", "2834", "Healthcare")
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE issuers DROP COLUMN investment_company")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    with Database(path) as db:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.issuer_profile("1") == ("2834", None)
        db.set_sector("2", "0000", "Unclassified", True)
        assert db.issuer_profile("2") == ("0000", True)
