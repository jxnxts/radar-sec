"""Point-in-time Form 144 history from EDGAR full-text search (one query per day)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ..base import split_display_name
from ..efts import EftsHit, days, search
from .rules import Notice

# Electronic Form 144 became mandatory on 2023-04-13; earlier notices were on paper.
ELECTRONIC_SINCE = date(2023, 4, 13)


@dataclass
class HistoryStats:
    hits: int = 0
    filings: int = 0
    amendments: int = 0
    unparsed: int = 0


def notice_from_hit(hit: EftsHit) -> Notice | None:
    """efts lists the subject company first and the reporting person second."""
    if len(hit.names) < 2 or len(hit.ciks) < 2:
        return None
    issuer_name, tickers, issuer_cik = split_display_name(hit.names[0])
    seller_name, _, seller_cik = split_display_name(hit.names[1])
    issuer_cik = issuer_cik or str(int(hit.ciks[0]))
    seller_cik = seller_cik or str(int(hit.ciks[1]))
    if not issuer_cik or not seller_cik or issuer_cik == seller_cik:
        return None
    return Notice(
        accession=hit.accession,
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        seller_cik=seller_cik,
        seller_name=seller_name,
        filing_date=hit.file_date,
        ticker=tickers[0] if tickers else "",
    )


def load_notices(
    client,
    start: date,
    end: date,
    *,
    progress: Callable[[date], None] | None = None,
) -> tuple[list[Notice], HistoryStats]:
    stats = HistoryStats()
    seen: set[str] = set()
    notices: list[Notice] = []
    for day in days(max(start, ELECTRONIC_SINCE), end):
        if progress:
            progress(day)
        for hit in search(client, forms="144", start=day, end=day):
            stats.hits += 1
            if hit.accession in seen:
                continue
            seen.add(hit.accession)
            if hit.form.endswith("/A"):
                stats.amendments += 1
                continue
            notice = notice_from_hit(hit)
            if notice is None:
                stats.unparsed += 1
                continue
            stats.filings += 1
            notices.append(notice)
    return notices, stats
