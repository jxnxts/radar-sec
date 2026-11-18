"""Pluggable alerts.

An alert channel is any object with `name` and `send(signal)`. To add a channel,
write the class and register a factory with `register("name", factory)`; the
factory receives the environment and the language, and returns the ready channel
or `None` when it is not configured.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Protocol

from radar.i18n import DEFAULT_LANG, signal_label, t
from radar.models import Signal
from radar.signals import explain

log = logging.getLogger(__name__)


class Alerter(Protocol):
    name: str

    def send(self, signal: Signal) -> None: ...


Factory = Callable[[Mapping[str, str], str], "Alerter | None"]
_REGISTRY: dict[str, Factory] = {}


def register(name: str, factory: Factory) -> None:
    _REGISTRY[name] = factory


def available() -> list[str]:
    return sorted(_REGISTRY)


def alert_title(signal: Signal, lang: str = DEFAULT_LANG) -> str:
    company = signal.ticker or signal.issuer_name
    return t(
        "alert.title",
        lang,
        label=signal_label(signal.type, lang),
        company=company,
        score=f"{signal.score:.0f}",
    )


def alert_body(signal: Signal, lang: str = DEFAULT_LANG) -> str:
    lines = [explain(signal, lang)]
    if signal.summary:
        lines += ["", signal.summary]
    if link := filing_link(signal):
        lines += ["", link]
    return "\n".join(lines)


def filing_link(signal: Signal) -> str:
    if not signal.issuer_cik or not signal.trigger_accession:
        return ""
    from radar.edgar import filing_index_url

    return filing_index_url(signal.issuer_cik, signal.trigger_accession)


def build_alerters(
    names: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    lang: str = DEFAULT_LANG,
) -> list[Alerter]:
    """Builds the active channels, writing in `lang`.

    Without `names`, uses `RADAR_ALERTS` (default: console). Telegram joins on its
    own when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set.
    """
    env = os.environ if env is None else env
    if names is None:
        names = [n.strip() for n in env.get("RADAR_ALERTS", "console").split(",") if n.strip()]
        has_telegram = env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")
        if "telegram" not in names and has_telegram:
            names.append("telegram")

    alerters: list[Alerter] = []
    for name in dict.fromkeys(names):  # no repeats, keeping the order
        factory = _REGISTRY.get(name)
        if factory is None:
            log.warning("unknown alert channel: %s (available: %s)", name, available())
            continue
        alerter = factory(env, lang)
        if alerter is None:
            log.warning("alert channel '%s' requested but not configured; skipped", name)
            continue
        alerters.append(alerter)
    return alerters


def dispatch(alerters: list[Alerter], signal: Signal) -> list[str]:
    """Sends the signal through every channel. One failing does not stop the others."""
    delivered: list[str] = []
    for alerter in alerters:
        try:
            alerter.send(signal)
            delivered.append(alerter.name)
        except Exception as exc:
            log.warning("alert '%s' failed: %s", alerter.name, exc)
    return delivered


# Imported last: each module registers its own channel.
from radar.alerts import console, macos, telegram  # noqa: E402, F401
