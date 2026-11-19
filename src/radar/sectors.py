"""An issuer's sector from the SIC code the SEC keeps in the company registry.

SIC has hundreds of codes; the dashboard needs a few readable groups. The table
below folds SIC ranges into twelve sectors. It is an approximation: SIC is old
and misclassifies newer companies (a lot of technology falls under "services").
The labels are stable English codes; the dashboard translates them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from radar.edgar import normalize_cik
from radar.funds import NO_SIC, IssuerProfile, files_as_investment_company
from radar.http import SecClient, SecHttpError

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
CACHE_NAME = "sectors.json"
# CIK → whether the filer files registered-fund reports (only looked up for issuers
# without a SIC, see radar.funds).
FUND_CACHE_NAME = "investment-companies.json"
LEGACY_CACHE_NAME = "setores.json"  # name used by the first version

UNKNOWN = "Unclassified"
SECTORS = (
    "Healthcare",
    "Technology",
    "Financials",
    "Real Estate",
    "Energy",
    "Utilities",
    "Materials",
    "Industrials",
    "Consumer",
    "Communication",
    "Services",
    UNKNOWN,
)

# (start, end, sector), checked in order: the first range containing the code wins.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (2830, 2836, "Healthcare"),
    (3840, 3851, "Healthcare"),
    (8000, 8099, "Healthcare"),
    (8731, 8734, "Healthcare"),
    (3570, 3579, "Technology"),
    (3660, 3679, "Technology"),
    (3820, 3829, "Technology"),
    (7370, 7379, "Technology"),
    (6500, 6599, "Real Estate"),
    (6798, 6798, "Real Estate"),
    (6000, 6799, "Financials"),
    (1200, 1399, "Energy"),
    (2900, 2999, "Energy"),
    (4600, 4699, "Energy"),
    (4900, 4999, "Utilities"),
    (1000, 1199, "Materials"),
    (1400, 1499, "Materials"),
    (2400, 2499, "Materials"),
    (2600, 2699, "Materials"),
    (2800, 2899, "Materials"),
    (3200, 3399, "Materials"),
    (4800, 4899, "Communication"),
    (2700, 2799, "Communication"),
    (7800, 7849, "Communication"),
    (1500, 1799, "Industrials"),
    (3400, 3569, "Industrials"),
    (3580, 3659, "Industrials"),
    (3680, 3699, "Industrials"),
    (3700, 3799, "Industrials"),
    (3800, 3819, "Industrials"),
    (4000, 4599, "Industrials"),
    (4700, 4799, "Industrials"),
    (100, 999, "Consumer"),
    (2000, 2399, "Consumer"),
    (2500, 2599, "Consumer"),
    (3000, 3199, "Consumer"),
    (3852, 3999, "Consumer"),
    (5000, 5999, "Consumer"),
    (7000, 7299, "Consumer"),
    (7500, 7699, "Consumer"),
    (7850, 7999, "Consumer"),
    (8200, 8299, "Consumer"),
    (7300, 7399, "Services"),
    (8100, 8999, "Services"),
)


def sector_for_sic(sic: str | int | None) -> str:
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return UNKNOWN
    for low, high, sector in _RANGES:
        if low <= code <= high:
            return sector
    return UNKNOWN


class SectorLookup:
    """Looks up the SIC in the SEC registry, one request per company.

    Each company's registry entry is a JSON of hundreds of kilobytes of which only
    the SIC matters (plus, for issuers without a SIC, whether they file the reports
    of a registered fund). So the response does not go to the download cache: what
    stays on disk are two small files keyed by CIK.
    """

    def __init__(self, client: SecClient, *, cache_file: Path | None = None, flush_every: int = 25):
        self._client = client
        self._file = cache_file or client.cache_dir / CACHE_NAME
        self._fund_file = self._file.with_name(FUND_CACHE_NAME)
        if cache_file is None:
            _adopt_legacy_cache(client.cache_dir / LEGACY_CACHE_NAME, self._file)
        self._flush_every = flush_every
        self._sic: dict[str, str] | None = None
        self._funds: dict[str, bool] | None = None
        self._dirty = 0

    def _load(self) -> dict[str, str]:
        if self._sic is None:
            self._sic = _read_json(self._file)
        return self._sic

    def _load_funds(self) -> dict[str, bool]:
        if self._funds is None:
            self._funds = _read_json(self._fund_file)
        return self._funds

    def flush(self) -> None:
        """Writes to disk what was looked up since the last write."""
        if self._sic is None or not self._dirty:
            return
        _write_json(self._file, self._sic)
        if self._funds is not None:
            _write_json(self._fund_file, self._funds)
        self._dirty = 0

    def _fetch(self, key: str) -> bool:
        """Asks the SEC registry about `key`; False when it did not answer."""
        try:
            raw = self._client.get_bytes(
                SUBMISSIONS_URL.format(cik=int(key)), max_age=0, retries=1, store=False
            )
            data = json.loads(raw)
            sic = str(data.get("sic") or "")
            forms = ((data.get("filings") or {}).get("recent") or {}).get("form") or []
        except (SecHttpError, ValueError, AttributeError) as exc:
            log.debug("no SIC for CIK %s: %s", key, exc)
            return False
        self._load()[key] = sic
        self._load_funds()[key] = files_as_investment_company(forms)
        self._dirty += 1
        if self._dirty >= self._flush_every:
            self.flush()
        return True

    def lookup(self, cik: str) -> tuple[str, str] | None:
        """Returns (sic, sector), or None if the SEC did not answer (worth retrying later)."""
        key = normalize_cik(cik)
        if not key.isdigit():
            return "", UNKNOWN
        known = self._load()
        if key not in known and not self._fetch(key):
            return None
        return known[key], sector_for_sic(known[key])

    def get(self, cik: str) -> tuple[str, str]:
        """Like `lookup`, but without an SEC answer returns ("", "Unclassified")."""
        return self.lookup(cik) or ("", UNKNOWN)

    def profile(self, cik: str) -> IssuerProfile | None:
        """SIC and fund-like filings of the issuer; None if the SEC did not answer.

        An issuer with a real SIC is never asked again; one without a SIC cached by an
        older version (before the fund check existed) is asked once more.
        """
        key = normalize_cik(cik)
        if not key.isdigit():
            return None
        known = self._load()
        funds = self._load_funds()
        sic = known.get(key)
        if sic is None or (sic.strip() in NO_SIC and key not in funds):
            if not self._fetch(key):
                return None
            sic = known[key]
        return IssuerProfile(sic=sic, investment_company=funds.get(key))


def cached_profiles(cache_dir: Path) -> Callable[[str], IssuerProfile | None]:
    """Profile lookup from the SIC caches on disk only, never asking the SEC (REPLAY)."""
    sic = _read_json(cache_dir / CACHE_NAME)
    funds = _read_json(cache_dir / FUND_CACHE_NAME)

    def profile(cik: str) -> IssuerProfile | None:
        key = normalize_cik(cik)
        if key not in sic:
            return None
        return IssuerProfile(sic=str(sic[key] or ""), investment_company=funds.get(key))

    return profile


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _adopt_legacy_cache(old: Path, new: Path) -> None:
    """Moves the SIC cache from its old file name, merging it if both files exist."""
    if not old.exists():
        return
    try:
        merged = json.loads(old.read_text(encoding="utf-8"))
        if new.exists():
            merged.update(json.loads(new.read_text(encoding="utf-8")))
        tmp = new.with_name(new.name + ".tmp")
        tmp.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
        tmp.replace(new)
        old.unlink()
    except (OSError, ValueError) as exc:
        log.debug("could not move %s to %s: %s", old, new, exc)
