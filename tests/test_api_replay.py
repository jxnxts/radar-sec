"""REPLAY mode end to end: simulated clock, REST and WebSocket, no network."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from radar.api.app import create_app
from radar.api.hub import Hub
from radar.api.prices import PriceService
from radar.api.replay import ReplayEngine
from tests.api_helpers import FakePrices, record

RECORDS = [
    record("2020-01-06", cik="100", name="Acme Corp", ticker="ACME", value=200_000),
    record(
        "2020-01-07",
        cik="200",
        name="Beta Inc",
        ticker="BETA",
        value=900_000,
        excess_6m=0.30,
        sector="Healthcare",
    ),
    record(
        "2020-01-08",
        cik="300",
        name="Gone Co",
        ticker="GONE",
        excess_6m=None,
        sector="Energy",
        ticker_current=False,
    ),
    record(
        "2020-01-09",
        cik="100",
        name="Acme Corp",
        ticker="ACME",
        kind="big_officer_buy",
        value=500_000,
        excess_6m=-0.20,
    ),
    record("2020-03-02", cik="400", name="Delta Ltd", ticker="DLT", sector="Financials"),
]


@pytest.fixture
def hub():
    return Hub()


@pytest.fixture
def engine(hub):
    # 1 simulated day per real minute, with no minimum wait between signals.
    return ReplayEngine(RECORDS, hub, start=date(2020, 1, 6), days_per_minute=1.0, min_gap=0.0)


@pytest.fixture
def client(engine, hub, tmp_path):
    prices = PriceService(FakePrices(), hub, cache_dir=tmp_path / "cache")
    app = create_app(
        engine=engine, hub=hub, prices=prices, reports_dir=tmp_path / "reports", background=False
    )
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------- clock


def test_clock_releases_signals_in_order(engine, hub):
    subscription = hub.subscribe()

    assert engine.advance(60) == 1  # one simulated day: only the signal of day 6
    assert engine.advance(60) == 1
    assert engine.status()["replay"]["position"] == 2

    events = [subscription.queue.get_nowait() for _ in range(subscription.queue.qsize())]
    signals = [e["data"] for e in events if e["type"] == "signal.new"]
    assert [s["company"] for s in signals] == ["Acme Corp", "Beta Inc"]
    assert {e["type"] for e in events} >= {"filing.new", "signal.new", "ranking.update"}
    # Every replay signal carries the measured outcome and the mode badge.
    assert all(s["mode"] == "replay" and s["outcome"]["status"] == "ok" for s in signals)


def test_long_gaps_are_compressed(engine):
    engine.advance(60 * 4)  # goes through the four January signals
    assert engine.cursor == 4
    # Almost two simulated months to go (~53 real minutes). The room does not stall:
    # after a few seconds without a signal, the clock jumps to the next one.
    waited = 0
    while not engine.advance(1.0):
        waited += 1
        assert waited < 10
    assert waited >= 5 and engine.status()["replay"]["date"] == "2020-03-02"


def test_minimum_gap_keeps_signals_readable(hub):
    engine = ReplayEngine(RECORDS, hub, start=date(2020, 1, 6), days_per_minute=1000, min_gap=3.0)
    assert engine.advance(0.5) == 1  # the first one comes out right away
    assert engine.advance(0.5) == 0  # the second waits for the operator to read
    assert engine.advance(3.0) == 1


def test_pause_speed_and_seek(engine, hub):
    engine.control(paused=True)
    assert engine.advance(600) == 0

    status = engine.control(paused=False, speed=5.0)
    assert status["speed"] == 5.0 and status["days_per_minute"] == 5.0
    assert engine.control(speed=999)["speed"] == 10.0  # clamped to the allowed range

    subscription = hub.subscribe()
    engine.control(seek=date(2020, 1, 9))
    reset = next(
        e
        for e in (subscription.queue.get_nowait() for _ in range(subscription.queue.qsize()))
        if e["type"] == "feed.reset"
    )
    # What already "happened" before the date comes ready, so the room does not start empty.
    assert [s["company"] for s in reset["data"]["signals"]] == ["Gone Co", "Beta Inc", "Acme Corp"]
    assert engine.status()["replay"]["scoreboard"]["shown"] == 0


def test_replay_loops_back_to_the_start(engine):
    for _ in range(40):
        engine.advance(120)
        if engine.loops:
            break
    assert engine.loops == 1 and engine.status()["replay"]["date"] == "2020-01-06"


def test_scoreboard_counts_who_beat_the_index(engine):
    engine.advance(60 * 4)
    board = engine.status()["replay"]["scoreboard"]
    assert board == {
        "shown": 4,
        "measured": 3,
        "unmeasured": 1,
        "beat_spy_6m": 1,
        "median_excess_6m": pytest.approx(-0.10),
    }


def test_ranking_groups_by_company_and_sector(engine):
    engine.advance(60 * 4)
    ranking = engine.ranking(7)

    assert [c["ticker"] for c in ranking["companies"]] == ["BETA", "ACME", "GONE"]
    assert (
        ranking["companies"][1]["value"] == 500_000
    )  # the largest, without adding up the same event
    sectors = {s["sector"]: s for s in ranking["sectors"]}
    assert sectors["Healthcare"]["companies"] == 1 and sectors["Utilities"]["companies"] == 0
    assert sum(s["share"] for s in ranking["sectors"]) == pytest.approx(1.0)
    # A ticker that is no longer the company's current one gets no logo (it may be another's).
    logos = {c["ticker"]: c["logo"] for c in ranking["companies"]}
    assert logos["BETA"] == "/api/logo/BETA" and logos["GONE"] is None


# ---------------------------------------------------------------------- REST


def test_health_and_state(client, engine):
    engine.advance(60)
    health = client.get("/api/health").json()
    assert health["ok"] is True and health["mode"] == "replay"
    assert health["replay"]["total"] == 5 and health["prices"]["delay_minutes"] == 15

    state = client.get("/api/state").json()
    assert state["data"]["mode"] == "replay"
    assert [s["id"] for s in state["data"]["signals"]] == ["r0"]
    assert {"7", "30"} == set(state["data"]["ranking"])


def test_signals_listing_filters(client, engine):
    engine.advance(60 * 4)
    assert [s["company"] for s in client.get("/api/signals").json()] == [
        "Acme Corp",
        "Gone Co",
        "Beta Inc",
        "Acme Corp",
    ]
    officer = client.get("/api/signals", params={"type": "big_officer_buy"}).json()
    assert [s["type"] for s in officer] == ["big_officer_buy"]
    assert len(client.get("/api/signals", params={"limit": 2}).json()) == 2
    assert client.get("/api/signals", params={"type": "made-up"}).status_code == 422


def test_signal_detail_has_purchases_history_and_chart_range(client, engine):
    engine.advance(60 * 4)
    detail = client.get("/api/signals/r3").json()

    assert detail["company"] == "Acme Corp" and detail["type"] == "big_officer_buy"
    assert detail["insiders"] == [
        {"name": "DOE JANE", "role": "CEO · Chief Executive Officer", "value": 500_000}
    ]
    assert [p["name"] for p in detail["purchases"]] == ["Roe Richard", "DOE JANE"]
    assert [s["id"] for s in detail["previous_signals"]] == ["r0"]  # only the company's past
    assert detail["chart"] == {"symbol": "ACME", "start": "2019-08-12", "end": "2020-07-27"}
    assert detail["filing_url"].startswith("https://www.sec.gov/Archives/edgar/data/100/")
    assert client.get("/api/signals/r999").status_code == 404
    assert client.get("/api/signals/l1").status_code == 404


def test_company_filings_and_ranking_endpoints(client, engine):
    engine.advance(60 * 4)
    company = client.get("/api/company/100").json()
    assert company["name"] == "Acme Corp" and len(company["signals"]) == 2
    assert client.get("/api/company/999").status_code == 404

    filings = client.get("/api/filings").json()
    assert filings and all(f["kind"] == "buy" and f["form"] == "4" for f in filings)
    assert len({f["accession"] for f in filings}) == len(filings)  # no repeats on the tape

    assert client.get("/api/ranking", params={"days": 30}).json()["days"] == 30
    assert client.get("/api/ranking", params={"days": 5}).status_code == 422


def test_replay_control_endpoint(client, engine):
    body = client.post("/api/replay/control", json={"paused": True, "speed": 2}).json()
    assert body["paused"] is True and body["speed"] == 2.0
    assert engine.paused is True

    body = client.post("/api/replay/control", json={"seek": "2020-01-08"}).json()
    assert body["date"] == "2020-01-08"
    assert client.post("/api/replay/control", json={"seek": "ontem"}).status_code == 422


def test_price_history_endpoint_and_validation(client):
    response = client.get(
        "/api/prices/ACME/history", params={"start": "2020-01-01", "end": "2020-02-01"}
    )
    body = response.json()
    assert body["kind"] == "ohlc" and body["source"] == "Test source"
    assert body["bars"][0] == {
        "t": "2020-01-02",
        "o": 10.0,
        "h": 11.0,
        "l": 9.5,
        "c": 10.5,
        "v": 1000.0,
    }
    bad_range = {"start": "2020-02-01", "end": "2020-01-01"}
    assert client.get("/api/prices/ACME/history", params=bad_range).status_code == 422
    assert client.get("/api/prices/../etc/history", params=bad_range).status_code in (404, 422)


def test_backtest_endpoint_without_report(client):
    assert client.get("/api/backtest").status_code == 404


# ----------------------------------------------------------------- WebSocket


def test_websocket_sends_snapshot_then_events(client, engine, hub):
    engine.advance(60)
    with client.websocket_connect("/ws") as socket:
        snapshot = socket.receive_json()
        assert snapshot["type"] == "snapshot" and snapshot["boot"] == hub.boot_id
        assert snapshot["seq"] == hub.seq
        assert [s["company"] for s in snapshot["data"]["signals"]] == ["Acme Corp"]
        assert snapshot["data"]["status"]["replay"]["position"] == 1

        hub.publish_threadsafe("price.tick", {"quotes": {}})
        tick = socket.receive_json()
        assert tick["type"] == "price.tick" and tick["seq"] == snapshot["seq"] + 1

        engine.advance(60)
        seen = []
        while not seen or seen[-1]["type"] != "ranking.update":
            seen.append(socket.receive_json())
        signal = next(e for e in seen if e["type"] == "signal.new")
        assert signal["data"]["company"] == "Beta Inc"
        assert [e["seq"] for e in seen] == sorted(e["seq"] for e in seen)


def test_reconnecting_client_gets_what_it_missed_in_the_snapshot(client, engine, hub):
    with client.websocket_connect("/ws") as socket:
        first = socket.receive_json()
        assert first["data"]["signals"] == []

    engine.advance(60 * 2)  # two signals come out while the client is away

    with client.websocket_connect("/ws") as socket:
        again = socket.receive_json()
        assert again["boot"] == first["boot"] and again["seq"] > first["seq"]
        assert [s["company"] for s in again["data"]["signals"]] == ["Beta Inc", "Acme Corp"]
    assert hub.clients == 0


def test_signal_texts_come_as_localized_maps(client, engine):
    engine.advance(60 * 4)
    signal = client.get("/api/signals/r3").json()
    assert signal["label"] == "Large CEO/CFO buy"
    assert set(signal["explanation"]) == set(signal["summary"]) == {"en", "pt-BR"}
    assert signal["explanation"]["en"].startswith("DOE JANE (CEO, Chief Executive Officer) bought")
    assert signal["explanation"]["pt-BR"].startswith(
        "DOE JANE (CEO, Chief Executive Officer) comprou US$ 500 mil"
    )
    assert signal["summary"]["en"].startswith("Who: DOE JANE, CEO of Acme Corp (ACME).")
    assert signal["summary"]["pt-BR"].startswith("Quem: DOE JANE, CEO de Acme Corp (ACME).")
    assert signal["summary_source"] == {"en": "template", "pt-BR": "template"}
    assert signal["sector"] == "Technology" and signal["outcome"]["status"] == "ok"
    gone = client.get("/api/signals/r2").json()
    assert gone["outcome"] == {"status": "no_prices"} and gone["sector"] == "Energy"
