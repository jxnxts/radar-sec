from __future__ import annotations

import json
from datetime import date, timedelta

from radar.sources.efts import parse_hits
from radar.sources.form144.history import notice_from_hit
from radar.sources.form144.parser import extract_xml, parse_form144
from radar.sources.form144.rules import (
    FORM144_CLUSTER,
    FORM144_LARGE,
    Notice,
    detect_clusters,
    large_sale,
)
from tests.conftest import FIXTURES

F144 = FIXTURES / "sources" / "form144"


def test_parses_a_real_form_144():
    doc = parse_form144(extract_xml((F144 / "0001230439-24-000001.txt").read_text()))
    assert doc.issuer_cik == "1770787"
    assert doc.issuer_name == "10x Genomics, Inc."
    assert doc.seller_name == "Hindson Benjamin J."
    assert doc.seller_cik == "1786391"
    assert doc.relationships == ("Officer", "Director")
    assert doc.units_to_sell == 2581
    assert doc.market_value == 122494.26
    assert doc.units_outstanding == 105109711
    assert doc.approx_sale_date == date(2024, 2, 22)
    assert doc.acquisition_nature == ("Restricted Stock Unit Grant",)
    assert not doc.is_amendment
    assert round(doc.percent_of_outstanding, 4) == round(100 * 2581 / 105109711, 4)


def test_parses_a_form_144_with_several_lots():
    doc = parse_form144(extract_xml((F144 / "0001959173-26-008125.txt").read_text()))
    assert doc.issuer_name == "Matson, Inc."
    assert doc.exchange == "NYSE"
    assert len(doc.acquisition_nature) >= 3
    assert doc.market_value == 320835.0


def test_full_text_search_hit_gives_issuer_and_seller():
    _, hits = parse_hits((F144 / "efts_144_2024-02-22.json").read_bytes())
    notice = notice_from_hit(hits[0])
    assert notice is not None
    assert notice.issuer_name == "RESMED INC"
    assert notice.ticker == "RMD"
    assert notice.issuer_cik == "943819"
    assert notice.seller_cik == "1186102"
    assert notice.filing_date == date(2024, 2, 22)


def _notice(n: int, seller: str, day: date, value: float | None = 1e6) -> Notice:
    return Notice(
        accession=f"0000000000-24-{n:06d}",
        issuer_cik="1",
        issuer_name="ACME",
        seller_cik=seller,
        seller_name=f"Seller {seller}",
        filing_date=day,
        ticker="ACME",
        market_value=value,
    )


def test_cluster_fires_on_the_third_distinct_seller_within_ten_days():
    d0 = date(2024, 3, 1)
    notices = [
        _notice(1, "a", d0),
        _notice(2, "a", d0 + timedelta(days=1)),  # same seller again: does not count
        _notice(3, "b", d0 + timedelta(days=3)),
        _notice(4, "c", d0 + timedelta(days=9)),  # third seller, day 10 of the window
        _notice(5, "d", d0 + timedelta(days=12)),  # inside the 30-day cooldown
    ]
    signals = detect_clusters(notices)
    assert [s.signal_date for s in signals] == [d0 + timedelta(days=9)]
    assert signals[0].type == FORM144_CLUSTER
    assert signals[0].details["n_sellers"] == 3
    assert signals[0].trigger_accession == notices[3].accession


def test_cluster_needs_the_sellers_inside_the_window():
    d0 = date(2024, 3, 1)
    notices = [
        _notice(1, "a", d0),
        _notice(2, "b", d0 + timedelta(days=5)),
        _notice(3, "c", d0 + timedelta(days=10)),
    ]  # 11 days: "a" is out
    assert detect_clusters(notices) == []


def test_cluster_respects_prior_signals():
    d0 = date(2024, 3, 1)
    notices = [_notice(i, s, d0 + timedelta(days=i)) for i, s in enumerate("abc")]
    assert detect_clusters(notices, prior_signals={"1": [d0 - timedelta(days=5)]}) == []
    assert detect_clusters(notices, prior_signals={"1": [d0 - timedelta(days=40)]})


def test_large_sale_thresholds():
    small = _notice(1, "a", date(2024, 1, 2), value=9_999_999)
    assert large_sale(small) is None
    big = _notice(2, "a", date(2024, 1, 2), value=12_000_000)
    signal = large_sale(big)
    assert signal is not None and signal.type == FORM144_LARGE
    assert signal.details["tested"] is False
    by_percent = Notice(
        accession="x",
        issuer_cik="1",
        issuer_name="ACME",
        seller_cik="a",
        seller_name="A",
        filing_date=date(2024, 1, 2),
        market_value=100.0,
        percent_outstanding=1.5,
    )
    assert large_sale(by_percent) is not None


def test_efts_fixture_is_valid_json():
    data = json.loads((F144 / "efts_144_2024-02-22.json").read_text())
    assert data["hits"]["total"]["value"] == 197
