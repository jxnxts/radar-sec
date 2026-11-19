"""Price, market value and liquidity of a signal's company (no network: SEC and prices faked)."""

import json
from datetime import date

import pytest

from radar.api.hub import Hub
from radar.api.prices import PriceService
from radar.config import DashboardConfig
from radar.liquidity import (
    CONCEPT_URL,
    LIQUIDITY_GATED_TYPES,
    SharesLookup,
    is_liquid,
    latest_shares,
    liquidity_fields,
    market_value,
    measure,
)
from tests.api_helpers import FakePrices

CFG = DashboardConfig()
TODAY = date(2026, 11, 18)


def test_avoid_rules_are_gated_and_long_or_insider_rules_are_not():
    assert {
        "late_filing_nt",
        "short_crowded",
        "ceo_cfo_exit_8k",
        "form144_cluster",
        "form144_large",
        "ftd_persistent",
        "auditor_change_8k",
        "bankruptcy_8k",
    } == LIQUIDITY_GATED_TYPES
    for kind in ("cluster_buy", "big_officer_buy", "activist_13d", "buyback_8k", "squeeze_setup"):
        assert kind not in LIQUIDITY_GATED_TYPES


def test_latest_shares_takes_the_newest_reference_date_then_the_last_filed():
    payload = {
        "units": {
            "shares": [
                {"end": "2026-06-30", "val": 100, "filed": "2026-08-01"},
                {"end": "2026-09-30", "val": 110, "filed": "2026-11-01"},
                {"end": "2026-09-30", "val": 111, "filed": "2026-11-10"},  # amended
                {"end": "2027-03-31", "val": 999, "filed": "2026-11-10"},  # future: ignored
                {"end": "bad", "val": 1},
                {"end": "2026-10-31", "val": 0},
            ]
        }
    }
    assert latest_shares(payload, TODAY) == (111, date(2026, 9, 30))
    assert latest_shares({}, TODAY) is None
    stale = {"units": {"shares": [{"end": "2024-12-31", "val": 5, "filed": "2025-02-01"}]}}
    assert latest_shares(stale, TODAY) is None  # too old to value the company today


@pytest.mark.parametrize(
    ("price", "shares", "liquid"),
    [
        (5.0, 60_000_000, True),  # exactly at both thresholds
        (4.99, 1_000_000_000, False),  # cheap stock
        (50.0, 5_000_000, False),  # US$ 250 mi
        (None, 1_000_000_000, False),  # unknown price
        (50.0, None, False),  # unknown shares
    ],
)
def test_liquid_needs_both_thresholds_and_known_values(price, shares, liquid):
    assert is_liquid(price, market_value(price, shares), CFG) is liquid


def test_measure_and_view_fields():
    result = measure("TINY", (2.0, "2026-11-17"), (10_000_000, date(2026, 9, 30)), CFG)
    assert result.market_value == 20_000_000 and result.liquid is False
    assert result.shares_as_of == "2026-09-30" and result.price_as_of == "2026-11-17"
    stored = {"price": 2.0, "market_value": 20_000_000.0, "price_as_of": "2026-11-17"}
    fields = liquidity_fields("late_filing_nt", stored, CFG)
    assert fields == {
        "price": 2.0,
        "price_as_of": "2026-11-17",
        "market_value": 20_000_000.0,
        "liquid": False,
        "liquidity_gated": True,
    }
    looser = DashboardConfig(avoid_min_price=1.0, avoid_min_market_value=10_000_000)
    assert liquidity_fields("late_filing_nt", stored, looser)["liquid"] is True
    unknown = liquidity_fields("cluster_buy", None, CFG)
    assert unknown["liquid"] is False and unknown["liquidity_gated"] is False


def test_shares_come_from_the_company_concept_cached_for_a_day(make_client, recorder):
    url = CONCEPT_URL.format(cik=777)
    recorder.add(url, json.dumps({"units": {"shares": [{"end": "2026-09-30", "val": 42}]}}))
    client = make_client()
    lookup = SharesLookup(client, today=lambda: TODAY)
    assert lookup.get("0000000777") == (42.0, date(2026, 9, 30))
    assert SharesLookup(client, today=lambda: TODAY).get("777") == (42.0, date(2026, 9, 30))
    assert recorder.urls().count(url) == 1  # the second lookup came from the disk cache

    assert lookup.get("888") is None  # no XBRL fact: remembered for the day
    assert lookup.get("888") is None
    assert recorder.urls().count(CONCEPT_URL.format(cik=888)) == 1
    assert lookup.get("not-a-cik") is None


class Closes(FakePrices):
    def __init__(self):
        super().__init__()
        self.close_calls = []

    def last_closes(self, symbols):
        self.close_calls.append(list(symbols))
        return {s: (12.5, "2026-11-17") for s in symbols if s != "NOPE"}


def test_latest_prices_use_quotes_then_cache_then_source(tmp_path):
    source = Closes()
    service = PriceService(source, Hub(), cache_dir=tmp_path, tracked=lambda: ["MP"])
    service.refresh()  # MP (and the indices) now have live quotes
    try:
        first = service.latest_prices(["MP", "TINY", "NOPE", "TINY", ""])
        assert first == {"MP": (100.0, "2026-11-17T16:00:00-05:00"), "TINY": (12.5, "2026-11-17")}
        assert source.close_calls == [["TINY", "NOPE"]]

        again = PriceService(source, Hub(), cache_dir=tmp_path)  # another run: disk cache
        assert again.latest_prices(["TINY"]) == {"TINY": (12.5, "2026-11-17")}
        assert source.close_calls == [["TINY", "NOPE"]]
        again.close()
    finally:
        service.close()


def test_latest_prices_fall_back_to_quotes_and_survive_a_failing_source(tmp_path):
    source = FakePrices()  # no last_closes: the quotes are used
    service = PriceService(source, Hub(), cache_dir=tmp_path)
    try:
        assert service.latest_prices(["ACME"]) == {"ACME": (100.0, "2026-11-17T16:00:00-05:00")}
        source.fail = True
        assert service.latest_prices(["OTHER"]) == {}
    finally:
        service.close()
