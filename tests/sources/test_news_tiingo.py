"""Tiingo News on a plan without news access: turned off once, shown in the health."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

import httpx

from radar.config import NewsConfig
from radar.sources.news.client import NewsClient
from radar.sources.news.feeds import WIRES
from radar.sources.news.live import NewsSource, TiingoFeed, WireFeed
from radar.sources.runner import SourceRunner
from radar.sources.store import SourceStore
from tests.conftest import FIXTURES

NOW = datetime(2026, 11, 20, 1, 52, 51, tzinfo=UTC)


def _news_source(handler, feeds, clock):
    return NewsSource(
        NewsConfig(),
        client=NewsClient(
            user_agent="radar-sec tests",
            min_host_interval=0.001,
            transport=httpx.MockTransport(handler),
            sleep=lambda seconds: None,
        ),
        feeds=feeds,
        now=lambda: NOW,
        clock=clock,
    )


def test_tiingo_without_news_access_is_disabled_once(caplog):
    calls: list[httpx.Request] = []
    prn = (FIXTURES / "sources" / "news" / "prnewswire.rss.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "api.tiingo.com":
            return httpx.Response(
                403, json={"detail": "You do not have permission to access the News API"}
            )
        return httpx.Response(200, content=prn)

    clock = [0.0]
    source = _news_source(
        handler,
        [WireFeed(WIRES["prnewswire"], 300), TiingoFeed("secret-key", 900)],
        lambda: clock[0],
    )
    with caplog.at_level(logging.INFO):
        first = source.poll(type("Ctx", (), {"store": SourceStore(sqlite3.connect(":memory:"))})())
        for _ in range(3):
            clock[0] += 1000
            source.poll(type("Ctx", (), {"store": SourceStore(sqlite3.connect(":memory:"))})())
    tiingo_calls = [c for c in calls if c.url.host == "api.tiingo.com"]
    assert len(tiingo_calls) == 1
    assert tiingo_calls[0].headers["Authorization"] == "Token secret-key"
    assert "secret-key" not in str(tiingo_calls[0].url)
    disabled = [r for r in caplog.records if "disabled for this session" in r.getMessage()]
    assert len(disabled) == 1 and "permission" in disabled[0].getMessage()
    assert all("secret-key" not in r.getMessage() for r in caplog.records)
    assert "off for this session: tiingo" in first.note
    feeds = {f["name"]: f for f in source.health()["feeds"]}
    assert feeds["tiingo"]["state"] == "disabled"
    assert feeds["tiingo"]["error"].startswith("HTTP 403: You do not have permission")
    assert feeds["prnewswire"]["state"] == "ok"


def test_a_disabled_feed_alone_does_not_fail_the_poll():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token."})

    source = _news_source(handler, [TiingoFeed("bad", 900)], lambda: 0.0)
    ctx = type("Ctx", (), {"store": SourceStore(sqlite3.connect(":memory:"))})()
    result = source.poll(ctx)  # no RuntimeError: nothing failed, the feed is off
    assert result.records == [] and source.due() == []


def test_feed_states_reach_the_runner_status(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "You do not have permission"})

    source = _news_source(handler, [TiingoFeed("secret-key", 900)], lambda: 0.0)
    runner = SourceRunner(sqlite3.connect(":memory:"), make_client(), sources=[source])
    runner.tick(force=True)
    [status] = runner.statuses()
    assert status["state"] == "ok"
    assert status["detail"]["feeds"][0]["state"] == "disabled"
