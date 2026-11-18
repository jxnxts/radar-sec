"""EDGAR's "getcurrent" Atom feed: the latest filings, by form type."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlencode

from defusedxml import ElementTree as ET

from radar.edgar import normalize_cik
from radar.http import SecClient
from radar.models import FilingRef

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
VALID_COUNTS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)

# "4 - CIENA CORP (0000936395) (Issuer)"
_TITLE = re.compile(r"^(?P<form>.+?) - (?P<name>.+) \((?P<cik>\d{1,10})\) \((?P<role>[^()]+)\)\s*$")
_ACCESSION = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
_FILED = re.compile(r"Filed:\s*(?:</b>)?\s*(\d{4}-\d{2}-\d{2})")

# Roles that identify the company the filing is about (rather than who filed it).
_SUBJECT_ROLES = ("Issuer", "Subject")


@dataclass(frozen=True)
class FeedEntry:
    accession: str
    form: str
    name: str
    cik: str
    role: str
    filed_date: date
    updated: datetime | None
    index_url: str


def feed_url(form_type: str, *, start: int = 0, count: int = 100) -> str:
    if count not in VALID_COUNTS:
        raise ValueError(f"count must be one of {VALID_COUNTS}")
    query = urlencode(
        {
            "action": "getcurrent",
            "type": form_type,
            "company": "",
            "dateb": "",
            "owner": "include",
            "start": start,
            "count": count,
            "output": "atom",
        }
    )
    return f"{FEED_URL}?{query}"


def parse_feed(content: bytes | str) -> list[FeedEntry]:
    """Extracts the feed entries. Entries that cannot be understood are skipped."""
    root = ET.fromstring(content)
    entries: list[FeedEntry] = []
    for node in root.iter(f"{ATOM}entry"):
        title = (node.findtext(f"{ATOM}title") or "").strip()
        match = _TITLE.match(title)
        acc = _ACCESSION.search(node.findtext(f"{ATOM}id") or "")
        link = node.find(f"{ATOM}link")
        href = link.get("href", "") if link is not None else ""
        if not match or not acc or not href:
            log.debug("feed entry skipped: %r", title)
            continue

        category = node.find(f"{ATOM}category")
        form = (category.get("term") if category is not None else None) or match["form"]

        updated_raw = (node.findtext(f"{ATOM}updated") or "").strip()
        try:
            updated = datetime.fromisoformat(updated_raw) if updated_raw else None
        except ValueError:
            updated = None

        filed_match = _FILED.search(node.findtext(f"{ATOM}summary") or "")
        if filed_match:
            filed = date.fromisoformat(filed_match.group(1))
        elif updated:
            filed = updated.date()
        else:
            continue

        entries.append(
            FeedEntry(
                accession=acc.group(1),
                form=form.strip(),
                name=match["name"].strip(),
                cik=normalize_cik(match["cik"]),
                role=match["role"].strip(),
                filed_date=filed,
                updated=updated,
                index_url=href,
            )
        )
    return entries


def group_entries(entries: list[FeedEntry]) -> list[FilingRef]:
    """Groups the entries by accession number.

    The feed repeats the same filing once per party (issuer, filer...).
    We keep one reference per filing, preferring the subject company as "owner".
    """
    grouped: dict[str, list[FeedEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.accession, []).append(entry)

    refs: list[FilingRef] = []
    for accession, group in grouped.items():
        subject = next((e for e in group if e.role in _SUBJECT_ROLES), group[0])
        filers = tuple(e.name for e in group if e is not subject)
        refs.append(
            FilingRef(
                accession=accession,
                form=subject.form,
                cik=subject.cik,
                company=subject.name,
                filed_date=subject.filed_date,
                url=subject.index_url,
                accepted_at=subject.updated,
                filers=filers,
            )
        )
    return refs


def fetch_current(
    client: SecClient,
    form_type: str,
    *,
    is_known: Callable[[str], bool] = lambda accession: False,
    count: int = 100,
    max_pages: int = 5,
    first_page: bytes | None = None,
) -> list[FilingRef]:
    """Fetches the latest filings of a type, paging until it hits one already seen.

    `first_page` lets the caller reuse the first page when it was already downloaded
    (the monitor fetches the first page of every feed in parallel).
    """
    refs: dict[str, FilingRef] = {}
    for page in range(max_pages):
        if page == 0 and first_page is not None:
            content = first_page
        else:
            content = client.get_bytes(
                feed_url(form_type, start=page * count, count=count), max_age=0
            )
        entries = parse_feed(content)
        page_refs = group_entries(entries)
        for ref in page_refs:
            refs.setdefault(ref.accession, ref)
        # Short page = end of the feed; known filing = we have caught up with the past.
        if len(entries) < count or any(is_known(r.accession) for r in page_refs):
            break
    return list(refs.values())
