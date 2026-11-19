"""Point-in-time 8-K / NT history from EDGAR full-text search.

Items-based rules search the item heading ("Item 1.03") and keep only filings whose
EDGAR `items` metadata contains that item. Text rules search each fixed phrase.
Queries are monthly so none reaches the 10,000-hit cap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

from ..base import split_display_name
from ..efts import EftsHit, months, search
from .rules import Filing8K
from .text import BUYBACK_PHRASES, EXIT_PHRASES, exit_titles

ITEM_QUERIES = {"1.03": "Item 1.03", "4.01": "Item 4.01"}


@dataclass
class HistoryStats:
    queries: int = 0
    hits: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)


def _base(hit: EftsHit) -> Filing8K | None:
    if not hit.names:
        return None
    name, tickers, cik = split_display_name(hit.names[0])
    cik = cik or (str(int(hit.ciks[0])) if hit.ciks else "")
    if not cik:
        return None
    return Filing8K(
        accession=hit.accession,
        form=hit.form,
        cik=cik,
        name=name,
        filing_date=hit.file_date,
        ticker=tickers[0] if tickers else "",
        items=hit.items,
    )


def load_filings(
    client,
    start: date,
    end: date,
    *,
    progress: Callable[[date], None] | None = None,
) -> tuple[list[Filing8K], HistoryStats]:
    stats = HistoryStats()
    filings: dict[str, Filing8K] = {}

    def merge(hit: EftsHit, rule: str, **changes) -> None:
        stats.hits += 1
        current = filings.get(hit.accession) or _base(hit)
        if current is None:
            return
        for key, value in changes.items():
            if isinstance(value, tuple):
                value = tuple(dict.fromkeys(getattr(current, key) + value))
            changes[key] = value
        if hit.items and not current.items:
            changes["items"] = hit.items
        filings[hit.accession] = replace(current, **changes)
        stats.by_rule[rule] = stats.by_rule.get(rule, 0) + 1

    for first, last in months(start, end):
        if progress:
            progress(first)
        for phrase in BUYBACK_PHRASES:
            stats.queries += 1
            for hit in search(client, forms="8-K", start=first, end=last, q=f'"{phrase}"'):
                if hit.form == "8-K":
                    merge(hit, "buyback", buyback_phrases=(phrase,))
        for phrase in EXIT_PHRASES:
            stats.queries += 1
            for hit in search(client, forms="8-K", start=first, end=last, q=f'"{phrase}"'):
                if hit.form == "8-K" and "5.02" in hit.items:
                    merge(
                        hit,
                        "exit",
                        exit_phrases=(phrase,),
                        exit_titles=tuple(exit_titles([phrase])),
                    )
        for item, query in ITEM_QUERIES.items():
            stats.queries += 1
            for hit in search(client, forms="8-K", start=first, end=last, q=f'"{query}"'):
                if hit.form == "8-K" and item in hit.items:
                    merge(hit, f"item_{item}")
        stats.queries += 1
        for hit in search(client, forms="NT 10-K,NT 10-Q", start=first, end=last):
            if hit.form in ("NT 10-K", "NT 10-Q"):
                merge(hit, "nt")
    return sorted(filings.values(), key=lambda f: (f.filing_date, f.accession)), stats
