"""EDGAR full-text search (efts.sec.gov): point-in-time history of filings by form,
date and exact phrase. Each hit is one document of a filing; callers dedupe by accession.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

log = logging.getLogger(__name__)

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
PAGE_SIZE = 100
MAX_HITS = 10_000  # efts never pages past this


@dataclass(frozen=True)
class EftsHit:
    accession: str
    form: str  # root form of the filing ("8-K", "144", "NT 10-K"...)
    file_type: str  # type of this document ("8-K", "EX-99.1"...)
    file_date: date
    ciks: tuple[str, ...]
    names: tuple[str, ...]  # display names: "Company  (TICK, TICK2)  (CIK 000...)"
    items: tuple[str, ...]


def efts_url(*, forms: str, start: date, end: date, q: str | None = None, offset: int = 0) -> str:
    """Search URL. Parameter order is fixed so the disk cache key is stable."""
    params: dict[str, object] = {}
    if q:
        params["q"] = q
    params["forms"] = forms
    params["dateRange"] = "custom"
    params["startdt"] = start.isoformat()
    params["enddt"] = end.isoformat()
    if offset:
        params["from"] = offset
    return f"{EFTS_URL}?{urlencode(params)}"


def parse_hits(payload: bytes | str) -> tuple[int, list[EftsHit]]:
    data = json.loads(payload)
    hits = data.get("hits", {})
    total = int((hits.get("total") or {}).get("value") or 0)
    out: list[EftsHit] = []
    for hit in hits.get("hits", []):
        src = hit.get("_source") or {}
        try:
            filed = date.fromisoformat(src["file_date"])
        except (KeyError, ValueError):
            continue
        accession = src.get("adsh") or str(hit.get("_id", "")).split(":")[0]
        if not accession:
            continue
        out.append(
            EftsHit(
                accession=accession,
                form=src.get("form") or (src.get("root_forms") or [""])[0],
                file_type=src.get("file_type") or "",
                file_date=filed,
                ciks=tuple(src.get("ciks") or ()),
                names=tuple(src.get("display_names") or ()),
                items=tuple(src.get("items") or ()),
            )
        )
    return total, out


def search(
    client,
    *,
    forms: str,
    start: date,
    end: date,
    q: str | None = None,
    max_age: float | None = None,
) -> Iterator[EftsHit]:
    """All hits of one query, page by page. Past windows never change, so they are
    cached for good (`max_age=None`); pass `max_age=0` for windows that include today."""
    offset = 0
    while True:
        payload = client.get_bytes(
            efts_url(forms=forms, start=start, end=end, q=q, offset=offset), max_age=max_age
        )
        total, hits = parse_hits(payload)
        yield from hits
        offset += PAGE_SIZE
        if not hits or offset >= min(total, MAX_HITS):
            if total > MAX_HITS:
                log.warning(
                    "efts: %s %s..%s has %d hits; only %d are reachable",
                    forms,
                    start,
                    end,
                    total,
                    MAX_HITS,
                )
            return


def months(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Calendar-month windows covering [start, end]."""
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        nxt = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        yield max(cursor, start), min(nxt - timedelta(days=1), end)
        cursor = nxt


def days(start: date, end: date) -> Iterator[date]:
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            yield cursor
        cursor += timedelta(days=1)
