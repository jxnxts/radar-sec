"""Server assembly and the `radar serve` command."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from radar.api.server import DEFAULT_REPLAY_START, ServerOptions, build_app
from radar.backtest.replay import write_replay
from radar.cli import app
from radar.config import ConfigError
from tests.api_helpers import record

runner = CliRunner()


def test_serve_help_lists_the_two_modes():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--replay" in result.output and "--port" in result.output


def test_replay_without_file_explains_how_to_create_it(settings):
    with pytest.raises(RuntimeError, match="radar replay-build"):
        build_app(settings, ServerOptions(replay=True, prices=False))


def test_live_mode_requires_the_sec_user_agent(settings, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT")
    with pytest.raises(ConfigError, match="SEC_USER_AGENT"):
        build_app(settings, ServerOptions(prices=False))


def test_replay_server_serves_api_and_built_panel(settings, tmp_path):
    write_replay(
        settings.reports_dir / "backtest-2026-01-01-replay.jsonl.gz",
        [record("2020-02-10"), record("2020-02-20", cik="200", name="Beta Inc", ticker="BETA")],
    )
    panel = tmp_path / "dist"
    (panel / "assets").mkdir(parents=True)
    (panel / "index.html").write_text("<!doctype html><title>radar-sec</title>")
    (panel / "assets" / "app.js").write_text("console.log('dashboard')")

    application = build_app(settings, ServerOptions(replay=True, prices=False, panel_dir=panel))
    assert application.state.serves_panel is True
    engine = application.state.engine
    assert engine.status()["replay"]["date"] == DEFAULT_REPLAY_START.isoformat()
    assert engine.status()["replay"]["source"] == "backtest-2026-01-01-replay.jsonl.gz"

    # background=True: the replay clock really runs inside the server.
    with TestClient(application) as client:
        assert client.get("/api/health").json()["mode"] == "replay"
        # The signal before the start date comes ready; the next one comes out as the clock moves.
        assert client.get("/api/signals").json()[-1]["company"] == "Acme Corp"
        assert "radar-sec" in client.get("/").text
        assert "radar-sec" in client.get("/any/route").text  # the dashboard is a single page
        assert client.get("/assets/app.js").text == "console.log('dashboard')"
        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/../pyproject.toml").status_code in (200, 404)
        assert "[project]" not in client.get("/%2e%2e/pyproject.toml").text


def test_replay_start_option_moves_the_clock(settings):
    write_replay(
        settings.reports_dir / "backtest-2026-01-01-replay.jsonl.gz",
        [record("2020-02-10"), record("2021-05-20", cik="200")],
    )
    application = build_app(
        settings,
        ServerOptions(
            replay=True,
            prices=False,
            replay_start=date(2021, 5, 1),
            panel_dir=Path("does-not-exist"),
        ),
    )
    assert application.state.serves_panel is False
    assert application.state.engine.status()["replay"]["date"] == "2021-05-01"
