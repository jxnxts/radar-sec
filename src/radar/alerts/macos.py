"""Native macOS notification via osascript."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping

from radar.alerts import alert_title, register
from radar.i18n import DEFAULT_LANG
from radar.models import Signal
from radar.signals import explain

# The text goes in as a script argument, not pasted inside it: company names come
# from public filings and must not become AppleScript code.
_SCRIPT = (
    "on run argv",
    "display notification (item 1 of argv) with title (item 2 of argv) subtitle (item 3 of argv)",
    "end run",
)


class MacOSAlerter:
    name = "macos"

    def __init__(self, *, lang: str = DEFAULT_LANG):
        self.lang = lang

    def send(self, signal: Signal) -> None:
        command = ["osascript"]
        for line in _SCRIPT:
            command += ["-e", line]
        command += [
            explain(signal, self.lang)[:240],
            "radar-sec",
            alert_title(signal, self.lang)[:120],
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=10)


def _factory(env: Mapping[str, str], lang: str = DEFAULT_LANG) -> MacOSAlerter | None:
    if sys.platform != "darwin" or shutil.which("osascript") is None:
        return None
    return MacOSAlerter(lang=lang)


register("macos", _factory)
