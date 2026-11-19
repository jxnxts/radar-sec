"""News source: feed parsing, dedupe, ticker matching, tags, the polite client and the
poller, on feeds recorded from the real wires. No network."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime

import httpx
import pytest

from radar.config import NewsConfig
from radar.sources.base import NEWS
from radar.sources.news.client import NewsClient, NewsHttpError
from radar.sources.news.feeds import (
    WIRES,
    FeedFormatError,
    gdelt_url,
    parse_gdelt,
    parse_rss,
    parse_tiingo,
)
from radar.sources.news.live import GdeltFeed, NewsSource, TiingoFeed, WireFeed, build_feeds
from radar.sources.news.matching import (
    EXCHANGE,
    NAME,
    PROVIDER,
    CompanyIndex,
    explicit_tickers,
    match_companies,
    name_core,
)
from radar.sources.news.model import canonical_url, dedupe_key, parse_time
from radar.sources.news.tags import tag
from radar.sources.registry import Registry
from radar.sources.runner import SourceRunner
from radar.sources.store import SourceStore
from radar.sources.views import company_context, event_view
from tests.conftest import FIXTURES

NEWS_DIR = FIXTURES / "sources" / "news"
PRN = WIRES["prnewswire"].url
BW = WIRES["businesswire"].url
NOW = datetime(2026, 11, 19, 22, 25, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry(json.loads((NEWS_DIR / "company_tickers.json").read_text()))


@pytest.fixture(scope="module")
def index(registry) -> CompanyIndex:
    return CompanyIndex(registry)


class Ctx:
    def __init__(self, registry: Registry | None, conn=None):
        self.store = SourceStore(conn or sqlite3.connect(":memory:"))
        self.registry = registry
        self.today = date(2026, 11, 19)


def _client(handler) -> NewsClient:
    return NewsClient(
        user_agent="radar-sec tests",
        min_host_interval=0.001,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )


def _routes(routes: dict[str, object], calls: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        url = str(request.url)
        for prefix, answer in routes.items():
            if url.startswith(prefix):
                if callable(answer):
                    return answer(request)
                if isinstance(answer, httpx.Response):
                    return answer
                return httpx.Response(200, content=answer)
        return httpx.Response(404)

    return handler


# ------------------------------------------------------------------ parsing


def test_pr_newswire_rss_is_parsed_with_plain_text_and_utc_times():
    items = parse_rss((NEWS_DIR / "prnewswire.rss.xml").read_bytes(), "prnewswire")
    assert len(items) == 20
    first = items[0]
    assert first.title.startswith("Mimic Virtual Patching")
    assert first.url.startswith("https://www.prnewswire.com/news-releases/")
    assert "<p>" not in first.summary and first.summary
    assert first.published_at == datetime(2026, 11, 19, 22, 5, tzinfo=UTC)
    assert first.published_raw == "Thu, 19 Nov 2026 22:05:00 +0000"


def test_business_wire_rss_keeps_only_english_releases():
    raw = parse_rss((NEWS_DIR / "businesswire.rss.xml").read_bytes(), "businesswire")
    feed = WireFeed(WIRES["businesswire"], 300)
    kept = feed.fetch(_client(_routes({BW: (NEWS_DIR / "businesswire.rss.xml").read_bytes()})))
    assert len(raw) == 40 and 0 < len(kept) < len(raw)
    assert all("/en/" in item.url for item in kept)
    assert kept[0].published_at == datetime(2026, 11, 19, 21, 56, tzinfo=UTC)  # "UT" zone


def test_atom_feeds_are_parsed_too():
    atom = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Acme Widgets, Inc. Reports Third Quarter Results</title>
        <link rel="alternate" href="https://example.com/acme-q3"/>
        <published>2026-11-19T13:00:00-05:00</published>
        <summary>Acme (NYSE: ACME) reported results.</summary></entry>
    </feed>"""
    [item] = parse_rss(atom, "custom")
    assert item.url == "https://example.com/acme-q3"
    assert item.published_at == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)


def test_error_pages_are_not_taken_for_feeds():
    with pytest.raises(FeedFormatError):
        parse_rss(b"<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD></HTML>", "globenewswire")
    with pytest.raises(FeedFormatError):
        parse_gdelt(b"Please limit requests to one every 5 seconds.")
    with pytest.raises(FeedFormatError):
        parse_tiingo(b'{"detail": "Invalid token."}')
    assert parse_gdelt(b"") == []


def test_gdelt_and_tiingo_answers():
    gdelt = parse_gdelt((NEWS_DIR / "gdelt_artlist.json").read_bytes())
    assert [i.feed for i in gdelt] == ["gdelt", "gdelt"]
    assert gdelt[0].published_at == datetime(2026, 11, 19, 21, 45, tzinfo=UTC)
    assert gdelt[0].extra["domain"] == "example-news.com"
    url = gdelt_url("(NYSE OR NASDAQ) sourcelang:english", max_records=50, timespan="1h")
    assert "mode=artlist" in url and "format=json" in url and "timespan=1h" in url

    tiingo = parse_tiingo((NEWS_DIR / "tiingo_news.json").read_bytes())
    assert tiingo[0].provider_tickers == ("BKU",)
    assert tiingo[0].extra["crawled_at"] == "2026-11-19T21:20:11.123Z"


def test_timestamps_in_every_feed_format():
    assert parse_time("Thu, 19 Nov 2026 21:56:00 UT") == datetime(2026, 11, 19, 21, 56, tzinfo=UTC)
    assert parse_time("20261119T214500Z") == datetime(2026, 11, 19, 21, 45, tzinfo=UTC)
    assert parse_time("2026-11-19T21:30:00Z") == datetime(2026, 11, 19, 21, 30, tzinfo=UTC)
    assert parse_time("not a date") is None and parse_time("") is None


def test_canonical_url_and_dedupe_key():
    a = "http://www.businesswire.com/news/home/2026/en/Acme/?feedref=XYZ&utm_source=rss#top"
    b = "https://businesswire.com/news/home/2026/en/Acme"
    assert canonical_url(a) == canonical_url(b) == "https://businesswire.com/news/home/2026/en/Acme"
    assert canonical_url("https://x.com/a?id=2&utm_medium=x") == "https://x.com/a?id=2"
    assert dedupe_key(a, "Acme  Reports Results!") == dedupe_key(b, "acme reports results")
    assert dedupe_key(a, "Acme Reports Results") != dedupe_key(a, "Acme Reports Other Results")


# ----------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Matador Resources Company (NYSE: MTDR) today", [("NYSE", "MTDR")]),
        ("(NASDAQ:GH) and (Nasdaq: CODX)", [("NASDAQ", "GH"), ("Nasdaq", "CODX")]),
        ("Mesa Royalty Trust (NYSE symbol-MTR) announced", [("NYSE", "MTR")]),
        ("Berkshire (NYSE: BRK.B) said", [("NYSE", "BRK-B")]),
        ("listed on Nasdaq GS: ABCD", [("Nasdaq GS", "ABCD")]),
        ("Acme (TSX: ACM) and (LSE: ACM)", []),
        ("the NYSE: a venue", []),
    ],
)
def test_explicit_exchange_tickers(text, expected):
    assert explicit_tickers(text) == expected


def test_name_cores_ignore_suffixes_and_state_tags():
    assert name_core("Matador Resources Co") == name_core("Matador Resources Company")
    assert name_core("LENNAR CORP /NEW/") == "lennar"
    assert name_core("Amazon.com, Inc.") == "amazon com"
    assert name_core("The Walt Disney Company") == "walt disney"


def test_matching_prefers_explicit_tickers_and_never_guesses(index):
    def tickers(title, summary="", provider=()):
        return [(m.ticker, m.method) for m in match_companies(index, title, summary, provider)]

    assert tickers("Matador Resources Company Announces Closing", "Matador (NYSE: MTDR)") == [
        ("MTDR", EXCHANGE)
    ]
    # An explicit ticker the registry does not know is dropped, not guessed.
    assert tickers("Unknown Corp (NASDAQ: ZZZZQ) rises") == []
    # Company names only with a corporate suffix, and only exact registrant names.
    assert tickers("INVESTOR DEADLINE: Lennar Corporation (LEN) Investors") == [("LEN", NAME)]
    assert tickers("Apple said its phones sell well") == []
    assert tickers("Apple Inc. said its phones sell well") == [("AAPL", NAME)]
    # A longer name that is not a registrant does not shrink into another one.
    assert tickers("National Capital Bancorp, Inc. Announces Approval") == []
    assert tickers("Securities Class Action Against Capital Bancorp, Inc.") == [("CBNK", NAME)]
    # Provider tickers count only when the registry knows them.
    assert tickers("Buyback news", provider=("BKU", "ZZZZ")) == [("BKU", PROVIDER)]
    # One match per company even if named twice.
    assert tickers("Apple Inc. (NASDAQ: AAPL) and Apple Inc. again") == [("AAPL", EXCHANGE)]


def test_matching_on_the_recorded_wires(index):
    items = parse_rss((NEWS_DIR / "prnewswire.rss.xml").read_bytes(), "prnewswire")
    matched = {
        i.title[:30]: [m.ticker for m in match_companies(index, i.title, i.summary)] for i in items
    }
    hits = {k: v for k, v in matched.items() if v}
    assert hits == {
        "HAMILTON BEACH BRANDS HOLDING ": ["HBB"],
        "John Forsyth, Cirrus Logic Pre": ["CRUS"],
        "Co-Diagnostics Announces Rever": ["CODX"],
        "ODNB Financial Corporation and": ["NACB"],
        "First Horizon Bank Celebrates ": ["FHN"],
    }


# --------------------------------------------------------------------- tags


@pytest.mark.parametrize(
    ("title", "summary", "expected"),
    [
        (
            "Geospace Technologies Reports Fourth Quarter and Fiscal Year 2026 Results",
            "",
            ["earnings"],
        ),
        (
            "Grandstand Reports Third Quarter Results, Updates 2026 Guidance",
            "",
            ["earnings", "guidance"],
        ),
        ("Rockwell Automation Signs Definitive Agreement to Acquire AGILOX", "", ["mna"]),
        (
            "Everforth, Inc. Announces Withdrawal of Proposed Senior Notes Offering",
            "",
            ["offering"],
        ),
        ("BankUnited, Inc. Increases Share Repurchase Program", "", ["buyback"]),
        ("Acme Receives FDA Approval for Widgetmab", "", ["fda"]),
        ("Securities Class Action Filed Against Build-A-Bear Workshop, Inc.", "", ["lawsuit"]),
        ("HF Sinclair Appoints Shawn J. Carsten as Chief Financial Officer", "", ["exec_change"]),
        ("Acme CEO to Step Down at Year End", "", ["exec_change"]),
        ("Carter's, Inc. Announces Quarterly Dividend", "", ["dividend"]),
        ("Floor & Decor Opens New Store in Porter Ranch, California", "", []),
        ("Acme expands its product offering", "", []),
    ],
)
def test_keyword_tags(title, summary, expected):
    assert tag(title, summary) == expected


# ------------------------------------------------------------------- client


def test_client_sends_conditional_requests_and_reads_304():
    calls: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"<rss/>", headers={"ETag": '"v1"'})

    client = _client(_routes({PRN: answer}, calls))
    assert client.get(PRN) == b"<rss/>"
    assert client.get(PRN) is None
    assert calls[0].headers["User-Agent"] == "radar-sec tests"
    assert "If-None-Match" not in calls[0].headers and calls[1].headers["If-None-Match"] == '"v1"'


def test_client_backs_off_a_host_that_refuses():
    now = [1000.0]
    calls: list[httpx.Request] = []
    client = NewsClient(
        user_agent="t",
        min_host_interval=0.001,
        transport=httpx.MockTransport(
            _routes(
                {
                    "https://api.gdeltproject.org": httpx.Response(
                        429, headers={"Retry-After": "120"}
                    )
                },
                calls,
            )
        ),
        clock=lambda: now[0],
        sleep=lambda s: None,
    )
    url = gdelt_url("NYSE")
    with pytest.raises(NewsHttpError) as first:
        client.get(url)
    assert first.value.status_code == 429
    with pytest.raises(NewsHttpError, match="paused"):
        client.get(url)
    assert len(calls) == 1  # the paused host was not asked again
    now[0] += 121
    with pytest.raises(NewsHttpError):
        client.get(url)
    assert len(calls) == 2


def test_wires_respect_robots_txt():
    robots = (NEWS_DIR / "businesswire_robots.txt").read_bytes()
    calls: list[httpx.Request] = []
    client = _client(
        _routes(
            {
                "https://feed.businesswire.com/robots.txt": robots,
                BW: (NEWS_DIR / "businesswire.rss.xml").read_bytes(),
                PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes(),
            },
            calls,
        )
    )
    assert not client.allowed(BW)
    with pytest.raises(NewsHttpError, match="robots.txt"):
        WireFeed(WIRES["businesswire"], 300).fetch(client)
    assert BW not in [str(c.url) for c in calls]  # the feed itself was never requested
    # No robots.txt (404) allows everything; robots.txt is read once per host.
    assert WireFeed(WIRES["prnewswire"], 300).fetch(client)
    WireFeed(WIRES["prnewswire"], 300).fetch(client)
    robots_calls = [str(c.url) for c in calls if str(c.url).endswith("/robots.txt")]
    assert robots_calls == [
        "https://feed.businesswire.com/robots.txt",
        "https://www.prnewswire.com/robots.txt",
    ]
    # A server error on robots.txt means "not now", not "allowed".
    broken = _client(_routes({"https://www.prnewswire.com/robots.txt": httpx.Response(503)}))
    with pytest.raises(NewsHttpError, match="trying later"):
        WireFeed(WIRES["prnewswire"], 300).fetch(broken)


def test_client_spaces_requests_to_the_same_host():
    sleeps: list[float] = []
    client = NewsClient(
        user_agent="t",
        min_host_interval=5.0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")),
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )
    client.get("https://a.example/1")
    client.get("https://b.example/1")
    client.get("https://a.example/2")
    assert sleeps == [5.0]


# ------------------------------------------------------------------- poller


def _source(routes, *, feeds=None, now=NOW, scorer=None, clock=None) -> NewsSource:
    config = NewsConfig()
    return NewsSource(
        config,
        client=_client(_routes(routes)),
        feeds=feeds
        if feeds is not None
        else [WireFeed(WIRES["prnewswire"], 300), WireFeed(WIRES["businesswire"], 300)],
        now=lambda: now,
        scorer=scorer,
        clock=clock or (lambda: 0.0),
    )


def test_poller_stores_every_item_and_emits_events_for_matches(registry):
    routes = {
        PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes(),
        BW: (NEWS_DIR / "businesswire.rss.xml").read_bytes(),
    }
    ctx = Ctx(registry)
    result = _source(routes).poll(ctx)

    stored = ctx.store.count_news()
    assert stored["prnewswire"] == 20 and 0 < stored["businesswire"] <= 17
    assert len(result.records) == sum(stored.values())
    assert all(r["kind"] == "news" and r["seen_at"] == NOW.isoformat() for r in result.records)
    assert {r["source"] for r in result.records} == {"prnewswire", "businesswire"}

    by_ticker = {e.ticker: e for e in result.events}
    mtdr = by_ticker["MTDR"]
    assert mtdr.source == NEWS and mtdr.kind == "news" and mtdr.seen_at == NOW
    assert mtdr.issuer_cik and mtdr.event_date == date(2026, 11, 19)
    assert mtdr.title.startswith("Matador Resources Company Announces Closing")
    assert mtdr.data["tags"] == ["offering"] and mtdr.data["method"] == EXCHANGE
    assert mtdr.data["published_at"] == "2026-11-19T21:56:00+00:00"
    # An item naming two companies is an event for each of them.
    storage = [e for e in result.events if e.title.startswith("Strategic Storage Trust VI")]
    assert sorted(e.ticker for e in storage) == ["SGST", "SMA"]
    assert len({e.key for e in result.events}) == len(result.events)
    assert "matched" in result.note


def test_poller_dedupes_by_key_url_and_headline(registry):
    prn = (NEWS_DIR / "prnewswire.rss.xml").read_bytes()
    ctx = Ctx(registry)
    clock = [0.0]
    source = _source({PRN: prn}, feeds=[WireFeed(WIRES["prnewswire"], 300)], clock=lambda: clock[0])
    assert len(source.poll(ctx).records) == 20
    clock[0] += 301
    again = source.poll(ctx)
    assert again.records == [] and again.events == []
    # The same headline from another feed (another URL) is not stored twice.
    copy = prn.replace(b"https://www.prnewswire.com/news-releases/", b"https://mirror.example/")
    other = _source(
        {"https://mirror.example/feed": copy},
        feeds=[
            WireFeed(WIRES["prnewswire"].__class__("mirror", "https://mirror.example/feed"), 300)
        ],
    )
    assert other.poll(ctx).records == []


def test_poller_keeps_items_without_a_registry_and_reports_it():
    ctx = Ctx(None)
    result = _source(
        {PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes()},
        feeds=[WireFeed(WIRES["prnewswire"], 300)],
    ).poll(ctx)
    assert len(result.records) == 20 and result.events == []
    assert "ticker list unavailable" in result.note


def test_poller_respects_each_feed_interval_and_survives_a_failing_feed(registry):
    clock = [0.0]
    routes = {
        PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes(),
        "https://api.gdeltproject.org": httpx.Response(429),
    }
    source = _source(
        routes,
        feeds=[WireFeed(WIRES["prnewswire"], 300), GdeltFeed("NYSE", 250, 900)],
        clock=lambda: clock[0],
    )
    ctx = Ctx(registry)
    first = source.poll(ctx)
    assert len(first.records) == 20 and "gdelt: HTTP 429" in first.note
    assert source.interval_s == 300
    clock[0] = 301
    assert [f.name for f in source.due()] == ["prnewswire"]
    clock[0] = 901
    assert {f.name for f in source.due()} == {"prnewswire", "gdelt"}
    # When every due feed fails, the poll fails (the runner shows the source in error).
    failing = _source({}, feeds=[GdeltFeed("NYSE", 250, 900)])
    with pytest.raises(RuntimeError, match="gdelt"):
        failing.poll(ctx)


def test_gdelt_feed_matches_names_in_headlines(registry):
    source = _source(
        {"https://api.gdeltproject.org": (NEWS_DIR / "gdelt_artlist.json").read_bytes()},
        feeds=[GdeltFeed("(NYSE OR NASDAQ) sourcelang:english", 250, 900)],
    )
    result = source.poll(Ctx(registry))
    assert [r["source"] for r in result.records] == ["gdelt", "gdelt"]
    assert [e.ticker for e in result.events] == ["MTDR"]
    assert result.events[0].data["method"] == NAME
    assert result.events[0].url.endswith("?utm_source=gdelt")  # stored as given


def test_tiingo_runs_only_with_a_key_and_sends_it_in_a_header(registry, monkeypatch):
    assert [f.name for f in build_feeds(NewsConfig(), tiingo_key="")] == ["prnewswire"]
    monkeypatch.setenv("TIINGO_API_KEY", "secret-key")
    assert [f.name for f in build_feeds(NewsConfig(gdelt=True))][-2:] == ["gdelt", "tiingo"]
    with pytest.raises(ValueError):
        TiingoFeed("", 900)

    calls: list[httpx.Request] = []
    routes = {"https://api.tiingo.com/tiingo/news": (NEWS_DIR / "tiingo_news.json").read_bytes()}
    source = NewsSource(
        NewsConfig(),
        client=_client(_routes(routes, calls)),
        feeds=[TiingoFeed("secret-key", 900)],
        now=lambda: NOW,
    )
    result = source.poll(Ctx(registry))
    assert calls[0].headers["Authorization"] == "Token secret-key"
    assert "secret-key" not in str(calls[0].url)
    assert [(e.ticker, e.data["method"]) for e in result.events] == [("BKU", PROVIDER)]
    # Stored oldest first.
    assert [r["data"]["tags"] for r in result.records] == [[], ["buyback"]]


def test_unknown_wire_is_a_config_error():
    with pytest.raises(ValueError, match="unknown news wire"):
        build_feeds(NewsConfig(wires=("nope",)), tiingo_key="")


def test_scorer_hook_result_is_stored(registry):
    class Scorer:
        name = "fake"

        def score(self, item):
            return {"model": "fake", "tickers": len(item["tickers"])}

    ctx = Ctx(registry)
    result = _source(
        {PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes()},
        feeds=[WireFeed(WIRES["prnewswire"], 300)],
        scorer=Scorer(),
    ).poll(ctx)
    assert all(r["data"]["score"]["model"] == "fake" for r in result.records)
    assert ctx.store.recent_news(limit=1)[0]["score"]["model"] == "fake"


# ------------------------------------------------------------ runner, views


def test_runner_stores_news_events_for_the_tape_and_the_company_context(make_client, registry):
    conn = sqlite3.connect(":memory:")
    source = _source(
        {PRN: (NEWS_DIR / "prnewswire.rss.xml").read_bytes()},
        feeds=[WireFeed(WIRES["prnewswire"], 300)],
    )
    runner = SourceRunner(conn, make_client(), sources=[source])
    runner._registry = registry
    tick = runner.tick(force=True)
    assert runner.status[NEWS].state == "ok" and len(tick.events) == 5

    row = runner.store.recent_events(source=NEWS, limit=10)[0]
    view = event_view(row)
    assert view["source"] == NEWS and view["title"]["en"] == view["title"]["pt-BR"] == row["title"]
    hbb = next(r for r in runner.store.recent_events(source=NEWS) if r["ticker"] == "HBB")
    context = company_context(runner.store, hbb["cik"], "HBB", today=date(2026, 11, 20))
    assert [e["ticker"] for e in context[NEWS]] == ["HBB"]
