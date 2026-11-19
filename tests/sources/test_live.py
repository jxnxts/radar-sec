"""Live side of the extra sources: pollers on real feed fixtures, the runner, the views,
the explanations in every language and the API/WebSocket wiring. No network."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from radar.api.app import create_app
from radar.api.hub import MARKET_EVENT_NEW, Hub
from radar.api.live import LiveEngine
from radar.config import AIConfig, SecConfig, SourcesConfig
from radar.feed import feed_url
from radar.i18n import LANGS
from radar.models import Signal
from radar.signals import explain
from radar.sources.base import FORM144, MarketEvent, PollResult
from radar.sources.eightk.live import EightKSource
from radar.sources.form144.live import Form144Source
from radar.sources.runner import SourceContext, SourceRunner
from radar.sources.short.history import FinraClient
from radar.sources.specs import SPECS
from radar.sources.store import SourceStore
from radar.sources.views import company_context, event_view, signal_extras
from radar.summary import Summarizer
from radar.watch import Watcher
from tests.conftest import FIXTURES

SRC = FIXTURES / "sources"
TODAY = date(2026, 11, 18)


def _context(client, store: SourceStore, tmp_path) -> SourceContext:
    finra = FinraClient(
        tmp_path / "finra", transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    return SourceContext(
        client=client,
        store=store,
        finra=finra,
        today=TODAY,
        ticker_for=lambda cik: {"3453": "MATX"}.get(cik, ""),
        registrant=lambda symbol: None,
        prior_signal_dates=lambda kind, cik: [],
        momentum=lambda ticker, day: None,
        shares_outstanding=lambda cik, day: None,
        resolve_cusip=lambda cusip, day: None,
    )


def test_form144_poller_reads_the_feed_and_the_xml(make_client, recorder, tmp_path):
    recorder.add(feed_url("144", count=100), (SRC / "form144" / "feed_144.atom.xml").read_bytes())
    text = (SRC / "form144" / "0001959173-26-008125.txt").read_bytes()
    recorder.add(
        "https://www.sec.gov/Archives/edgar/data/3453/000195917326008125/0001959173-26-008125.txt",
        text,
    )
    store = SourceStore(sqlite3.connect(":memory:"))
    result = Form144Source().poll(_context(make_client(), store, tmp_path))

    assert [e.key for e in result.events] == ["0001959173-26-008125"]
    event = result.events[0]
    assert event.issuer_name == "Matson, Inc." and event.ticker == "MATX"
    assert event.data["seller"] == "Park Kuuhaku T"
    assert event.data["seller_cik"] == "1910186"  # the feed's "Reporting" entry
    assert event.data["value"] == 320835.0
    assert store.has_notice("0001959173-26-008125")
    assert result.signals == []  # one small notice: no cluster, not large


def test_eightk_poller_classifies_feed_items_without_downloading(make_client, recorder, tmp_path):
    recorder.add(feed_url("8-K", count=100), (SRC / "eightk" / "feed_8k.atom.xml").read_bytes())
    store = SourceStore(sqlite3.connect(":memory:"))
    result = EightKSource().poll(_context(make_client(), store, tmp_path))

    first = next(e for e in result.events if e.key == "0001921963-26-000084")
    assert first.kind == "8k" and first.data["items"] == ["7.01", "9.01"]
    assert len(result.events) == len({e.key for e in result.events}) > 10
    # Only items whose rules read text trigger a download (here they all 404).
    downloads = [u for u in recorder.urls() if u.endswith(".txt")]
    assert all(".txt" in u for u in downloads)


class FakeSource:
    name = FORM144
    interval_s = 60.0

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def poll(self, ctx) -> PollResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        signal = Signal(
            type="form144_large",
            dedupe_key="form144_large:acc-1",
            issuer_cik="3453",
            issuer_name="Matson, Inc.",
            ticker="MATX",
            signal_date=ctx.today,
            score=70.0,
            explanation="x",
            trigger_accession="0001959173-26-008125",
            details={
                "seller": "Park Kuuhaku T",
                "role": "Officer",
                "total_value": 12e6,
                "percent_outstanding": None,
                "tested": False,
            },
        )
        event = MarketEvent(
            source=FORM144,
            kind="form144",
            key="0001959173-26-008125",
            event_date=ctx.today,
            issuer_cik="3453",
            issuer_name="Matson, Inc.",
            ticker="MATX",
            title="sale",
            data={"seller": "Park Kuuhaku T", "relationships": ["Officer"], "value": 12e6},
        )
        return PollResult(events=[event], signals=[signal])


def _runner(conn, client, source) -> SourceRunner:
    runner = SourceRunner(
        conn,
        client,
        sources=[source],
        today=lambda: TODAY,
        finra=FinraClient(
            client.cache_dir, transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ),
    )
    runner._registry = __import__("radar.sources.registry", fromlist=["Registry"]).Registry({})
    return runner


def test_runner_stores_events_once_and_survives_a_broken_source(make_client):
    conn = sqlite3.connect(":memory:")
    good, bad = FakeSource(), FakeSource(fail=True)
    bad.name = "eightk"
    runner = SourceRunner(conn, make_client(), sources=[good, bad], today=lambda: TODAY)
    runner._registry = __import__("radar.sources.registry", fromlist=["Registry"]).Registry({})
    seen = []
    first = runner.tick(on_event=lambda event_id, event: seen.append(event_id))
    assert len(first.events) == 1 and len(first.signals) == 1 and seen
    assert runner.status["eightk"].state == "error" and "boom" in runner.status["eightk"].last_error
    assert runner.status[FORM144].state == "ok"
    assert runner.tick().events == []  # not due yet
    again = runner.tick(force=True)
    assert again.events == [] and len(again.signals) == 1  # the event is already stored


def test_every_new_type_explains_itself_in_every_language():
    samples = {
        "form144_cluster": {
            "n_sellers": 3,
            "sellers": [{"name": "A", "role": "Officer"}],
            "total_value": 2e6,
            "window_days": 10,
        },
        "form144_large": {
            "seller": "A",
            "role": "Director",
            "total_value": 12e6,
            "percent_outstanding": 1.5,
        },
        "fund_consensus_13f": {
            "holders_before": 20,
            "holders_now": 31,
            "active_filers": 4500,
            "period": "2025-09-30",
            "rank": 1,
            "breadth_change": 0.0024,
        },
        "notable_fund_new_13f": {
            "manager": "Pershing Square",
            "weight": 0.12,
            "period": "2025-09-30",
        },
        "buyback_8k": {"form": "8-K", "items": ["8.01"]},
        "ceo_cfo_exit_8k": {"titles": ["CEO"], "items": ["5.02"]},
        "bankruptcy_8k": {"items": ["1.03"]},
        "auditor_change_8k": {"items": ["4.01"]},
        "late_filing_nt": {"form": "NT 10-K"},
        "short_crowded": {
            "change": 0.4,
            "short_shares": 5e6,
            "days_to_cover": 9.2,
            "settlement_date": "2025-10-15",
        },
        "squeeze_setup": {
            "change": -0.2,
            "short_shares": 5e6,
            "days_to_cover": 9.2,
            "settlement_date": "2025-10-15",
            "momentum": 0.3,
        },
        "ftd_persistent": {"run_days": 6, "peak_fails": 2e6, "peak_fraction": 0.012},
    }
    assert set(samples) == set(SPECS)
    for kind, details in samples.items():
        signal = Signal(
            type=kind,
            dedupe_key=kind,
            issuer_cik="1",
            issuer_name="ACME",
            ticker="ACME",
            signal_date=TODAY,
            score=50,
            explanation="fallback",
            trigger_accession="0000000000-26-000001",
            details=details,
        )
        texts = {lang: explain(signal, lang) for lang in LANGS}
        assert all(t and "{" not in t and t != "fallback" for t in texts.values()), kind
        assert texts["en"] != texts["pt-BR"], kind
        extras = signal_extras(signal)
        assert extras["source"] == SPECS[kind].source and extras["facts"], kind


def test_event_view_and_company_context_in_both_languages():
    store = SourceStore(sqlite3.connect(":memory:"))
    event = MarketEvent(
        source="eightk",
        kind="8k",
        key="acc",
        event_date=TODAY,
        issuer_cik="1",
        issuer_name="ACME",
        ticker="ACME",
        title="raw",
        data={"items": ["2.02", "9.01"], "flags": ["earnings"]},
    )
    event_id = store.add_event(event)
    row = store.recent_events()[0]
    view = event_view(row)
    assert view["id"] == f"e{event_id}" and view["source"] == "eightk"
    assert view["title"]["en"] == "8-K · Earnings release"
    assert view["title"]["pt-BR"] == "8-K · Resultado divulgado"
    context = company_context(store, "1", "ACME", today=TODAY)
    assert [e["id"] for e in context["eightk"]] == [view["id"]]
    assert context["short"] == {"interest": [], "volume": [], "fails": []}


@pytest.fixture
def engine(settings, recorder, make_client):
    for form, count in (("4", 100), ("SCHEDULE 13D", 40)):
        recorder.add(
            feed_url(form, count=count), '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        )
    recorder.add("https://www.sec.gov/files/company_tickers.json", json.dumps({}))
    settings = replace(
        settings, sec=SecConfig(backfill_issuer=False), sources=SourcesConfig(enabled=())
    )

    def factory(db, listener):
        client = make_client(config=settings.sec)
        return Watcher(
            settings,
            db,
            client,
            [],
            Summarizer(db, AIConfig(enabled=False)),
            today=TODAY,
            listener=listener,
            sources=_runner(db.conn, client, FakeSource()),
        )

    live = LiveEngine(settings, Hub(), watcher_factory=factory, today=lambda: TODAY)
    yield live
    live.close()


def test_live_engine_publishes_events_and_new_signal_types(engine, tmp_path):
    subscription = engine.hub.subscribe()
    result = engine.run_cycle()
    assert result.source_events == 1 and [s.type for s in result.signals] == ["form144_large"]
    events = [subscription.queue.get_nowait() for _ in range(subscription.queue.qsize())]
    tape = [e["data"] for e in events if e["type"] == MARKET_EVENT_NEW]
    assert tape[0]["source"] == "form144" and tape[0]["title"]["en"].startswith("Park Kuuhaku T")
    signal = next(e["data"] for e in events if e["type"] == "signal.new")
    assert signal["source"] == "form144" and signal["tested"] is False
    assert signal["insiders"][0]["name"] == "Park Kuuhaku T"
    assert signal["filing_url"].endswith("0001959173-26-008125-index.htm")
    assert "planeja vender" in signal["explanation"]["pt-BR"]

    snapshot = engine.snapshot()
    assert snapshot["market_events"][0]["kind"] == "form144"
    assert engine.status()["sources"][0]["name"] == "form144"

    app = create_app(engine=engine, hub=engine.hub, reports_dir=tmp_path / "x", background=False)
    with TestClient(app) as client:
        assert client.get("/api/events").json()[0]["company"] == "Matson, Inc."
        assert client.get("/api/events?source=eightk").json() == []
        context = client.get("/api/company/0000003453/context").json()
        assert context["form144"][0]["data"]["seller"] == "Park Kuuhaku T"
        assert context["signals"][0]["type"] == "form144_large"
        assert client.get("/api/company/abc/context").status_code == 422
        assert client.get("/api/signals?type=form144_large").json()[0]["ticker"] == "MATX"
