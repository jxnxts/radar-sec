"""Shared fixtures. No test touches the network or reads the real .env."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import httpx
import pytest

import radar.config
import radar.http
from radar.config import SecConfig, Settings
from radar.http import RateLimiter, SecClient

FIXTURES = Path(__file__).parent / "fixtures"
TEST_USER_AGENT = "RadarSEC-Tests contact@example.com"


def pytest_configure(config: pytest.Config) -> None:
    """Keep CLI output plain everywhere, including CI.

    Typer and Rich force styled output when GITHUB_ACTIONS, FORCE_COLOR or PY_COLORS
    is set, which splits option names with ANSI codes. This runs before the test
    modules import Typer.
    """
    os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
    os.environ["NO_COLOR"] = "1"
    for var in ("FORCE_COLOR", "PY_COLORS"):
        os.environ.pop(var, None)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch):
    """No network, no user .env and no real credentials in the environment."""

    def blocked(*args, **kwargs):
        raise RuntimeError("test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(radar.config, "_ENV_LOADED", True)
    monkeypatch.setattr(radar.http, "_global_limiter", None)
    monkeypatch.setenv("SEC_USER_AGENT", TEST_USER_AGENT)
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "RADAR_ALERTS",
        "RADAR_DATA_DIR",
        "RADAR_CONFIG",
        "RADAR_LANG",
        "TIINGO_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="latin-1")


@pytest.fixture
def fixture_text():
    return read_fixture


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")


class Recorder:
    """Fake transport: answers from a URL → response map and records the calls."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[httpx.Request] = []

    def add(self, url: str, response: object) -> None:
        self.routes[url] = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        route = self.routes.get(url)
        if route is None:
            for prefix, candidate in self.routes.items():
                if prefix.endswith("*") and url.startswith(prefix[:-1]):
                    route = candidate
                    break
        if route is None:
            return httpx.Response(404, text=f"no route for {url}")
        if callable(route):
            return route(request)
        if isinstance(route, httpx.Response):
            return route
        if isinstance(route, bytes):
            return httpx.Response(200, content=route)
        return httpx.Response(200, text=str(route))

    def urls(self) -> list[str]:
        return [str(call.url) for call in self.calls]


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def make_client(tmp_path: Path, recorder: Recorder):
    """Builds a SecClient on top of the fake transport, with no real waits."""

    def factory(**overrides) -> SecClient:
        sleeps: list[float] = []
        options = {
            "config": SecConfig(max_retries=3),
            "transport": httpx.MockTransport(recorder),
            "limiter": RateLimiter(1000, sleep=lambda seconds: None),
            "sleep": sleeps.append,
        }
        options.update(overrides)
        client = SecClient(tmp_path / "cache", **options)
        client.sleeps = sleeps  # type: ignore[attr-defined]
        return client

    return factory
