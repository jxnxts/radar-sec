"""Price, market value and liquidity of a signal's company, for the dashboard.

The backtests only found the "avoid" filters useful on liquid stocks (entry price
of at least US$ 5 and market value of at least US$ 300 million), so the dashboard
hides avoid signals of smaller or unknown companies by default.

- Price: the latest quote or close from the dashboard's price source (cached).
- Shares outstanding: the cover-page fact the backtest already uses
  (dei:EntityCommonStockSharesOutstanding). The backtest reads it from the SEC
  "frames" API, one file per quarter; live, one small "company concept" file per
  company is enough, cached on disk and refreshed at most once a day.
- Market value = price × shares outstanding. Unknown liquidity is not liquid.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from radar.config import DashboardConfig
from radar.edgar import normalize_cik
from radar.http import SecClient, SecHttpError
from radar.sources.base import AVOID
from radar.sources.form144.rules import FORM144_LARGE
from radar.sources.specs import SPECS

CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/"
    "EntityCommonStockSharesOutstanding.json"
)
CONCEPT_MAX_AGE = 86_400  # seconds: the SEC is asked again at most once a day per company
# A cover-page figure older than this is too stale to value the company today
# (foreign filers report it once a year, in the 20-F/40-F).
SHARES_MAX_AGE_DAYS = 550
# How long a stored price/market value stays valid before it is refreshed.
REFRESH_AFTER = timedelta(hours=20)

# Signals shown only for liquid companies by default: every "avoid" rule, plus the
# large planned sale (Form 144), which is context but reads as a bearish flag too.
LIQUIDITY_GATED_TYPES = frozenset(
    {kind for kind, spec in SPECS.items() if spec.direction == AVOID} | {FORM144_LARGE}
)

# symbols → {symbol: (price, as_of ISO)}
PriceLookup = Callable[[list[str]], dict[str, tuple[float, str]]]


def latest_shares(payload: dict[str, Any], today: date) -> tuple[float, date] | None:
    """The most recent shares-outstanding figure of a company concept JSON, or None.

    Among facts with the same reference date, the one filed last wins (an amendment
    or a later report repeating it).
    """
    best: tuple[date, str, float] | None = None
    for item in (payload.get("units") or {}).get("shares") or []:
        try:
            day = date.fromisoformat(item["end"])
            value = float(item["val"])
        except (KeyError, TypeError, ValueError):
            continue
        if value <= 0 or day > today:
            continue
        key = (day, str(item.get("filed") or ""), value)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None or (today - best[0]).days > SHARES_MAX_AGE_DAYS:
        return None
    return best[2], best[0]


class SharesLookup:
    """Shares outstanding per CIK from the SEC company concept API (disk cache, daily)."""

    def __init__(self, client: SecClient, *, today: Callable[[], date] = date.today):
        self._client = client
        self._today = today
        # CIKs without the fact (no XBRL, funds, foreign filers using IFRS tags): not asked
        # again until the next day.
        self._missing: dict[str, float] = {}

    def get(self, cik: str) -> tuple[float, date] | None:
        key = normalize_cik(cik)
        if not key.isdigit():
            return None
        missed = self._missing.get(key)
        if missed is not None and time.time() - missed < CONCEPT_MAX_AGE:
            return None
        try:
            raw = self._client.get_bytes(
                CONCEPT_URL.format(cik=int(key)), max_age=CONCEPT_MAX_AGE, retries=1
            )
            found = latest_shares(json.loads(raw), self._today())
        except (SecHttpError, ValueError) as exc:
            logging.getLogger(__name__).debug("no shares outstanding for %s: %s", key, exc)
            found = None
        if found is None:
            self._missing[key] = time.time()
        return found


@dataclass(frozen=True)
class Liquidity:
    """What is stored per signal (see `Database.set_liquidity`)."""

    symbol: str
    price: float | None
    price_as_of: str | None
    shares: float | None
    shares_as_of: str | None
    market_value: float | None
    liquid: bool


def market_value(price: float | None, shares: float | None) -> float | None:
    if price is None or shares is None or price <= 0 or shares <= 0:
        return None
    return price * shares


def is_liquid(price: float | None, value: float | None, cfg: DashboardConfig) -> bool:
    """Liquid = price and market value both known and at or above the thresholds."""
    if price is None or value is None:
        return False
    return price >= cfg.avoid_min_price and value >= cfg.avoid_min_market_value


def measure(
    symbol: str,
    price: tuple[float, str] | None,
    shares: tuple[float, date] | None,
    cfg: DashboardConfig,
) -> Liquidity:
    last = price[0] if price else None
    count = shares[0] if shares else None
    value = market_value(last, count)
    return Liquidity(
        symbol=symbol,
        price=last,
        price_as_of=price[1] if price else None,
        shares=count,
        shares_as_of=shares[1].isoformat() if shares else None,
        market_value=round(value, 2) if value is not None else None,
        liquid=is_liquid(last, value, cfg),
    )


def liquidity_fields(
    signal_type: str, stored: dict[str, Any] | None, cfg: DashboardConfig
) -> dict[str, Any]:
    """Fields added to every signal view. `liquid` is recomputed with the current
    thresholds, so changing radar.toml takes effect without refreshing the data."""
    price = stored.get("price") if stored else None
    value = stored.get("market_value") if stored else None
    return {
        "price": price,
        "price_as_of": stored.get("price_as_of") if stored else None,
        "market_value": value,
        "liquid": is_liquid(price, value, cfg),
        "liquidity_gated": signal_type in LIQUIDITY_GATED_TYPES,
    }
