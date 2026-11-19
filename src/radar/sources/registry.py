"""SEC registrants by ticker and by CIK, from the current `company_tickers.json`."""

from __future__ import annotations

import json

from radar.backtest.datasets import normalize_symbol
from radar.edgar import normalize_cik
from radar.tickers import TICKERS_URL


class Registry:
    """SEC registrants by ticker and by CIK (current `company_tickers.json`)."""

    def __init__(self, payload: dict):
        self.by_ticker: dict[str, tuple[str, str, str]] = {}
        self.by_cik: dict[str, str] = {}
        for item in payload.values():
            cik = normalize_cik(item.get("cik_str"))
            ticker = normalize_symbol(item.get("ticker"))
            if not cik or not ticker:
                continue
            self.by_ticker.setdefault(ticker, (cik, ticker, item.get("title", "")))
            self.by_cik.setdefault(cik, ticker)

    @classmethod
    def load(cls, client) -> Registry:
        return cls(json.loads(client.get_bytes(TICKERS_URL, max_age=7 * 86_400)))

    def registrant(self, symbol: str) -> tuple[str, str, str] | None:
        return self.by_ticker.get(normalize_symbol(symbol))

    def ticker_for(self, cik: str, fallback: str = "") -> str:
        return self.by_cik.get(normalize_cik(cik)) or normalize_symbol(fallback)
