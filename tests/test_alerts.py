"""Alert channels: which ones are active, what they show and how they fail."""

import json
import subprocess
from datetime import date

import httpx
import pytest
from rich.console import Console

from radar import alerts
from radar.alerts import build_alerters, dispatch
from radar.alerts.console import ConsoleAlerter
from radar.alerts.macos import MacOSAlerter
from radar.alerts.telegram import TelegramAlerter
from radar.models import Signal


def signal() -> Signal:
    return Signal(
        type="big_officer_buy",
        dedupe_key="k",
        issuer_cik="1801368",
        issuer_name='Company "Quotes" & Co',
        ticker="CMP",
        signal_date=date(2026, 11, 17),
        score=72.4,
        explanation="",
        trigger_accession="0001831686-26-000014",
        details={
            "insider": "Jane Doe",
            "role": "CEO",
            "title": "",
            "total_value": 300_000,
            "shares": 10_000,
            "avg_price": 30.0,
            "last_buy": "2026-11-16",
        },
        summary="Who: Jane Doe.\nHow much: $300K.",
        summary_source="template",
    )


EXPLANATION_EN = (
    'Jane Doe (CEO) bought $300K of Company "Quotes" & Co (CMP) stock on the open market '
    "(code P): 10,000 shares at an average of $30.00, on Nov 16, 2026."
)


def names(found) -> list[str]:
    return [a.name for a in found]


def test_console_is_the_default_channel():
    assert names(build_alerters(env={})) == ["console"]


def test_telegram_joins_only_when_both_variables_exist():
    assert names(build_alerters(env={"TELEGRAM_BOT_TOKEN": "t"})) == ["console"]
    assert names(build_alerters(env={"TELEGRAM_CHAT_ID": "c"})) == ["console"]
    both = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    assert names(build_alerters(env=both)) == ["console", "telegram"]


def test_asking_for_telegram_without_credentials_is_skipped():
    assert names(build_alerters(["console", "telegram"], env={})) == ["console"]


def test_channels_come_from_radar_alerts(monkeypatch):
    monkeypatch.setattr("radar.alerts.macos.sys.platform", "darwin")
    monkeypatch.setattr("radar.alerts.macos.shutil.which", lambda name: "/usr/bin/osascript")
    assert names(build_alerters(env={"RADAR_ALERTS": "console, macos"})) == ["console", "macos"]


def test_macos_channel_is_unavailable_elsewhere(monkeypatch):
    monkeypatch.setattr("radar.alerts.macos.sys.platform", "linux")
    assert names(build_alerters(["macos"], env={})) == []


def test_unknown_channels_are_ignored():
    assert names(build_alerters(["console", "carrier-pigeon"], env={})) == ["console"]


def test_new_channels_can_be_plugged_in(monkeypatch):
    sent = []

    class Webhook:
        name = "webhook"

        def send(self, signal):
            sent.append(signal.ticker)

    monkeypatch.setitem(alerts._REGISTRY, "webhook", lambda env, lang: Webhook())
    dispatch(build_alerters(["webhook"], env={}), signal())
    assert sent == ["CMP"]


def test_console_alert_shows_what_matters():
    console = Console(record=True, width=120, force_terminal=False)
    ConsoleAlerter(console).send(signal())
    text = console.export_text()
    assert "Large CEO/CFO buy" in text and "CMP" in text and "score 72" in text
    assert "Jane Doe (CEO) bought $300K" in text
    assert "How much: $300K." in text
    assert "summary: template" in text
    assert "0001831686-26-000014-index.htm" in text


def test_alerts_follow_the_configured_language():
    console = Console(record=True, width=200, force_terminal=False)
    (alerter,) = build_alerters(["console"], env={}, lang="pt-BR")
    alerter.console = console
    alerter.send(signal())
    text = console.export_text()
    assert "Compra grande de CEO/CFO: CMP (score 72)" in text
    assert "Jane Doe (CEO) comprou US$ 300 mil" in text and "resumo: template" in text


def test_macos_alert_passes_text_as_arguments_not_as_script(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    MacOSAlerter().send(signal())

    command = captured["command"]
    assert command[0] == "osascript"
    script = [command[i + 1] for i, part in enumerate(command) if part == "-e"]
    # A company name with quotes must not end up in the AppleScript code.
    assert all("Quotes" not in line and "bought" not in line for line in script)
    assert command[-3:] == [EXPLANATION_EN, "radar-sec", alerts.alert_title(signal())]
    assert captured["kwargs"]["check"] is True


def test_telegram_alert_posts_the_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    TelegramAlerter("TOKEN123", "42", transport=httpx.MockTransport(handler)).send(signal())
    assert seen["url"] == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert seen["body"]["chat_id"] == "42"
    assert EXPLANATION_EN in seen["body"]["text"]


def test_telegram_errors_do_not_leak_the_token():
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    with pytest.raises(RuntimeError) as info:
        TelegramAlerter("TOKEN123", "42", transport=transport).send(signal())
    assert "401" in str(info.value) and "TOKEN123" not in str(info.value)


def test_one_failing_channel_does_not_stop_the_others():
    delivered = []

    class Broken:
        name = "broken"

        def send(self, signal):
            raise RuntimeError("down")

    class Working:
        name = "working"

        def send(self, signal):
            delivered.append(signal.ticker)

    assert dispatch([Broken(), Working()], signal()) == ["working"]
    assert delivered == ["CMP"]
