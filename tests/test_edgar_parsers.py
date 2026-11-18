"""Parsers against real filings saved in tests/fixtures."""

from datetime import date, datetime

import pytest

from radar.edgar import parse_submission, submission_txt_url
from radar.parsers.form4 import Form4ParseError, parse_form4
from radar.parsers.sc13d import Sc13dParseError, parse_13d, parse_13d_xml
from tests.conftest import read_fixture


def load(accession: str):
    return parse_submission(read_fixture(f"{accession}.txt"))


def form4(accession: str):
    return parse_form4(load(accession).primary_document.xml)


# ----------------------------------------------------------------- submission


def test_submission_header_form4():
    sub = load("0001831686-26-000014")
    assert sub.accession == "0001831686-26-000014"
    assert sub.form == "4"
    assert sub.filed_date == date(2026, 11, 17)
    assert sub.accepted_at == datetime(2026, 11, 17, 20, 8, 52)
    assert sub.party("issuer").name == "MP Materials Corp. / DE"
    assert sub.party("issuer").cik == "1801368"
    assert sub.party("owner").name == "Corbett Ryan"
    assert sub.primary_document.type == "4"
    assert sub.primary_document.xml.startswith("<?xml")


def test_submission_header_13d_identifies_subject_and_filer():
    sub = load("0001104659-26-129242")
    assert sub.form == "SCHEDULE 13D/A"
    assert sub.party("subject").name == "Atlas Energy Solutions Inc."
    assert sub.party("subject").cik == "1984060"
    assert [p.name for p in sub.parties_with("filer")] == ["SHEPARD GREGORY M"]


def test_submission_txt_url_strips_leading_zeros():
    assert submission_txt_url("0000936395", "0001444157-26-000031") == (
        "https://www.sec.gov/Archives/edgar/data/936395/000144415726000031/0001444157-26-000031.txt"
    )


# --------------------------------------------------------------------- Form 4


def test_form4_cfo_open_market_purchase():
    doc = form4("0001831686-26-000014")
    assert doc.document_type == "4"
    assert doc.issuer_cik == "1801368"
    assert doc.issuer_name == "MP Materials Corp. / DE"
    assert doc.issuer_ticker == "MP"
    assert doc.period_of_report == date(2026, 11, 17)

    (owner,) = doc.owners
    assert owner.name == "Corbett Ryan"
    assert owner.cik == "1831686"
    assert owner.is_officer and not owner.is_director and not owner.is_ten_percent_owner
    assert owner.officer_title == "Chief Financial Officer"

    (tx,) = doc.transactions
    assert tx.code == "P"
    assert tx.date == date(2026, 11, 17)
    assert tx.shares == 2627
    assert tx.price == 34.86
    assert tx.acquired_disposed == "A"
    assert tx.shares_after == 120620
    assert tx.ownership == "D"
    assert tx.value == pytest.approx(91_577.22)
    assert doc.purchases == [tx]


def test_form4_ten_percent_owner_with_two_purchases():
    doc = form4("0001104659-26-129252")
    assert doc.issuer_ticker == "BOLT"
    (owner,) = doc.owners
    assert owner.is_ten_percent_owner and not owner.is_officer
    assert owner.roles == ["10% owner"]
    assert [(t.date, t.shares, t.price) for t in doc.transactions] == [
        (date(2026, 11, 16), 33094, 5.89),
        (date(2026, 11, 17), 20000, 5.7499),
    ]
    assert all(t.ownership == "I" for t in doc.transactions)
    assert sum(t.value for t in doc.purchases) == pytest.approx(309_921.66)
    assert len(doc.footnotes) >= 1


def test_form4_other_codes_are_stored_but_are_not_purchases():
    doc = form4("0001782135-26-000037")
    assert doc.issuer_ticker == "GILD"
    assert [t.code for t in doc.transactions] == ["M", "S", "S", "S"]
    assert doc.transactions[0].acquired_disposed == "A"
    assert doc.transactions[1].acquired_disposed == "D"
    assert doc.purchases == []  # exercises and sales are not a buy signal


def test_form4_rejects_garbage():
    with pytest.raises(Form4ParseError):
        parse_form4("<html>this is not a Form 4</html>")
    with pytest.raises(Form4ParseError):
        parse_form4("<ownershipDocument><issuer>")


# ------------------------------------------------------------------------ 13D


def test_13d_new_xml_original_filing():
    doc = parse_13d(load("0001104659-26-129222"))
    assert doc.source_format == "xml"
    assert doc.form == "SCHEDULE 13D"
    assert not doc.is_amendment
    assert doc.issuer_name == "Perfect Moment Ltd."
    assert doc.issuer_cik == "1849221"
    assert doc.cusip == "713715100"
    assert doc.event_date == date(2026, 11, 16)
    (reporter,) = doc.reporters
    assert reporter.name == "X3 Higher Moment Fund LLC"
    assert reporter.cik == "1844136"
    assert reporter.shares == 5_267_050
    assert reporter.percent == 9.9
    assert doc.max_percent == 9.9
    assert "investment purposes" in doc.purpose


def test_13d_new_xml_group_uses_largest_stake_not_the_sum():
    doc = parse_13d(load("0001213900-26-121050"))
    assert [r.percent for r in doc.reporters] == [15.56, 0.33, 0.82, 0.66]
    assert doc.reporters[0].name == "Lim Soon Huat"
    assert doc.max_percent == 15.56


def test_13d_new_xml_amendment_is_flagged():
    doc = parse_13d(load("0001104659-26-129242"))
    assert doc.form == "SCHEDULE 13D/A"
    assert doc.is_amendment
    assert doc.max_percent == 4.89
    assert doc.reporters[0].name == "Gregory M. Shepard"


def test_13d_legacy_html_extracts_what_it_can():
    doc = parse_13d(load("0000921895-23-000084"))
    assert doc.source_format == "legacy"
    assert doc.form == "SC 13D"
    assert not doc.is_amendment
    # The issuer comes from the EDGAR header, which is structured.
    assert doc.issuer_cik == "1005286"
    assert doc.issuer_name.startswith("LIFECORE BIOMEDICAL")
    assert doc.cusip == "514766104"
    assert doc.event_date == date(2023, 1, 9)
    names = [r.name for r in doc.reporters]
    assert names[:5] == [
        "22NW Fund, LP",
        "22NW, LP",
        "22NW Fund GP, LLC",
        "22NW GP, Inc.",
        "Aron R. English",
    ]
    assert doc.reporters[0].percent == 9.99
    assert doc.reporters[0].shares == 3_096_787
    assert doc.reporters[0].cik == "1640809"  # matched with the header's "FILED BY"
    assert doc.max_percent == 9.99


def test_13d_xml_rejects_other_documents():
    with pytest.raises(Sc13dParseError):
        parse_13d_xml("<ownershipDocument/>")
