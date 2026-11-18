"""Terminal alert (the default channel)."""

from __future__ import annotations

from collections.abc import Mapping

from rich.console import Console
from rich.panel import Panel

from radar.alerts import alert_body, alert_title, register
from radar.i18n import DEFAULT_LANG, t
from radar.models import Signal


class ConsoleAlerter:
    name = "console"

    def __init__(self, console: Console | None = None, *, lang: str = DEFAULT_LANG):
        self.console = console or Console()
        self.lang = lang

    def send(self, signal: Signal) -> None:
        source = ""
        if signal.summary_source:
            label = t(f"summary.source.{signal.summary_source}", self.lang)
            source = t("alert.summary_source", self.lang, source=label)
        self.console.print(
            Panel(
                alert_body(signal, self.lang),
                title=f"[bold]{alert_title(signal, self.lang)}[/bold]",
                subtitle=f"{signal.signal_date.isoformat()}{source}",
                border_style="green",
                expand=False,
                highlight=False,
            )
        )


def _factory(env: Mapping[str, str], lang: str = DEFAULT_LANG) -> ConsoleAlerter:
    return ConsoleAlerter(lang=lang)


register("console", _factory)
