"""Configuration loading and the command line."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from radar.cli import app
from radar.config import ConfigError, Settings, load_settings

REPO = Path(__file__).parent.parent
runner = CliRunner()


def test_shipped_config_file_matches_the_defaults():
    # The repository radar.toml documents the defaults; if they differ, one of them is wrong.
    loaded = load_settings(REPO / "radar.toml")
    defaults = Settings()
    assert loaded.signals == defaults.signals
    assert loaded.sec == defaults.sec
    assert loaded.ai == defaults.ai
    assert loaded.backtest == defaults.backtest
    assert loaded.lang == defaults.lang == "en"


def test_config_file_overrides_defaults(tmp_path):
    path = tmp_path / "mine.toml"
    path.write_text(
        "[signals]\ncluster_min_insiders = 3\nofficer_min_value = 500000\n"
        '[ai]\nenabled = false\nmodel = "sonnet"\n[backtest]\nhorizons_months = [1, 12]\n'
    )
    settings = load_settings(path)
    assert settings.signals.cluster_min_insiders == 3
    assert settings.signals.officer_min_value == 500_000.0
    assert settings.signals.cluster_window_days == 14  # the rest keeps the default
    assert settings.ai.enabled is False and settings.ai.model == "sonnet"
    assert settings.backtest.horizons_months == (1, 12)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[signals]\ncluster_window = 14\n", "unknown key 'cluster_window'"),
        ("[signals]\ncluster_min_insiders = 'two'\n", "expected an integer"),
        ("[ai]\nenabled = 1\n", "expected true/false"),
        ("[signalz]\nx = 1\n", "unknown key 'signalz'"),
        ("[signals\n", "invalid TOML"),
        ('lang = "fr"\n', "unsupported language 'fr'"),
    ],
)
def test_config_mistakes_are_reported_clearly(tmp_path, content, message):
    path = tmp_path / "bad.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_settings(path)


def test_missing_explicit_config_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.toml")


def test_data_dir_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path / "other"))
    settings = load_settings()
    assert settings.db_path == tmp_path / "other" / "radar.sqlite"
    assert settings.cache_dir == tmp_path / "other" / "cache"


@pytest.mark.parametrize(("value", "expected"), [("en-US", "en"), ("pt-br", "pt-BR"), ("", "en")])
def test_language_comes_from_the_config_or_the_environment(monkeypatch, tmp_path, value, expected):
    path = tmp_path / "lang.toml"
    path.write_text('lang = "pt-BR"\n')
    assert load_settings(path).lang == "pt-BR"
    monkeypatch.setenv("RADAR_LANG", value)
    assert load_settings(path).lang == (expected if value else "pt-BR")


def test_bad_language_in_the_environment_is_reported(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RADAR_LANG", "klingon")
    with pytest.raises(ConfigError, match="RADAR_LANG"):
        load_settings()


# ------------------------------------------------------------------------ CLI


@pytest.fixture
def workdir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_help_lists_the_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("watch", "signals", "backtest", "report", "serve", "replay-build"):
        assert command in result.output


def test_watch_without_user_agent_fails_with_instructions(workdir, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT")
    result = runner.invoke(app, ["watch", "--once"])
    assert result.exit_code == 2
    assert "SEC_USER_AGENT" in result.output and ".env" in result.output


def test_watch_rejects_once_with_interval(workdir):
    result = runner.invoke(app, ["watch", "--once", "--interval", "60"])
    assert result.exit_code == 2 and "not both" in result.output


def test_signals_before_any_watch(workdir):
    result = runner.invoke(app, ["signals", "--since", "7d"])
    assert result.exit_code == 0 and "radar watch --once" in result.output


def test_signals_lists_what_is_stored(workdir):
    from datetime import date

    from radar.db import Database
    from radar.models import Signal

    with Database(workdir / "data" / "radar.sqlite") as db:
        db.add_signal(
            Signal(
                type="cluster_buy",
                dedupe_key="k",
                issuer_cik="1",
                issuer_name="Example Corp",
                ticker="EXM",
                signal_date=date.today(),
                score=71,
                trigger_accession="acc",
                explanation="stored text",
                details={
                    "insiders": [{"name": "Jane Doe", "role": "CEO", "value": 300_000}],
                    "n_insiders": 2,
                    "total_value": 300_000,
                    "avg_price": 10.0,
                    "first_buy": date.today().isoformat(),
                    "last_buy": date.today().isoformat(),
                },
                summary="Short summary.",
                summary_source="template",
            )
        )
    listing = runner.invoke(app, ["signals", "--since", "7d"])
    assert listing.exit_code == 0
    assert "EXM" in listing.output and "cluster_buy" in listing.output
    assert "2 distinct insiders bought $300K" in listing.output

    full = runner.invoke(app, ["signals", "--since", "7d", "--full"])
    assert "Who: 2 insiders at Example Corp" in full.output and "(summary: template)" in full.output

    other_type = runner.invoke(app, ["signals", "--type", "activist_13d"])
    assert "No signals" in other_type.output

    portuguese = runner.invoke(app, ["signals", "--since", "7d", "--lang", "pt-BR"])
    assert "2 insiders distintos compraram US$ 300 mil" in portuguese.output
    assert "1 sinal(is) desde" in portuguese.output


def test_signals_rejects_bad_arguments(workdir):
    assert runner.invoke(app, ["signals", "--since", "yesterday"]).exit_code == 2
    assert runner.invoke(app, ["signals", "--type", "made-up"]).exit_code == 2


def test_backtest_validates_dates(workdir):
    bad_format = runner.invoke(app, ["backtest", "--start", "01/01/2020"])
    assert bad_format.exit_code == 2 and "YYYY-MM-DD" in bad_format.output
    inverted = runner.invoke(app, ["backtest", "--start", "2025-01-01", "--end", "2020-01-01"])
    assert inverted.exit_code == 2 and "before" in inverted.output
    bad_lang = runner.invoke(app, ["backtest", "--lang", "fr"])
    assert bad_lang.exit_code == 2 and "unsupported language" in bad_lang.output


def test_report_needs_a_signals_csv(workdir):
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 2 and "no signals CSV" in result.output
