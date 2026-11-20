"""Press releases from 8-K EX-99 exhibits and the Tiingo News permission state.

Fixtures are real EDGAR documents of 2026-11-19 (the Ames National submission is
trimmed to its header, a stub 8-K and the EX-99.1). No network.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import httpx
import pytest

from radar.config import NewsConfig
from radar.feed import feed_url
from radar.forward import ForwardLog, ForwardRecorder
from radar.sources.base import EIGHTK, NEWS
from radar.sources.eightk.live import EightKSource
from radar.sources.news.exhibits import (
    EVENT_KIND,
    FEED,
    FilingInfo,
    PressReleaseCollector,
    exhibit_item,
    headline,
    parse_index,
    submission_exhibits,
    text_lines,
)
from radar.sources.news.live import store_item
from radar.sources.news.matching import FILING, Match
from radar.sources.news.model import NewsItem
from radar.sources.runner import SourceContext, SourceRunner, press_release_collector
from radar.sources.short.history import FinraClient
from radar.sources.store import SourceStore
from radar.sources.views import company_context
from tests.conftest import FIXTURES

SEC8K = FIXTURES / "sources" / "news" / "sec8k"
NOW = datetime(2026, 11, 20, 1, 52, 51, tzinfo=UTC)

AMES = ("0001437749-26-037728", "1132651", "AMES NATIONAL CORP", "2026-11-19T16:11:50-05:00")
GRANITE = (
    "0001928446-26-000070",
    "1928446",
    "Granite Ridge Resources, Inc.",
    "2026-11-19T17:25:25-05:00",
)
TICKERS = {"1132651": "ATLO", "1928446": "GRNT"}


def _folder(accession: str, cik: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"


def _index(accession: str, cik: str) -> str:
    return f"{_folder(accession, cik)}{accession}-index.htm"


def _info(filing=GRANITE, items=("8.01", "9.01")) -> FilingInfo:
    accession, cik, name, accepted = filing
    return FilingInfo(
        accession=accession,
        form="8-K",
        cik=cik,
        name=name,
        ticker=TICKERS[cik],
        index_url=_index(accession, cik),
        accepted_at=datetime.fromisoformat(accepted),
        items=items,
    )


def _entry(filing, items: list[tuple[str, str]]) -> str:
    accession, cik, name, accepted = filing
    lines = "".join(f"\n&lt;br&gt;Item {code}: {label}" for code, label in items)
    return f"""<entry>
<title>8-K - {name} ({cik.zfill(10)}) (Filer)</title>
<link rel="alternate" type="text/html" href="{_index(accession, cik)}"/>
<summary type="html">
 &lt;b&gt;Filed:&lt;/b&gt; 2026-11-19 &lt;b&gt;AccNo:&lt;/b&gt; {accession} &lt;b&gt;Size:&lt;/b&gt; 180 KB{lines}
</summary>
<updated>{accepted}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
<id>urn:tag:sec.gov,2008:accession-number={accession}</id>
</entry>"""


def _feed(*entries: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="ISO-8859-1" ?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "<title>Latest Filings</title>\n" + "".join(entries) + "\n</feed>\n"
    ).encode("latin-1")


def _context(client, store: SourceStore, tmp_path) -> SourceContext:
    finra = FinraClient(
        tmp_path / "finra", transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    return SourceContext(
        client=client,
        store=store,
        finra=finra,
        today=date(2026, 11, 19),
        ticker_for=lambda cik: TICKERS.get(cik, ""),
        registrant=lambda symbol: None,
        prior_signal_dates=lambda kind, cik: [],
        momentum=lambda ticker, day: None,
        shares_outstanding=lambda cik, day: None,
        resolve_cusip=lambda cusip, day: None,
    )


def _routes(recorder, *, granite_items=(("3.02", "Unregistered Sales"), ("9.01", "Exhibits"))):
    recorder.add(
        feed_url("8-K", count=100),
        _feed(
            _entry(AMES, [("8.01", "Other Events"), ("9.01", "Financial Statements")]),
            _entry(GRANITE, list(granite_items)),
        ),
    )
    recorder.add(
        f"{_folder(AMES[0], AMES[1])}{AMES[0]}.txt",
        (SEC8K / f"{AMES[0]}.txt").read_bytes(),
    )
    recorder.add(_index(*GRANITE[:2]), (SEC8K / f"{GRANITE[0]}-index.htm").read_bytes())
    recorder.add(
        f"{_folder(GRANITE[0], GRANITE[1])}grnt-20261119xexx991.htm",
        (SEC8K / f"{GRANITE[0]}_ex991.htm").read_bytes(),
    )


def _collector(**kw) -> PressReleaseCollector:
    return PressReleaseCollector(now=lambda: NOW, **kw)


# ------------------------------------------------------------------ parsing


def test_index_page_lists_the_ex99_documents():
    exhibits = parse_index((SEC8K / f"{GRANITE[0]}-index.htm").read_text())
    assert [(e.type, e.filename, e.size) for e in exhibits] == [
        ("EX-99.1", "grnt-20261119xexx991.htm", 8774)
    ]
    assert exhibits[0].url == f"{_folder(*GRANITE[:2])}grnt-20261119xexx991.htm"


def test_submission_text_yields_the_exhibit_and_its_url():
    raw = (SEC8K / f"{AMES[0]}.txt").read_text(encoding="latin-1")
    [(exhibit, body)] = submission_exhibits(raw, _folder(*AMES[:2]))
    assert exhibit.type == "EX-99.1"
    assert exhibit.url == f"{_folder(*AMES[:2])}{exhibit.filename}"
    assert exhibit.filename.endswith(".htm") and "<TYPE>" not in body


@pytest.mark.parametrize(
    ("fixture", "company", "expected"),
    [
        # Headline after "Exhibit 99.1"; the summary starts with the dateline.
        (
            f"{GRANITE[0]}_ex991.htm",
            GRANITE[2],
            "Granite Ridge Resources, Inc. Announces Planned Grey Rock Share Distribution",
        ),
        # Exhibit number, headline and dateline glued in one block.
        (
            "0000932696-26-000089_ex991.htm",
            "INSIGHT ENTERPRISES INC",
            "Insight Announces Offering of Convertible Senior Notes",
        ),
        # Words of the headline broken over source lines.
        (
            "0001493152-26-053323_ex991.htm",
            "Arrive AI Inc.",
            "Arrive AI Eliminates All Debt Through Preferred Equity Exchange",
        ),
    ],
)
def test_headline_is_the_first_real_title_line(fixture, company, expected):
    lines = text_lines((SEC8K / fixture).read_text(encoding="utf-8", errors="replace"))
    title, start = headline(lines, company)
    assert title == expected
    assert start > 0 and lines[start:]


def test_contact_block_before_the_headline_is_skipped():
    raw = (SEC8K / f"{AMES[0]}.txt").read_text(encoding="latin-1")
    [(_, body)] = submission_exhibits(raw, _folder(*AMES[:2]))
    title, _ = headline(text_lines(body), AMES[2])
    assert title == "AMES NATIONAL CORPORATION DECLARED CASH DIVIDEND"
    lines = ["Contact:", "John Doe", "(515) 232-6251", "jdoe@example.com", "ACME Corp. Announces"]
    assert headline(lines + ["Record Results"], "ACME Corp")[0] == (
        "ACME Corp. Announces Record Results"
    )


def test_exhibit_item_carries_filing_times_and_plain_text():
    body = (SEC8K / f"{GRANITE[0]}_ex991.htm").read_text()
    [exhibit] = parse_index((SEC8K / f"{GRANITE[0]}-index.htm").read_text())
    item = exhibit_item(_info(), exhibit, body, summary_max=300)
    assert item.feed == FEED == "sec-8k-ex99"
    assert item.published_at == datetime(2026, 11, 19, 22, 25, 25, tzinfo=UTC)
    assert item.summary.startswith("Dallas, Texas, November 19, 2026")
    assert len(item.summary) <= 300 and "<" not in item.summary
    assert item.extra["accession"] == GRANITE[0] and item.extra["exhibit"] == "EX-99.1"
    # No headline at all: the title falls back to the company and the exhibit.
    bare = exhibit_item(_info(), exhibit, "<html><body><p>123</p></body></html>")
    assert bare.title == f"{GRANITE[2]}: EX-99.1"


# ------------------------------------------------------------------- 8-K poll


def test_eightk_poll_stores_press_releases_as_news(make_client, recorder, tmp_path):
    _routes(recorder)
    store = SourceStore(sqlite3.connect(":memory:"))
    client = make_client()
    source = EightKSource(press_releases=_collector())
    result = source.poll(_context(client, store, tmp_path))

    news = store.recent_news()
    assert {r["feed"] for r in news} == {FEED}
    by_ticker = {r["tickers"][0]: r for r in news}
    assert set(by_ticker) == {"ATLO", "GRNT"}
    ames = by_ticker["ATLO"]
    assert ames["title"] == "AMES NATIONAL CORPORATION DECLARED CASH DIVIDEND"
    assert ames["published_at"] == "2026-11-19T21:11:50+00:00"  # SEC acceptance, in UTC
    assert ames["seen_at"] == NOW.isoformat()
    assert ames["ciks"] == ["1132651"] and ames["matches"][0]["method"] == FILING
    assert "dividend" in ames["tags"]
    assert by_ticker["GRNT"]["url"].endswith("grnt-20261119xexx991.htm")

    # Forward-log records per feed, and one news event per release.
    assert {(r["kind"], r["source"]) for r in result.records} == {("news", FEED)}
    releases = [e for e in result.events if e.source == NEWS]
    assert {e.kind for e in releases} == {EVENT_KIND}
    assert {e.ticker for e in releases} == {"ATLO", "GRNT"}
    assert all(e.event_date == date(2026, 11, 19) and e.seen_at == NOW for e in releases)
    assert {e.source for e in result.events} == {EIGHTK, NEWS}
    assert "2 press release(s)" in result.note

    # Ames came from the submission already downloaded; Granite Ridge (items with no
    # text rule) cost its index page and one exhibit.
    urls = recorder.urls()
    assert sum(u.endswith(".txt") for u in urls) == 1
    assert sum(u.endswith("-index.htm") for u in urls) == 1
    assert source.health()["stored"] == 2 and source.health()["pending"] == 0


def test_index_reads_are_capped_per_poll_and_resumed(make_client, recorder, tmp_path):
    _routes(recorder)
    store = SourceStore(sqlite3.connect(":memory:"))
    source = EightKSource(press_releases=_collector(filings_per_poll=0))
    ctx = _context(make_client(), store, tmp_path)
    source.poll(ctx)
    assert [r["tickers"] for r in store.recent_news()] == [["ATLO"]]
    assert source.press_releases.pending() == 1
    assert not any(u.endswith("-index.htm") for u in recorder.urls())

    source.press_releases.filings_per_poll = 5
    again = source.poll(ctx)  # the waiting filing is read now (and queued only once)
    assert [e.ticker for e in again.events if e.source == NEWS] == ["GRNT"]
    assert source.press_releases.pending() == 0


def test_filings_without_item_901_cost_no_index(make_client, recorder, tmp_path):
    _routes(recorder, granite_items=(("5.07", "Shareholder vote"),))
    source = EightKSource(press_releases=_collector())
    source.poll(_context(make_client(), SourceStore(sqlite3.connect(":memory:")), tmp_path))
    assert not any(u.endswith("-index.htm") for u in recorder.urls())


def test_press_releases_are_off_without_the_setting():
    assert press_release_collector(None) is None
    assert press_release_collector(NewsConfig(sec_exhibits=False)) is None
    collector = press_release_collector(NewsConfig(sec_exhibits_per_filing=2))
    assert collector is not None and collector.per_filing == 2


def test_an_official_copy_is_kept_when_a_wire_had_the_headline():
    ctx = type("Ctx", (), {})()
    ctx.store = SourceStore(sqlite3.connect(":memory:"))
    from radar.sources.base import PollResult

    title = "Granite Ridge Resources, Inc. Announces Planned Grey Rock Share Distribution"
    wire = NewsItem(feed="prnewswire", url="https://www.prnewswire.com/a", title=title)
    official = NewsItem(feed=FEED, url="https://www.sec.gov/Archives/x/ex991.htm", title=title)
    match = [Match("GRNT", "1928446", "Granite Ridge", FILING)]
    result = PollResult()
    assert store_item(ctx, wire, NOW, result, matches=[])
    assert store_item(ctx, official, NOW, result, matches=match, dedupe_title=False)
    # A wire copy after the official one is still deduped by headline.
    late = NewsItem(feed="prnewswire", url="https://www.prnewswire.com/b", title=title)
    assert not store_item(ctx, late, NOW, result, matches=[])


def test_runner_logs_press_releases_and_shows_them_in_the_context(make_client, recorder, tmp_path):
    _routes(recorder)
    conn = sqlite3.connect(":memory:")
    log_ = ForwardLog(tmp_path / "forward")
    source = EightKSource(press_releases=_collector())
    runner = SourceRunner(
        conn, make_client(), sources=[source], recorder=ForwardRecorder(log_, conn=conn)
    )
    runner.context = lambda: _context(runner.client, runner.store, tmp_path)  # type: ignore[method-assign]
    runner.tick(force=True)

    records = list(log_.read(NOW.date()))
    assert sum(r["kind"] == "news" and r["source"] == FEED for r in records) == 2
    assert any(r["kind"] == "event" and r["data"]["kind"] == EVENT_KIND for r in records)
    status = next(s for s in runner.statuses() if s["name"] == EIGHTK)
    assert status["detail"]["stored"] == 2

    context = company_context(runner.store, "1132651", "ATLO", today=date(2026, 11, 20))
    assert [e["kind"] for e in context[NEWS]] == [EVENT_KIND]
