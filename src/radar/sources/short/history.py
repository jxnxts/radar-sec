"""Short-interest and fails-to-deliver history (FINRA API pages and SEC zips, cached)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from radar.http import RateLimiter
from radar.models import Signal

from ..base import cooldown_filter
from .data import (
    FINRA_SHORT_INTEREST_URL,
    FTD_PAGE_URL,
    CusipMap,
    ShortInterest,
    ftd_available_date,
    ftd_links,
    ftd_name,
    parse_ftd,
    parse_short_interest,
    publication_date,
    short_interest_request,
)
from .rules import (
    COOLDOWN_DAYS,
    Registrant,
    crowded_shorts,
    persistent_fails,
    squeeze_candidates,
)

log = logging.getLogger(__name__)

FTD_LAST_MODIFIED = "sec-ftd-last-modified.json"


class FinraClient:
    """FINRA Query API (public datasets need no credentials). Results are cached on disk."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        rate_per_second: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.folder = cache_dir / "finra" / "short-interest"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._limiter = RateLimiter(rate_per_second)
        self._http = httpx.Client(timeout=60, transport=transport)

    def close(self) -> None:
        self._http.close()

    def short_interest(self, settlement: date, *, refresh: bool = False) -> list[ShortInterest]:
        path = self.folder / f"{settlement.isoformat()}.json"
        if path.exists() and not refresh:
            return parse_short_interest(json.loads(path.read_text()))
        rows: list[dict] = []
        offset = 0
        while True:
            self._limiter.acquire()
            response = self._http.post(
                FINRA_SHORT_INTEREST_URL,
                json=short_interest_request(settlement, offset),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            page = response.json() if response.content else []
            rows += page
            total = int(response.headers.get("record-total", len(rows)))
            offset += 5000
            if not page or offset >= total:
                break
        if rows:
            path.write_text(json.dumps(rows, separators=(",", ":")))
        return parse_short_interest(rows)

    def settlement_dates(self, probe_symbol: str = "AAPL") -> list[date]:
        """All settlement dates FINRA has, read from one always-present symbol."""
        self._limiter.acquire()
        response = self._http.post(
            FINRA_SHORT_INTEREST_URL,
            json={
                "limit": 5000,
                "fields": ["settlementDate"],
                "compareFilters": [
                    {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": probe_symbol}
                ],
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return sorted({date.fromisoformat(r["settlementDate"]) for r in response.json()})

    def cached_dates(self) -> list[date]:
        return sorted(date.fromisoformat(p.stem) for p in self.folder.glob("*.json"))


@dataclass
class ShortHistory:
    crowded: list[Signal] = field(default_factory=list)
    squeeze_candidates: list = field(default_factory=list)
    fails: list[Signal] = field(default_factory=list)
    settlement_dates: int = 0
    ftd_files: int = 0


def load_short_interest(
    finra: FinraClient, start: date, end: date, registrant: Registrant
) -> ShortHistory:
    out = ShortHistory()
    dates = [d for d in finra.cached_dates() if start <= publication_date(d) <= end]
    for settlement in dates:
        records = finra.short_interest(settlement)
        out.settlement_dates += 1
        out.crowded += crowded_shorts(records, registrant, publication_date)
        out.squeeze_candidates += squeeze_candidates(records, registrant)
    out.crowded = cooldown_filter(out.crowded, COOLDOWN_DAYS)
    return out


def ftd_halves(start: date, end: date) -> list[tuple[int, int, str]]:
    halves = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        halves += [(year, month, "a"), (year, month, "b")]
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return halves


def load_fails(
    client,
    cache_dir: Path,
    start: date,
    end: date,
    registrant: Registrant,
    shares_outstanding: Callable[[str, date], float | None],
    cusips: CusipMap | None = None,
) -> tuple[list[Signal], int]:
    """`ftd_persistent` signals dated by availability in [start, end]. Also feeds `cusips`."""
    links = ftd_links(client.get_text(FTD_PAGE_URL, max_age=7 * 86_400))
    meta_path = cache_dir / FTD_LAST_MODIFIED
    last_modified = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    signals: list[Signal] = []
    files = 0
    for year, month, half in ftd_halves(date(start.year, start.month, 1), end):
        url = links.get((year, month, half))
        if url is None:
            log.warning("fails-to-deliver %d-%02d%s is not listed by the SEC", year, month, half)
            continue
        name = url.rsplit("/", 1)[-1]
        if name not in last_modified:
            last_modified[name] = head_last_modified(client, url)
            meta_path.write_text(json.dumps(last_modified, indent=1, sort_keys=True))
        lm = last_modified.get(name)
        available = ftd_available_date(year, month, half, date.fromisoformat(lm) if lm else None)
        try:
            path = client.download(url)
        except Exception as exc:  # noqa: BLE001 - a missing half is reported, not fatal
            log.warning("fails-to-deliver %s unavailable: %s", name, exc)
            continue
        fails = parse_ftd(path.read_bytes())
        files += 1
        if cusips is not None:
            cusips.add(fails)
        if start <= available <= end:
            signals += persistent_fails(
                fails,
                available,
                registrant,
                shares_outstanding,
                file_name=ftd_name(year, month, half),
            )
    return cooldown_filter(signals, COOLDOWN_DAYS), files


def head_last_modified(client, url: str) -> str | None:
    """Posting date of a file (HTTP Last-Modified), through the SEC rate limiter."""
    from email.utils import parsedate_to_datetime

    client._limiter.acquire()
    try:
        response = client._client.head(url)
    except httpx.HTTPError:
        return None
    value = response.headers.get("last-modified") if response.status_code == 200 else None
    return parsedate_to_datetime(value).date().isoformat() if value else None


def build_cusip_map(cache_dir: Path) -> CusipMap:
    """CUSIP → latest symbol from every fails-to-deliver file already in the cache."""
    cusips = CusipMap()
    root = cache_dir / "www.sec.gov" / "files"
    for path in sorted(root.rglob("cnsfails*.zip")):
        try:
            cusips.add(parse_ftd(path.read_bytes()))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read %s: %s", path.name, exc)
    return cusips
