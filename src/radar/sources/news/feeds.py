"""Where the news comes from and how each payload becomes `NewsItem`s.

Every URL here was checked by hand before being used (see the README). Parsing is
pure: the live poller downloads, these functions read bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from defusedxml import ElementTree as ET

from .model import NewsItem, clean_text, parse_time

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TIINGO_URL = "https://api.tiingo.com/tiingo/news"


@dataclass(frozen=True)
class Wire:
    name: str
    url: str
    note: str = ""
    # Keep only item URLs containing this (Business Wire also lists translations).
    url_must_contain: str = ""


# Public RSS feeds of the press-release wires. Only PR Newswire is on by default.
WIRES: dict[str, Wire] = {
    "prnewswire": Wire(
        "prnewswire",
        "https://www.prnewswire.com/rss/news-releases-list.rss",
        "all releases; only the latest 20, so it needs a short polling interval",
    ),
    "businesswire": Wire(
        "businesswire",
        "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFpRXg==",
        "all releases of about the last 24 hours (~1 MB); its robots.txt disallows /rss/ "
        "for generic agents (checked 2026-11-19), so it is off by default and the client "
        "refuses it while that stays so",
        url_must_contain="/en/",
    ),
    "globenewswire": Wire(
        "globenewswire",
        "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/"
        "GlobeNewswire%20-%20News%20about%20Public%20Companies",
        "answers 403 to automated clients (checked 2026-11-19); off by default",
    ),
}


class FeedFormatError(ValueError):
    """The payload is not the feed we expected (an error page, a rate-limit notice...)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(node, name: str):
    for child in node:
        if _local(child.tag) == name:
            return child
    return None


def _text(node, name: str) -> str:
    child = _child(node, name)
    return (child.text or "") if child is not None else ""


def parse_rss(content: bytes, feed: str) -> list[NewsItem]:
    """Items of an RSS 2.0 or Atom feed, in feed order."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FeedFormatError(f"{feed}: not XML ({exc})") from exc
    items: list[NewsItem] = []
    if _local(root.tag) == "feed":  # Atom
        entries = [n for n in root if _local(n.tag) == "entry"]
        for entry in entries:
            link = ""
            for child in entry:
                if _local(child.tag) == "link" and child.get("rel", "alternate") == "alternate":
                    link = child.get("href", "")
                    break
            raw = _text(entry, "published") or _text(entry, "updated")
            items.append(
                NewsItem(
                    feed=feed,
                    url=link.strip(),
                    title=clean_text(_text(entry, "title"), 500),
                    summary=clean_text(_text(entry, "summary") or _text(entry, "content")),
                    published_at=parse_time(raw),
                    published_raw=raw.strip(),
                )
            )
    else:
        channel = _child(root, "channel")
        if _local(root.tag) != "rss" or channel is None:
            raise FeedFormatError(f"{feed}: neither RSS nor Atom (<{_local(root.tag)}>)")
        for node in channel:
            if _local(node.tag) != "item":
                continue
            raw = _text(node, "pubDate") or _text(node, "date")
            items.append(
                NewsItem(
                    feed=feed,
                    url=(_text(node, "link") or _text(node, "guid")).strip(),
                    title=clean_text(_text(node, "title"), 500),
                    summary=clean_text(_text(node, "description")),
                    published_at=parse_time(raw),
                    published_raw=raw.strip(),
                )
            )
    return [i for i in items if i.url and i.title]


def gdelt_url(query: str, *, max_records: int = 250, timespan: str = "1h") -> str:
    """GDELT DOC 2.0 article list, newest first, as JSON."""
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max_records),
        "timespan": timespan,
        "sort": "datedesc",
    }
    return f"{GDELT_URL}?{urlencode(params)}"


def parse_gdelt(content: bytes) -> list[NewsItem]:
    """Articles of a GDELT DOC 2.0 `artlist` JSON answer.

    GDELT answers errors ("Timespan is too short.", rate-limit notices) as plain text
    with HTTP 200, so anything that is not the expected JSON raises FeedFormatError.
    """
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        return []  # GDELT sends an empty body when nothing matched
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise FeedFormatError(f"gdelt: {text[:160]}") from exc
    if not isinstance(payload, dict):
        raise FeedFormatError("gdelt: unexpected JSON")
    items: list[NewsItem] = []
    for article in payload.get("articles") or []:
        raw = str(article.get("seendate") or "")
        items.append(
            NewsItem(
                feed="gdelt",
                url=str(article.get("url") or "").strip(),
                title=clean_text(str(article.get("title") or ""), 500),
                published_at=parse_time(raw),
                published_raw=raw,
                extra={
                    "domain": article.get("domain") or "",
                    "language": article.get("language") or "",
                    "country": article.get("sourcecountry") or "",
                },
            )
        )
    return [i for i in items if i.url and i.title]


def tiingo_url(*, limit: int = 100, start: datetime | None = None) -> str:
    """Tiingo News, newest crawled first. The key goes in the Authorization header."""
    params = {"limit": str(limit), "sortBy": "crawlDate"}
    if start is not None:
        params["startDate"] = start.date().isoformat()
    return f"{TIINGO_URL}?{urlencode(params)}"


def parse_tiingo(content: bytes) -> list[NewsItem]:
    """Articles of a Tiingo News answer (a JSON list)."""
    try:
        payload = json.loads(content)
    except ValueError as exc:
        raise FeedFormatError(f"tiingo: not JSON ({exc})") from exc
    if not isinstance(payload, list):
        detail = payload.get("detail") if isinstance(payload, dict) else ""
        raise FeedFormatError(f"tiingo: unexpected answer {detail or ''}".strip())
    items: list[NewsItem] = []
    for article in payload:
        raw = str(article.get("publishedDate") or "")
        items.append(
            NewsItem(
                feed="tiingo",
                url=str(article.get("url") or "").strip(),
                title=clean_text(str(article.get("title") or ""), 500),
                summary=clean_text(str(article.get("description") or "")),
                published_at=parse_time(raw),
                published_raw=raw,
                provider_tickers=tuple(
                    str(t).upper() for t in article.get("tickers") or [] if str(t).strip()
                ),
                extra={
                    "id": article.get("id"),
                    "source": article.get("source") or "",
                    "crawled_at": article.get("crawlDate") or "",
                    "tags": list(article.get("tags") or []),
                },
            )
        )
    return [i for i in items if i.url and i.title]
