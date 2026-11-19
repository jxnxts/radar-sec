from __future__ import annotations

import json
from datetime import date

from radar.sources.short.data import (
    CusipMap,
    Fail,
    ShortInterest,
    ftd_available_date,
    ftd_links,
    parse_ftd,
    parse_short_interest,
    parse_short_volume,
    publication_date,
)
from radar.sources.short.rules import (
    FTD_PERSISTENT,
    SHORT_CROWDED,
    SQUEEZE_SETUP,
    crowded_shorts,
    persistent_fails,
    squeeze_candidates,
    squeezes,
)
from tests.conftest import FIXTURES

SHORT = FIXTURES / "sources" / "short"


def registrant(symbol: str):
    return {"ACME": ("1", "ACME", "Acme Corp"), "AAPL": ("320193", "AAPL", "Apple Inc.")}.get(
        symbol
    )


def _si(**kw) -> ShortInterest:
    base = dict(
        symbol="ACME",
        name="Acme Corp Common Stock",
        settlement_date=date(2024, 1, 12),
        market="NNM",
        short_shares=5e6,
        previous_short_shares=3e6,
        avg_daily_volume=5e5,
        days_to_cover=10.0,
        change_pct=None,
    )
    base.update(kw)
    return ShortInterest(**base)


def test_parses_finra_short_interest():
    records = parse_short_interest(
        json.loads((SHORT / "finra_short_interest_sample.json").read_text())
    )
    aapl = next(r for r in records if r.symbol == "AAPL")
    assert aapl.listed and not aapl.fund_like
    assert aapl.settlement_date == date(2024, 1, 12)
    assert aapl.short_shares > 0 and aapl.days_to_cover is not None
    otc = [r for r in records if r.market == "OTC"]
    assert otc and not any(r.listed for r in otc)


def test_fund_names_are_excluded():
    assert _si(name="SPDR S&P 500 ETF Trust").fund_like
    assert _si(name="ProShares UltraPro QQQ").fund_like
    assert not _si(name="Acme Corp Common Stock").fund_like


def test_publication_date_is_ten_business_days_later():
    assert publication_date(date(2024, 1, 12)) == date(2024, 1, 26)
    assert publication_date(date(2024, 1, 31)) == date(2024, 2, 14)


def test_crowded_short_rule():
    public = publication_date
    assert [s.type for s in crowded_shorts([_si()], registrant, public)] == [SHORT_CROWDED]
    assert crowded_shorts([_si(days_to_cover=6.9)], registrant, public) == []
    assert crowded_shorts([_si(previous_short_shares=4.5e6)], registrant, public) == []  # +11%
    assert (
        crowded_shorts([_si(short_shares=9e5, previous_short_shares=5e5)], registrant, public) == []
    )
    assert crowded_shorts([_si(market="OTC")], registrant, public) == []
    assert crowded_shorts([_si(symbol="ZZZZ")], registrant, public) == []  # not a registrant
    signal = crowded_shorts([_si()], registrant, public)[0]
    assert signal.signal_date == date(2024, 1, 26)
    assert signal.issuer_cik == "1"


def test_squeeze_rule_needs_covering_and_price_momentum():
    covering = _si(short_shares=2e6, previous_short_shares=3e6)
    candidates = squeeze_candidates([covering, _si()], registrant)
    assert [c[0] for c in candidates] == [covering]
    fired = squeezes(candidates, publication_date, lambda ticker, day: 0.25)
    assert [s.type for s in fired] == [SQUEEZE_SETUP]
    assert fired[0].details["momentum"] == 0.25
    assert squeezes(candidates, publication_date, lambda ticker, day: 0.19) == []
    assert squeezes(candidates, publication_date, lambda ticker, day: None) == []


def test_parses_short_volume_file():
    rows = parse_short_volume((SHORT / "CNMSshvol20240102.txt").read_text())
    first = rows[0]
    assert first.symbol == "A" and first.day == date(2024, 1, 2)
    assert 0 < first.ratio < 1


def test_parses_fails_file_and_skips_the_trailer():
    fails = parse_ftd((SHORT / "cnsfails202401a_sample.txt").read_bytes())
    assert fails and all(f.cusip and f.symbol for f in fails)
    assert {f.symbol for f in fails} <= {"GME", "AAPL", "MULN", "AMC", "ADNT"}
    zipped = parse_ftd(
        b"SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
        b"20240102|000000000|X|10|X CORP|.\nTrailer record count 1\n"
    )
    assert len(zipped) == 1 and zipped[0].price is None


def test_ftd_links_follow_irregular_paths():
    html = (
        '<a href="/files/data/fails-deliver-data/cnsfails202401a.zip">a</a>'
        '<a href="/files/node/add/data_distribution/cnsfails202002b.zip">b</a>'
        '<a href="/files/data/other/fails-deliver-data/cnsfails202308b_0.zip">c</a>'
    )
    links = ftd_links(html)
    assert links[(2024, 1, "a")].endswith("/fails-deliver-data/cnsfails202401a.zip")
    assert links[(2020, 2, "b")].startswith("https://www.sec.gov/files/node/add/")
    assert links[(2023, 8, "b")].endswith("cnsfails202308b_0.zip")


def test_ftd_availability_is_conservative():
    assert ftd_available_date(2024, 1, "a", None) == date(2024, 2, 3)
    assert ftd_available_date(2024, 1, "b", None) == date(2024, 2, 18)
    assert ftd_available_date(2024, 1, "a", date(2024, 2, 9)) == date(2024, 2, 9)


def _fail(day: int, qty: float, symbol: str = "ACME") -> Fail:
    return Fail(date(2024, 1, day), "000000001", symbol, qty, "ACME CORP", 2.0)


def test_persistent_fails_need_five_consecutive_days():
    days = [2, 3, 4, 5, 8, 9, 10]  # the file's settlement calendar
    calendar = [_fail(d, 1, "AAPL") for d in days]
    over = [_fail(d, 60_000) for d in (2, 3, 4, 5, 8)]  # 5 in a row, 0.6% of 10 mi
    signals = persistent_fails(
        calendar + over, date(2024, 2, 3), registrant, lambda cik, day: 10_000_000.0, file_name="f"
    )
    assert [s.type for s in signals] == [FTD_PERSISTENT]
    assert signals[0].details["run_days"] == 5
    broken = [_fail(d, 60_000) for d in (2, 3, 4, 8, 9)]  # gap on day 5
    assert (
        persistent_fails(
            calendar + broken, date(2024, 2, 3), registrant, lambda cik, day: 10_000_000.0
        )
        == []
    )
    small = [_fail(d, 40_000) for d in (2, 3, 4, 5, 8)]  # 0.4%: below the threshold
    assert (
        persistent_fails(
            calendar + small, date(2024, 2, 3), registrant, lambda cik, day: 10_000_000.0
        )
        == []
    )


def test_cusip_map_keeps_the_latest_symbol():
    cusips = CusipMap()
    cusips.add(
        [
            Fail(date(2021, 1, 4), "30303M102", "FB", 1, "", None),
            Fail(date(2023, 1, 4), "30303M102", "META", 1, "", None),
        ]
    )
    assert cusips.symbol("30303M102") == "META"
    assert cusips.symbol("unknown") == ""
