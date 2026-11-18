"""Approximate market cap on the signal date, without using future information.

Shares outstanding come from the 10-Q/10-K cover page (XBRL, the SEC "frames"
API): one request per quarter covers every company. For each signal we use the
latest figure whose reference date is at least `lag_days` before the signal,
which guarantees the report had already been published.
"""

from __future__ import annotations

import json
import logging
from bisect import bisect_right
from datetime import date, timedelta

from radar.backtest.datasets import Quarter
from radar.edgar import normalize_cik
from radar.http import SecClient, SecHttpError

log = logging.getLogger(__name__)

FRAME_URL = (
    "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/"
    "CY{year}Q{quarter}I.json"
)


class SharesOutstanding:
    def __init__(self) -> None:
        self._by_cik: dict[str, list[tuple[date, float]]] = {}
        self.frames_loaded = 0

    def add_frame(self, payload: dict) -> None:
        for item in payload.get("data", []):
            try:
                day = date.fromisoformat(item["end"])
                value = float(item["val"])
            except (KeyError, TypeError, ValueError):
                continue
            if value > 0:
                self._by_cik.setdefault(normalize_cik(item.get("cik")), []).append((day, value))
        self.frames_loaded += 1

    def finish(self) -> None:
        for values in self._by_cik.values():
            values.sort()

    @classmethod
    def load(cls, client: SecClient, quarters: list[Quarter]) -> SharesOutstanding:
        store = cls()
        for year, quarter in quarters:
            url = FRAME_URL.format(year=year, quarter=quarter)
            try:
                store.add_frame(json.loads(client.get_bytes(url, max_age=30 * 86_400)))
            except (SecHttpError, ValueError) as exc:
                log.warning("no shares outstanding for %dQ%d: %s", year, quarter, exc)
        store.finish()
        return store

    def as_of(
        self, cik: str, day: date, *, lag_days: int = 45, max_age_days: int = 400
    ) -> float | None:
        values = self._by_cik.get(normalize_cik(cik))
        if not values:
            return None
        cutoff = day - timedelta(days=lag_days)
        index = bisect_right(values, (cutoff, float("inf"))) - 1
        if index < 0:
            return None
        ref_day, shares = values[index]
        return shares if (day - ref_day).days <= max_age_days else None
