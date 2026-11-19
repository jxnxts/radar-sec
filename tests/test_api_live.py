"""LIVE mode: the monitor cycle publishes to the hub and the API reads the same database. Fake SEC."""

import json
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from radar.api.app import create_app
from radar.api.hub import Hub
from radar.api.live import LiveEngine
from radar.config import AIConfig, SecConfig, SignalConfig
from radar.feed import feed_url
from radar.summary import Summarizer
from radar.watch import Watcher
from tests.conftest import read_fixture
from tests.test_watch import AMENDED_13D, BOLT, GILEAD, MP_CFO, NEW_13D, TODAY, atom, index_url


@pytest.fixture
def engine(settings, recorder, make_client):
    form4, thirteen_d = [MP_CFO, BOLT, GILEAD], [NEW_13D, AMENDED_13D]
    recorder.add(feed_url("4"), atom(form4))
    recorder.add(feed_url("SCHEDULE 13D", count=40), atom(thirteen_d))
    for accession, _, _, cik, _ in form4 + thirteen_d:
        recorder.add(
            index_url(accession, cik).replace("-index.htm", ".txt"),
            read_fixture(f"{accession}.txt"),
        )
    recorder.add(
        "https://www.sec.gov/files/company_tickers.json",
        json.dumps(
            {
                "0": {"cik_str": 1849221, "ticker": "PMNT", "title": "Perfect Moment"},
                "1": {"cik_str": 1801368, "ticker": "MP", "title": "MP Materials"},
            }
        ),
    )
    # SEC registry with the SIC (metal mining) for one of the issuers.
    recorder.add("https://data.sec.gov/submissions/CIK0001801368.json", json.dumps({"sic": "1040"}))

    settings = replace(
        settings,
        sec=SecConfig(backfill_issuer=False),
        signals=SignalConfig(officer_min_value=50_000),
    )

    def factory(db, listener):
        return Watcher(
            settings,
            db,
            make_client(config=settings.sec),
            [],
            Summarizer(db, AIConfig(), generate=lambda prompt, **_: "AI summary."),
            today=TODAY,
            listener=listener,
        )

    live = LiveEngine(settings, Hub(), watcher_factory=factory, today=lambda: TODAY)
    yield live
    live.close()


def drain(subscription):
    return [subscription.queue.get_nowait() for _ in range(subscription.queue.qsize())]


def test_cycle_publishes_filings_signals_and_status(engine):
    subscription = engine.hub.subscribe()
    result = engine.run_cycle()

    assert result.new_filings == 5 and len(result.signals) == 2
    events = drain(subscription)
    filings = [e["data"] for e in events if e["type"] == "filing.new"]
    signals = {e["data"]["type"]: e["data"] for e in events if e["type"] == "signal.new"}

    assert len(filings) == 5
    by_company = {f["company"]: f for f in filings}
    assert by_company["MP Materials Corp. / DE"]["kind"] == "buy"
    assert by_company["MP Materials Corp. / DE"]["ticker"] == "MP"
    assert by_company["GILEAD SCIENCES, INC."]["kind"] in {"sale", "exercise"}
    assert by_company["Perfect Moment Ltd."]["kind"] == "new_13d"
    assert by_company["Perfect Moment Ltd."]["percent"] == 9.9
    assert by_company["Atlas Energy Solutions Inc."]["kind"] == "amended_13d"

    officer = signals["big_officer_buy"]
    assert officer["id"].startswith("l") and officer["mode"] == "live"
    assert officer["ticker"] == "MP" and officer["sector"] == "Materials"
    assert officer["summary"]["en"] == "AI summary."
    assert officer["summary_source"] == {"en": "ai", "pt-BR": "template"}
    assert officer["summary"]["pt-BR"].startswith("Quem: ")
    assert officer["label"] == "Large CEO/CFO buy"
    assert (
        officer["explanation"]["en"].endswith(".") and "comprou" in officer["explanation"]["pt-BR"]
    )
    assert officer["insiders"][0]["role"].startswith("CFO")
    assert officer["value"] == pytest.approx(91_577.22)
    assert officer["logo"] == "/api/logo/MP"  # ticker confirmed in the SEC registry
    assert officer["outcome"] is None  # outcomes only exist in replay
    assert signals["activist_13d"]["percent"] == 9.9
    assert signals["activist_13d"]["insiders"][0]["role"] == "13D filer"

    stages = [e["data"]["sec"]["stage"] for e in events if e["type"] == "system.status"]
    assert stages[:3] == ["feeds", "filings", "signals"]


def test_reads_reflect_what_the_cycle_stored(engine):
    engine.run_cycle()

    listed = engine.list_signals()
    assert {s["type"] for s in listed} == {"big_officer_buy", "activist_13d"}
    assert engine.list_signals(signal_type="activist_13d")[0]["company"] == "Perfect Moment Ltd."
    assert len(engine.list_filings()) == 5
    assert engine.tracked_tickers() == ["PMNT", "MP"] or engine.tracked_tickers() == ["MP", "PMNT"]

    officer = next(s for s in listed if s["type"] == "big_officer_buy")
    detail = engine.signal_detail(officer["id"])
    assert detail["chart"]["symbol"] == "MP" and detail["chart"]["end"] == TODAY.isoformat()
    assert detail["purchases"] and detail["purchases"][0]["role"] == "Chief Financial Officer"
    assert sum(p["value"] for p in detail["purchases"]) == pytest.approx(91_577.22)
    assert engine.signal_detail("l9999") is None and engine.signal_detail("r0") is None

    ranking = engine.ranking(7)
    assert ranking["basis"] == "open_market_buys"
    tickers = [c["ticker"] for c in ranking["companies"]]
    assert "MP" in tickers and "GILD" not in tickers  # only those with a P buy
    mp = next(c for c in ranking["companies"] if c["ticker"] == "MP")
    assert mp["sector"] == "Materials" and mp["value"] == pytest.approx(91_577.22)

    status = engine.status()
    assert status["mode"] == "live" and status["queue"]["pending"] == 0
    assert status["totals"] == {"signals": 2, "filings": 5}
    assert status["ai"]["state"] == "ok" and status["ai"]["used_last_hour"] == 2


def test_second_cycle_publishes_nothing_new(engine):
    engine.run_cycle()
    subscription = engine.hub.subscribe()
    engine.run_cycle()
    types = {e["type"] for e in drain(subscription)}
    assert types == {"system.status"}


def test_api_over_the_live_engine(engine, tmp_path):
    app = create_app(
        engine=engine, hub=engine.hub, reports_dir=tmp_path / "nothing", background=False
    )
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["sec"]["state"] == "starting" and health["sec"]["stage"] == "idle"
        assert health["ai"]["lang"] == "en" and health["ai"]["state"] == "ok"
        assert health["prices"] == {"state": "off"}
        assert client.get("/api/signals").json() == []

        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["data"]["signals"] == []
            engine.run_cycle()
            received = []
            while sum(1 for e in received if e["type"] == "signal.new") < 2:
                received.append(socket.receive_json())
        assert sum(1 for e in received if e["type"] == "filing.new") == 5

        signals = client.get("/api/signals").json()
        assert len(signals) == 2
        detail = client.get(f"/api/signals/{signals[0]['id']}").json()
        assert detail["id"] == signals[0]["id"] and "purchases" in detail
        assert client.get("/api/company/1801368").json()["ticker"] == "MP"
        # Replay controls do not exist in live mode; prices and logos are off here.
        assert client.post("/api/replay/control", json={"paused": True}).status_code == 409
        assert client.get("/api/quotes").status_code == 503
        assert client.get("/api/logo/MP").status_code == 404


def test_date_helper_used_by_fixture():
    assert TODAY == date(2026, 11, 17)


# ------------------------------------------------- funds and liquidity


def stored_signal(engine, kind, cik, name, ticker, day=TODAY):
    """Writes a signal straight to the database, as an older version would have."""
    from radar.db import Database
    from radar.models import Signal

    with Database(engine.settings.db_path) as db:
        signal = Signal(
            type=kind,
            dedupe_key=f"{kind}:{cik}:{day}",
            issuer_cik=cik,
            issuer_name=name,
            ticker=ticker,
            signal_date=day,
            score=60.0,
            explanation="Stored earlier.",
            trigger_accession=f"0000000000-26-{int(cik):06d}",
            details={"accessions": []},
        )
        db.add_signal(signal)
        return signal


def test_fund_signals_already_stored_are_hidden_but_kept(engine, monkeypatch):
    engine.run_cycle()
    leo = stored_signal(
        engine, "cluster_buy", "818972", "BNY MELLON STRATEGIC MUNICIPALS, INC.", "LEO"
    )
    dsm = stored_signal(
        engine, "cluster_buy", "855887", "BNY MELLON STRATEGIC MUNICIPAL BOND FUND, INC.", "DSM"
    )
    # A fund by its registry profile only (the name says nothing).
    eagle = stored_signal(engine, "big_officer_buy", "1604174", "Eagle Point Credit Co", "ECC")
    from radar.db import Database

    with Database(engine.settings.db_path) as db:
        db.set_sector("1604174", "", "Unclassified", True)
        db.set_sector("855887", "0000", "Unclassified")  # never checked: the name decides

    listed = {s["company"] for s in engine.list_signals()}
    assert listed == {"MP Materials Corp. / DE", "Perfect Moment Ltd."}
    for hidden in (leo, dsm, eagle):
        assert engine.signal_detail(f"l{hidden.id}") is None
    assert engine.company("818972") is None
    assert "LEO" not in engine.tracked_tickers()
    assert engine.status()["totals"]["signals"] == 5  # nothing was deleted

    real = engine._reader.purchase_totals
    monkeypatch.setattr(
        engine._reader,
        "purchase_totals",
        lambda since: [
            *real(since),
            {
                "cik": "818972",
                "name": "BNY MELLON STRATEGIC MUNICIPALS, INC.",
                "ticker": "LEO",
                "sector": "",
                "value": 9e9,
                "insiders": 3,
                "filings": 3,
                "last_date": TODAY.isoformat(),
            },
        ],
    )
    assert "LEO" not in [c["ticker"] for c in engine.ranking(7)["companies"]]


CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"


def concept(*facts):
    return json.dumps(
        {
            "units": {
                "shares": [{"end": end, "val": val, "filed": filed} for end, val, filed in facts]
            }
        }
    )


def test_price_and_market_value_are_stored_and_sent_with_each_signal(engine, recorder):
    asked = []

    def prices(symbols):
        asked.append(sorted(symbols))
        known = {"MP": (40.0, "2026-11-17"), "TINY": (2.0, "2026-11-17"), "BIG": (80.0, "x")}
        return {s: known[s] for s in symbols if s in known}

    engine.use_prices(prices)
    recorder.add(
        CONCEPT.format(cik=1801368),
        concept(
            ("2026-06-30", 170_000_000, "2026-08-01"), ("2026-09-30", 176_000_000, "2026-11-05")
        ),
    )
    recorder.add(CONCEPT.format(cik=777), concept(("2026-09-30", 10_000_000, "2026-11-01")))
    recorder.add(CONCEPT.format(cik=888), concept(("2026-09-30", 50_000_000, "2026-11-01")))
    tiny = stored_signal(engine, "late_filing_nt", "777", "Tiny Corp", "TINY")
    stored_signal(engine, "short_crowded", "888", "Big Corp", "BIG")
    stored_signal(engine, "ftd_persistent", "999", "Ghost Corp", "GHST")  # no price anywhere
    subscription = engine.hub.subscribe()
    engine.run_cycle()

    by_ticker = {s["ticker"]: s for s in engine.list_signals()}
    mp = by_ticker["MP"]
    assert mp["price"] == 40.0 and mp["market_value"] == pytest.approx(40.0 * 176_000_000)
    assert mp["liquid"] is True and mp["liquidity_gated"] is False  # a long signal
    small = by_ticker["TINY"]
    assert small["price"] == 2.0 and small["market_value"] == pytest.approx(20_000_000)
    assert small["liquid"] is False and small["liquidity_gated"] is True
    big = by_ticker["BIG"]
    assert big["liquid"] is True and big["liquidity_gated"] is True
    ghost = by_ticker["GHST"]
    assert ghost["price"] is None and ghost["market_value"] is None
    assert ghost["liquid"] is False  # unknown liquidity counts as not liquid
    assert engine.signal_detail(f"l{tiny.id}")["market_value"] == pytest.approx(20_000_000)

    events = drain(subscription)
    new = next(
        e["data"] for e in events if e["type"] == "signal.new" and e["data"]["ticker"] == "MP"
    )
    assert new["price"] == 40.0 and new["liquid"] is True  # measured before it was published
    updates = [e["data"] for e in events if e["type"] == "signals.update"]
    assert {s["ticker"] for s in updates[0]} >= {"TINY", "BIG", "GHST"}
    assert engine.status()["liquidity"] == {"min_price": 5.0, "min_market_value": 300_000_000.0}

    # Fresh values are not looked up again on the next cycle, and the SEC is asked once.
    calls = len(asked)
    engine.run_cycle()
    assert len(asked) == calls
    assert recorder.urls().count(CONCEPT.format(cik=777)) == 1


def test_thresholds_come_from_the_config(engine, recorder):
    from radar.config import DashboardConfig

    engine.settings = replace(
        engine.settings, dashboard=DashboardConfig(avoid_min_price=1.0, avoid_min_market_value=1e7)
    )
    engine.use_prices(lambda symbols: {s: (2.0, "2026-11-17") for s in symbols})
    recorder.add(CONCEPT.format(cik=777), concept(("2026-09-30", 10_000_000, "2026-11-01")))
    stored_signal(engine, "late_filing_nt", "777", "Tiny Corp", "TINY")
    engine.run_cycle()
    tiny = next(s for s in engine.list_signals() if s["ticker"] == "TINY")
    assert tiny["liquid"] is True


def test_without_a_price_source_liquidity_stays_unknown(engine):
    stored_signal(engine, "late_filing_nt", "777", "Tiny Corp", "TINY")
    engine.run_cycle()
    tiny = next(s for s in engine.list_signals() if s["ticker"] == "TINY")
    assert tiny["price"] is None and tiny["liquid"] is False and tiny["liquidity_gated"] is True


def test_api_payload_carries_the_liquidity_fields(engine, tmp_path):
    engine.use_prices(lambda symbols: {s: (40.0, "2026-11-17") for s in symbols})
    app = create_app(
        engine=engine, hub=engine.hub, reports_dir=tmp_path / "nothing", background=False
    )
    with TestClient(app) as client:
        engine.run_cycle()
        for signal in client.get("/api/signals").json():
            assert {"price", "price_as_of", "market_value", "liquid", "liquidity_gated"} <= set(
                signal
            )
        state = client.get("/api/state").json()["data"]
        assert all("liquid" in s for s in state["signals"])
