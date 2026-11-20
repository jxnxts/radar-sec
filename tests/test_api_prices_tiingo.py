"""Dashboard quotes from Tiingo IEX with Yahoo behind them, the label state and the
Tiingo summary of /api/health. No network."""

from __future__ import annotations

import json
import logging
from datetime import date

import httpx
import pytest

from radar.api.prices import (
    FallbackPriceSource,
    PriceService,
    Quote,
    TiingoIexSource,
    YahooPriceSource,
    build_price_source,
)
from radar.config import ConfigError, PricesConfig
from tests.test_tiingo import KEY, _client, _router


class FakeYahoo:
    name = "Yahoo Finance"
    delay_minutes = 15

    def __init__(self, fail: bool = False):
        self.asked: list[list[str]] = []
        self.fail = fail

    def quotes(self, symbols):
        self.asked.append(list(symbols))
        if self.fail:
            raise RuntimeError("yahoo down")
        return {
            s: Quote(s, 20.0, 19.0, "2026-11-19T16:00:00-05:00", source=self.name) for s in symbols
        }

    def last_closes(self, symbols):
        return {s: (20.0, "2026-11-19") for s in symbols}

    def history(self, symbol, start, end):
        return []


# ------------------------------------------------------------------- quotes


def test_iex_quotes_are_batched_and_parsed():
    calls: list[httpx.Request] = []
    intraday = [{"date": "2026-11-19T14:30:00.000Z", "close": 739.32}]
    source = TiingoIexSource(_client(_router(calls, intraday)), batch_size=2)
    quotes = source.quotes(["SPY", "IWM", "AAPL", "^VIX"])
    assert set(quotes) == {"SPY", "IWM", "AAPL"}  # ^VIX is not on IEX
    spy = quotes["SPY"]
    assert spy.price == 715.87 and spy.prev_close == 730.2
    assert spy.as_of == "2026-11-19T21:00:00+00:00" and spy.source == "Tiingo IEX"
    assert spy.spark == [739.32, 715.87]  # the session's 5-minute line, then the poll
    batches = [c.url.params["tickers"] for c in calls if c.url.path == "/iex/"]
    assert batches == ["spy,iwm", "aapl"]
    # The intraday seed is asked once per session day, only for the benchmark ETFs.
    source.quotes(["SPY"])
    seeds = [c.url.path for c in calls if c.url.path.endswith("/prices")]
    assert sorted(seeds) == ["/iex/iwm/prices", "/iex/spy/prices"]


def test_fallback_covers_what_tiingo_misses_and_its_failures(caplog):
    calls: list[httpx.Request] = []
    yahoo = FakeYahoo()
    source = FallbackPriceSource(TiingoIexSource(_client(_router(calls))), yahoo)
    quotes = source.quotes(["SPY", "^VIX"])
    assert quotes["SPY"].source == "Tiingo IEX" and quotes["^VIX"].source == "Yahoo Finance"
    assert yahoo.asked == [["^VIX"]]
    assert (source.name, source.delay_minutes) == ("Tiingo IEX", 0)
    assert source.status()["primary_state"] == "ok"

    def down(request):
        return httpx.Response(500)

    broken = FallbackPriceSource(TiingoIexSource(_client(down)), FakeYahoo())
    with caplog.at_level(logging.WARNING):
        quotes = broken.quotes(["SPY"])
    assert quotes["SPY"].source == "Yahoo Finance"
    assert (broken.name, broken.delay_minutes) == ("Yahoo Finance", 15)
    assert broken.status()["primary_state"] == "error"
    assert all(KEY not in r.getMessage() for r in caplog.records)


def test_price_service_reports_the_actual_source(tmp_path):
    calls: list[httpx.Request] = []
    source = FallbackPriceSource(TiingoIexSource(_client(_router(calls))), FakeYahoo())
    service = PriceService(source, hub=None, cache_dir=tmp_path)  # type: ignore[arg-type]
    tick = service.refresh()
    assert tick["source"] == "Tiingo IEX" and tick["delay_minutes"] == 0
    assert tick["provider"]["fallback"] == "Yahoo Finance"
    assert tick["quotes"]["SPY"]["source"] == "Tiingo IEX"
    # Charts keep Yahoo's split-adjusted daily bars and say so.
    assert service.history("SPY", date(2026, 11, 1), date(2026, 11, 5))["source"] == (
        "Yahoo Finance"
    )


def test_provider_choice():
    assert isinstance(build_price_source(PricesConfig(), api_key=""), YahooPriceSource)
    assert isinstance(
        build_price_source(PricesConfig(provider="yahoo"), api_key=KEY), YahooPriceSource
    )
    source = build_price_source(PricesConfig(tiingo_batch_size=50), api_key=KEY)
    assert isinstance(source, FallbackPriceSource) and source.primary.batch_size == 50
    with pytest.raises(ConfigError):
        PricesConfig(provider="iex")


def test_health_summarizes_what_the_key_does(monkeypatch):
    from radar.api.app import tiingo_health

    monkeypatch.setenv("TIINGO_API_KEY", KEY)
    engine = {
        "sources": [
            {
                "name": "news",
                "detail": {
                    "feeds": [
                        {"name": "tiingo", "state": "disabled", "error": "HTTP 403: no access"}
                    ]
                },
            }
        ]
    }
    prices = {
        "provider": {
            "primary": "Tiingo IEX",
            "primary_state": "ok",
            "primary_error": None,
            "fallback_symbols": ["^VIX"],
        }
    }
    health = tiingo_health(engine, prices)
    assert health["key_set"] is True
    assert health["news"] == {"state": "disabled", "error": "HTTP 403: no access"}
    assert health["quotes"]["state"] == "ok" and health["quotes"]["fallback_symbols"] == ["^VIX"]
    assert KEY not in json.dumps(health)
