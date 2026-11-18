"""The SEC's CIK → ticker map, used to give a ticker to 13D signals (which do not report one)."""

from __future__ import annotations

import json
import logging

from radar.edgar import normalize_cik
from radar.http import SecClient, SecHttpError

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class TickerMap:
    """Loads the map on demand. If the SEC does not answer, returns an empty ticker."""

    def __init__(self, client: SecClient, *, max_age: float = 86_400):
        self._client = client
        self._max_age = max_age
        self._map: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._map is None:
            self._map = {}
            try:
                data = json.loads(self._client.get_bytes(TICKERS_URL, max_age=self._max_age))
                for item in data.values():
                    # The file is sorted by market cap: the first occurrence
                    # of a CIK is the main share class.
                    self._map.setdefault(normalize_cik(item["cik_str"]), item["ticker"])
            except (SecHttpError, ValueError, KeyError, TypeError) as exc:
                log.warning("could not load the ticker map: %s", exc)
        return self._map

    def get(self, cik: str) -> str:
        return self._load().get(normalize_cik(cik), "")
