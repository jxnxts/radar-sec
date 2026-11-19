"""EDGAR `getcurrent` feed pages for the extra forms, keeping each entry's summary.

The base feed reader drops the Atom `<summary>`; for 8-K it carries the item list
("Item 5.02: ..."), which saves one download per filing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from defusedxml import ElementTree as ET

from radar.feed import ATOM, feed_url, group_entries, parse_feed
from radar.http import SecHttpError
from radar.models import FilingRef

_ACCESSION = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")


@dataclass(frozen=True)
class FeedItem:
    ref: FilingRef
    summary: str
    filer_ciks: tuple[str, ...] = ()


def summaries(content: bytes) -> dict[str, str]:
    root = ET.fromstring(content)
    out: dict[str, str] = {}
    for node in root.iter(f"{ATOM}entry"):
        acc = _ACCESSION.search(node.findtext(f"{ATOM}id") or "")
        if acc:
            out.setdefault(acc.group(1), node.findtext(f"{ATOM}summary") or "")
    return out


def reporting_ciks(content: bytes) -> dict[str, list[str]]:
    """Accession → CIKs of the entries whose role is "Reporting" (the Form 144 seller)."""
    out: dict[str, list[str]] = {}
    for entry in parse_feed(content):
        if entry.role == "Reporting":
            out.setdefault(entry.accession, []).append(entry.cik)
    return out


def fetch_items(
    client,
    form: str,
    *,
    is_known: Callable[[str], bool],
    count: int = 100,
    max_pages: int = 3,
    retries: int | None = 1,
) -> list[FeedItem]:
    """Newest filings of one form, paging until a known accession shows up."""
    items: dict[str, FeedItem] = {}
    for page in range(max_pages):
        try:
            content = client.get_bytes(
                feed_url(form, start=page * count, count=count), max_age=0, retries=retries
            )
        except SecHttpError:
            if page == 0:
                raise
            break
        entries = parse_feed(content)
        texts = summaries(content)
        reporters = reporting_ciks(content)
        refs = group_entries(entries)
        for ref in refs:
            items.setdefault(
                ref.accession,
                FeedItem(
                    ref, texts.get(ref.accession, ""), tuple(reporters.get(ref.accession, ()))
                ),
            )
        if len(entries) < count or any(is_known(r.accession) for r in refs):
            break
    return list(items.values())
