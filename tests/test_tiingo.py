"""Tiingo: the client (key only in a header, budget, 429/403) and the end-of-day
closes of the forward-test snapshot. Answers recorded from the real API on 2026-11-19.
No network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pandas as pd
import pytest

from radar.config import Settings
from radar.forward import TIINGO, YAHOO, snapshot_closes, tiingo_closes, tiingo_frame
from radar.http import RateLimiter
from radar.tiingo import (
    RequestBudget,
    TiingoAuthError,
    TiingoBudgetError,
    TiingoClient,
    tiingo_symbol,
)
from tests.conftest import FIXTURES

KEY = "test-key-123"
IEX = json.loads((FIXTURES / "tiingo" / "iex_batch.json").read_text())
DAILY = json.loads((FIXTURES / "tiingo" / "daily_aapl.json").read_text())


def _client(handler, *, per_hour: int = 100, clock=None) -> TiingoClient:
    budget = RequestBudget(per_hour, clock=clock) if clock else RequestBudget(per_hour)
    return TiingoClient(
        KEY,
        budget=budget,
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(1000, sleep=lambda s: None),
    )


def _router(calls: list[httpx.Request], intraday=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/iex/":
            wanted = request.url.params["tickers"].split(",")
            return httpx.Response(200, json=[r for r in IEX if r["ticker"].lower() in wanted])
        if path.startswith("/iex/") and path.endswith("/prices"):
            return httpx.Response(200, json=intraday or [])
        if path == "/tiingo/daily/aapl/prices":
            return httpx.Response(200, json=DAILY)
        return httpx.Response(404, json={"detail": "Not found."})

    return handler


# ------------------------------------------------------------------- client


def test_key_goes_only_in_the_authorization_header():
    calls: list[httpx.Request] = []
    client = _client(_router(calls))
    client.iex(["spy", "aapl"])
    [request] = calls
    assert request.headers["Authorization"] == f"Token {KEY}"
    assert KEY not in str(request.url)
    assert request.url.params["tickers"] == "spy,aapl"


def test_auth_errors_and_429_never_show_the_key():
    def forbidden(request):
        return httpx.Response(403, json={"detail": "You do not have permission"})

    with pytest.raises(TiingoAuthError) as error:
        _client(forbidden).iex(["spy"])
    assert error.value.status_code == 403 and KEY not in str(error.value)

    now = [0.0]

    def slow_down(request):
        return httpx.Response(429, headers={"Retry-After": "120"})

    client = _client(slow_down, clock=lambda: now[0])
    with pytest.raises(TiingoBudgetError, match="pausing 120s"):
        client.iex(["spy"])
    with pytest.raises(TiingoBudgetError, match="paused"):
        client.iex(["spy"])  # no request while paused
    assert client.requests_made == 1


def test_hourly_budget_fails_fast_and_rolls_over():
    now = [0.0]
    calls: list[httpx.Request] = []
    client = _client(_router(calls), per_hour=2, clock=lambda: now[0])
    client.iex(["spy"])
    client.iex(["spy"])
    with pytest.raises(TiingoBudgetError, match="2 requests/hour"):
        client.iex(["spy"])
    assert len(calls) == 2
    now[0] = 3601
    client.iex(["spy"])
    assert len(calls) == 3 and client.budget.used() == 1


def test_symbols_map_to_tiingo_tickers():
    assert tiingo_symbol("BRK-B") == "brk-b"
    assert tiingo_symbol("BRK.B") == "brk-b"
    assert tiingo_symbol("^VIX") is None


# ---------------------------------------------------------- end-of-day close


def test_tiingo_frame_matches_the_snapshot_table():
    frame = tiingo_frame(DAILY)
    assert list(frame.columns) == ["close", "adj_close", "split"]
    assert frame.index[-1] == pd.Timestamp("2026-11-19")
    assert frame.iloc[-1]["close"] == 349.21 and frame.iloc[-1]["split"] == 0.0
    assert frame.attrs["source"] == TIINGO
    assert tiingo_frame([]) is None


def test_snapshot_closes_use_tiingo_then_yahoo():
    calls: list[httpx.Request] = []
    asked: list[list[str]] = []

    def yahoo(symbols, start, end):
        asked.append(list(symbols))
        frame = pd.DataFrame(
            {"close": [10.0], "adj_close": [10.0], "split": [0.0]},
            index=pd.to_datetime(["2026-11-19"]),
        )
        frame.attrs["source"] = YAHOO
        return {s: frame for s in symbols}, {}

    fetch = tiingo_closes(_client(_router(calls)), yahoo, max_symbols=2)
    data, errors = fetch(["AAPL", "NOPE", "^VIX", "MSFT"], date(2026, 11, 12), date(2026, 11, 19))
    assert data["AAPL"].attrs["source"] == TIINGO
    # Unknown to Tiingo (404), an index and past the cap: Yahoo.
    assert asked == [["NOPE", "^VIX", "MSFT"]]
    assert {s: f.attrs["source"] for s, f in data.items()} == {
        "AAPL": TIINGO,
        "NOPE": YAHOO,
        "^VIX": YAHOO,
        "MSFT": YAHOO,
    }
    assert errors == {}


def test_snapshot_stops_asking_tiingo_once_the_budget_is_spent():
    calls: list[httpx.Request] = []

    def yahoo(symbols, start, end):
        return {}, {s: "no data" for s in symbols}

    fetch = tiingo_closes(_client(_router(calls), per_hour=1), yahoo, max_symbols=10)
    data, errors = fetch(["AAPL", "AAPL2", "AAPL3"], date(2026, 11, 12), date(2026, 11, 19))
    assert len(calls) == 1 and list(data) == ["AAPL"]
    assert set(errors) == {"AAPL2", "AAPL3"}


def test_snapshot_provider_follows_the_key(monkeypatch, tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert snapshot_closes(settings).__qualname__.startswith("yahoo_closes")
    monkeypatch.setenv("TIINGO_API_KEY", KEY)
    assert snapshot_closes(settings).__qualname__.startswith("tiingo_closes")


def test_recorded_snapshot_names_its_source(tmp_path):
    from radar.forward import ForwardLog, ForwardRecorder

    def fetch(symbols, start, end):
        frame = tiingo_frame(DAILY)
        return {s: frame for s in symbols}, {}

    log_ = ForwardLog(tmp_path)
    recorder = ForwardRecorder(
        log_, fetch_closes=fetch, now=lambda: datetime(2026, 11, 19, 22, tzinfo=UTC)
    )
    assert recorder.snapshot(["AAPL"], datetime(2026, 11, 19, 22, tzinfo=UTC)) == 1
    records = list(log_.read(date(2026, 11, 19)))
    assert records[0]["data"]["source"] == TIINGO and records[0]["data"]["close"] == 349.21
    assert records[-1]["data"]["sources"] == {TIINGO: 1}
