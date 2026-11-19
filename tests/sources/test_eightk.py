from __future__ import annotations

from datetime import date, timedelta

from radar.sources.efts import efts_url, months, parse_hits
from radar.sources.eightk.history import load_filings
from radar.sources.eightk.live import classify_text, filing_event
from radar.sources.eightk.rules import (
    AUDITOR_CHANGE_8K,
    BANKRUPTCY_8K,
    BUYBACK_8K,
    CEO_CFO_EXIT_8K,
    LATE_FILING_NT,
    Filing8K,
    classify,
    detect,
)
from radar.sources.eightk.text import (
    BUYBACK_PHRASES,
    items_from_header,
    items_from_summary,
    plain_text,
)
from radar.sources.feeds import fetch_items
from tests.conftest import FIXTURES

E8K = FIXTURES / "sources" / "eightk"


def _filing(**kw) -> Filing8K:
    base = dict(
        accession="0000000000-24-000001",
        form="8-K",
        cik="1",
        name="ACME",
        filing_date=date(2024, 1, 2),
        ticker="ACME",
    )
    base.update(kw)
    return Filing8K(**base)


def test_items_come_from_the_feed_summary():
    feed = (E8K / "feed_8k.atom.xml").read_bytes()
    items = fetch_items.__globals__["summaries"](feed)
    first = items["0001921963-26-000084"]
    assert items_from_summary(first) == ("7.01", "9.01")


def test_buyback_phrase_is_found_in_the_real_filing():
    raw = (E8K / "0001558370-24-001513.txt").read_text(encoding="latin-1")
    assert "8.01" in items_from_header(raw)
    filing = classify_text(_filing(items=items_from_header(raw)), raw)
    assert "authorized a share repurchase program" in filing.buyback_phrases
    assert "repurchase program" in filing.excerpt
    assert [s.type for s in classify(filing)] == [BUYBACK_8K]


def test_ceo_resignation_is_found_in_the_real_filing():
    raw = (E8K / "0001558370-24-002215.txt").read_text(encoding="latin-1")
    filing = classify_text(_filing(items=items_from_header(raw)), raw)
    assert "5.02" in filing.items
    assert filing.exit_titles == ("CEO",)
    signals = classify(filing)
    assert [s.type for s in signals] == [CEO_CFO_EXIT_8K]
    assert "CEO" in signals[0].explanation


def test_exit_phrase_without_item_502_is_ignored():
    raw = (E8K / "0001558370-24-002215.txt").read_text(encoding="latin-1")
    filing = classify_text(_filing(items=("8.01",)), raw)
    assert filing.exit_phrases == ()


def test_plain_text_drops_tags_and_entities():
    assert plain_text("<p>The Board&#160;has <b>Authorized</b>\n a  Share</p>") == (
        " the board has authorized a share "
    )


def test_item_and_form_rules():
    assert [s.type for s in classify(_filing(items=("1.03", "9.01")))] == [BANKRUPTCY_8K]
    assert [s.type for s in classify(_filing(items=("4.01",)))] == [AUDITOR_CHANGE_8K]
    assert [s.type for s in classify(_filing(form="NT 10-K"))] == [LATE_FILING_NT]
    assert classify(_filing(form="8-K/A", items=("1.03",))) == []
    assert classify(_filing(items=("5.02",))) == []  # 5.02 alone is not an exit


def test_cooldowns_per_type():
    d0 = date(2024, 1, 2)
    filings = [
        _filing(accession="a1", filing_date=d0, buyback_phrases=(BUYBACK_PHRASES[0],)),
        _filing(
            accession="a2",
            filing_date=d0 + timedelta(days=60),
            buyback_phrases=(BUYBACK_PHRASES[0],),
        ),  # within 90 days
        _filing(
            accession="a3",
            filing_date=d0 + timedelta(days=95),
            buyback_phrases=(BUYBACK_PHRASES[0],),
        ),
        _filing(accession="b1", form="NT 10-Q", filing_date=d0),
        _filing(accession="b2", form="NT 10-Q", filing_date=d0 + timedelta(days=31)),
    ]
    signals = detect(filings)
    assert [(s.type, s.trigger_accession) for s in signals] == [
        (BUYBACK_8K, "a1"),
        (LATE_FILING_NT, "b1"),
        (LATE_FILING_NT, "b2"),
        (BUYBACK_8K, "a3"),
    ]


def test_live_prior_signals_block_repeats():
    filing = _filing(form="NT 10-K")
    prior = {(LATE_FILING_NT, "1"): [filing.filing_date - timedelta(days=10)]}
    assert detect([filing], prior_signals=prior) == []


def test_event_shape():
    event = filing_event(_filing(items=("2.02", "9.01")), "https://example")
    assert event.kind == "8k"
    assert "earnings" in event.data["flags"]
    assert event.title.startswith("8-K · Results of operations")


def test_month_windows():
    windows = list(months(date(2024, 1, 15), date(2024, 3, 2)))
    assert windows == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 2)),
    ]


def test_history_merges_rules_by_accession(make_client, recorder):
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    empty = b'{"hits": {"total": {"value": 0}, "hits": []}}'
    recorder.add("https://efts.sec.gov/LATEST/search-index*", empty)
    recorder.add(
        efts_url(forms="8-K", start=start, end=end, q='"Item 1.03"'),
        (E8K / "efts_item_1.03_2024-01.json").read_bytes(),
    )
    filings, stats = load_filings(make_client(), start, end)
    _, hits = parse_hits((E8K / "efts_item_1.03_2024-01.json").read_bytes())
    expected = {h.accession for h in hits if h.form == "8-K" and "1.03" in h.items}
    assert {f.accession for f in filings} == expected
    assert stats.by_rule["item_1.03"] >= len(expected)
    assert all(s.type == BANKRUPTCY_8K for s in detect(filings))
