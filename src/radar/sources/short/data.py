"""FINRA short interest and daily short volume, and SEC fails-to-deliver files."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

FINRA_SHORT_INTEREST_URL = (
    "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
)
FINRA_SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"
FTD_PAGE_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
FTD_FILE_URL = "https://www.sec.gov/files/data/fails-deliver-data/{name}"

# FINRA market class codes of exchange-listed securities (everything except "OTC").
OTC_CODES = frozenset({"OTC", "ADF"})
# Fund-like names are excluded from the short signals: they are not companies.
FUND_WORDS = (
    "ETF",
    "ETN",
    "FUND",
    "TRUST",
    "ISHARES",
    "PROSHARES",
    "DIREXION",
    "SPDR",
    "INVESCO",
    "LEVERAGED",
)

# FINRA publishes about 7 business days after the settlement date; 10 is a safety margin.
SHORT_INTEREST_LAG_BDAYS = 10


@dataclass(frozen=True)
class ShortInterest:
    symbol: str
    name: str
    settlement_date: date
    market: str
    short_shares: float
    previous_short_shares: float | None
    avg_daily_volume: float | None
    days_to_cover: float | None
    change_pct: float | None

    @property
    def listed(self) -> bool:
        return self.market not in OTC_CODES

    @property
    def fund_like(self) -> bool:
        upper = f" {self.name.upper()} "
        return any(f" {word} " in upper or upper.strip().endswith(word) for word in FUND_WORDS)


def _float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_short_interest(rows: Iterable[dict]) -> list[ShortInterest]:
    out: list[ShortInterest] = []
    for row in rows:
        try:
            settled = date.fromisoformat(row["settlementDate"])
            symbol = str(row["symbolCode"]).strip().upper()
        except (KeyError, TypeError, ValueError):
            continue
        current = _float(row.get("currentShortPositionQuantity"))
        if not symbol or current is None:
            continue
        out.append(
            ShortInterest(
                symbol=symbol,
                name=str(row.get("issueName") or ""),
                settlement_date=settled,
                market=str(row.get("marketClassCode") or ""),
                short_shares=current,
                previous_short_shares=_float(row.get("previousShortPositionQuantity")),
                avg_daily_volume=_float(row.get("averageDailyVolumeQuantity")),
                days_to_cover=_float(row.get("daysToCoverQuantity")),
                change_pct=_float(row.get("changePercent")),
            )
        )
    return out


def short_interest_request(settlement: date, offset: int = 0, limit: int = 5000) -> dict:
    return {
        "limit": limit,
        "offset": offset,
        "compareFilters": [
            {
                "compareType": "EQUAL",
                "fieldName": "settlementDate",
                "fieldValue": settlement.isoformat(),
            }
        ],
    }


def publication_date(settlement: date, lag_bdays: int = SHORT_INTEREST_LAG_BDAYS) -> date:
    """Conservative public date of a FINRA short-interest settlement date."""
    return (
        np.busday_offset(np.datetime64(settlement, "D"), lag_bdays, roll="forward")
        .astype("datetime64[D]")
        .item()
    )


def load_short_interest_file(path: Path) -> list[ShortInterest]:
    return parse_short_interest(json.loads(path.read_text()))


@dataclass(frozen=True)
class ShortVolume:
    symbol: str
    day: date
    short_volume: float
    total_volume: float

    @property
    def ratio(self) -> float | None:
        return self.short_volume / self.total_volume if self.total_volume else None


def parse_short_volume(text: str) -> list[ShortVolume]:
    out: list[ShortVolume] = []
    for line in text.splitlines()[1:]:
        parts = line.strip().split("|")
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            out.append(
                ShortVolume(
                    symbol=parts[1].upper(),
                    day=datetime.strptime(parts[0], "%Y%m%d").date(),
                    short_volume=float(parts[2]),
                    total_volume=float(parts[4]),
                )
            )
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ fails-to-deliver


@dataclass(frozen=True)
class Fail:
    settlement_date: date
    cusip: str
    symbol: str
    quantity: float
    description: str
    price: float | None


def ftd_name(year: int, month: int, half: str) -> str:
    return f"cnsfails{year}{month:02d}{half}.zip"


_FTD_HREF = re.compile(r'href="([^"]*/cnsfails(\d{4})(\d{2})([ab])(?:_\d+)?\.zip)"')


def ftd_links(page_html: str) -> dict[tuple[int, int, str], str]:
    """(year, month, half) → absolute URL, from the SEC page.

    Most files sit under /files/data/fails-deliver-data/, but some halves were
    published under other folders or with a suffix ("cnsfails202308b_0.zip").
    """
    out: dict[tuple[int, int, str], str] = {}
    for m in _FTD_HREF.finditer(page_html):
        href = m.group(1)
        url = href if href.startswith("http") else "https://www.sec.gov" + href
        out.setdefault((int(m.group(2)), int(m.group(3)), m.group(4)), url)
    return out


def ftd_rule_date(year: int, month: int, half: str) -> date:
    """Conservative posting date: first half → month end + 3 days; second → 18th next month."""
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    if half == "a":
        return nxt - timedelta(days=1) + timedelta(days=3)
    return nxt.replace(day=18)


def ftd_available_date(year: int, month: int, half: str, last_modified: date | None) -> date:
    rule = ftd_rule_date(year, month, half)
    return max(rule, last_modified) if last_modified else rule


def parse_ftd(content: bytes) -> list[Fail]:
    """Rows of one half-month file (zip or plain text). The trailer lines are skipped."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            content = archive.read(archive.namelist()[0])
    text = content.decode("latin-1")
    out: list[Fail] = []
    for line in text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        try:
            settled = datetime.strptime(parts[0].strip(), "%Y%m%d").date()
            quantity = float(parts[3])
        except ValueError:
            continue
        price = _float(parts[5].strip())
        out.append(
            Fail(
                settled,
                parts[1].strip().upper(),
                parts[2].strip().upper(),
                quantity,
                parts[4].strip(),
                price,
            )
        )
    return out


class CusipMap:
    """CUSIP → most recent symbol seen in the SEC fails-to-deliver files.

    The latest symbol matches what price sources use today (a ticker can change
    while the CUSIP stays, as FB → META).
    """

    def __init__(self) -> None:
        self._latest: dict[str, tuple[date, str]] = {}

    def add(self, fails: Iterable[Fail]) -> None:
        for fail in fails:
            if not fail.cusip or not fail.symbol:
                continue
            seen = self._latest.get(fail.cusip)
            if seen is None or fail.settlement_date >= seen[0]:
                self._latest[fail.cusip] = (fail.settlement_date, fail.symbol)

    def symbol(self, cusip: str) -> str:
        found = self._latest.get(cusip)
        return found[1] if found else ""

    def __len__(self) -> int:
        return len(self._latest)
