"""Company logos, cached on disk.

Main source: Financial Modeling Prep's public image endpoint
(`financialmodelingprep.com/image-stock/<TICKER>.png`), which needs no key.
Fallback: the open `nvstly/icons` repository on GitHub. When neither has the
ticker (or returns an image that is too small), the API answers 404 and the
dashboard draws a monogram with the initials.

Requests carry only the ticker and a generic User-Agent: nothing that
identifies the user. The logos are trademarks of their respective companies,
used here only to identify them; they stay in the local cache and never enter
the repository.
"""

from __future__ import annotations

import logging
import re
import struct
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "radar-sec-dashboard/0.1"
MIN_SIDE = 48  # below this the logo turns into a blur on the card
MAX_BYTES = 600_000
MISS_TTL = 7 * 86_400
_TICKER = re.compile(r"^[A-Z0-9]{1,6}(-[A-Z]{1,2})?$")
_PNG = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class LogoSource:
    name: str
    url: str  # with {ticker}

    def url_for(self, ticker: str) -> str:
        return self.url.format(ticker=ticker)


DEFAULT_SOURCES: tuple[LogoSource, ...] = (
    LogoSource(
        "Financial Modeling Prep", "https://financialmodelingprep.com/image-stock/{ticker}.png"
    ),
    LogoSource(
        "nvstly/icons",
        "https://raw.githubusercontent.com/nvstly/icons/main/ticker_icons/{ticker}.png",
    ),
)


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG, read from the header; None if it is not a PNG."""
    if len(data) < 24 or not data.startswith(_PNG) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def usable(data: bytes) -> bool:
    if not data or len(data) > MAX_BYTES:
        return False
    size = png_size(data)
    return size is not None and min(size) >= MIN_SIDE


class LogoService:
    def __init__(
        self,
        cache_dir: Path,
        *,
        sources: Sequence[LogoSource] = DEFAULT_SOURCES,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 8.0,
    ):
        self.dir = cache_dir / "logos"
        self.sources = tuple(sources)
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def _lock(self, ticker: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(ticker, threading.Lock())

    def get(self, ticker: str) -> bytes | None:
        """The logo PNG, or None when there is no usable logo for the ticker."""
        ticker = ticker.strip().upper()
        if not _TICKER.match(ticker):
            return None
        image = self.dir / f"{ticker}.png"
        miss = self.dir / f"{ticker}.miss"
        with self._lock(ticker):
            if image.exists():
                return image.read_bytes()
            if miss.exists() and time.time() - miss.stat().st_mtime < MISS_TTL:
                return None
            self.dir.mkdir(parents=True, exist_ok=True)
            failed = False
            for source in self.sources:
                try:
                    response = self._client.get(source.url_for(ticker))
                except httpx.HTTPError as exc:
                    log.debug("logo for %s: %s failed (%s)", ticker, source.name, exc)
                    failed = True
                    continue
                if response.status_code == 200 and usable(response.content):
                    tmp = image.with_name(image.name + ".tmp")
                    tmp.write_bytes(response.content)
                    tmp.replace(image)
                    return response.content
                failed |= response.status_code >= 500 or response.status_code == 429
            # Only mark "missing" when every source answered; a network failure
            # deserves another attempt next time.
            if not failed:
                miss.touch()
            return None
