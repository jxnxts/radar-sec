"""Telegram alert. Only exists when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from radar.alerts import alert_body, alert_title, register
from radar.i18n import DEFAULT_LANG
from radar.models import Signal

MAX_MESSAGE = 4000  # Telegram accepts up to 4096 characters


class TelegramAlerter:
    name = "telegram"

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
        lang: str = DEFAULT_LANG,
    ):
        self._token = token
        self._chat_id = chat_id
        self._transport = transport
        self.lang = lang

    def send(self, signal: Signal) -> None:
        text = f"{alert_title(signal, self.lang)}\n\n{alert_body(signal, self.lang)}"
        with httpx.Client(timeout=15, transport=self._transport) as client:
            response = client.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text[:MAX_MESSAGE],
                    "disable_web_page_preview": True,
                },
            )
        if response.status_code != 200:
            # The URL is not repeated in the error message: it contains the bot token.
            raise RuntimeError(f"Telegram answered HTTP {response.status_code}")


def _factory(env: Mapping[str, str], lang: str = DEFAULT_LANG) -> TelegramAlerter | None:
    token, chat_id = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return None
    return TelegramAlerter(token, chat_id, lang=lang)


register("telegram", _factory)
