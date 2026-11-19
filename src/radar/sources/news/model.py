"""One news item, its point-in-time timestamps and its dedupe key.

`published_at` is what the feed states (it can be late, rounded or missing);
`seen_at` is when the radar fetched the item, in UTC. Backtests must use `seen_at`:
it is the earliest moment the radar could have acted on the item.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track the click; dropped from the canonical URL.
_TRACKING = re.compile(r"^(utm_\w+|feedref|cmpid|cmp|ref|src|source|mc_cid|mc_eid|fbclid|gclid)$")
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[^a-z0-9]+")

SUMMARY_MAX = 1000


@dataclass(frozen=True)
class NewsItem:
    """A news item as one feed delivered it, before matching."""

    feed: str  # "prnewswire", "businesswire", "gdelt", "tiingo"...
    url: str
    title: str
    summary: str = ""
    published_at: datetime | None = None
    published_raw: str = ""
    # Tickers the provider itself attached (Tiingo); still checked against the registry.
    provider_tickers: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_url(self) -> str:
        return canonical_url(self.url)

    @property
    def title_hash(self) -> str:
        return title_hash(self.title)

    @property
    def key(self) -> str:
        return dedupe_key(self.url, self.title)


def clean_text(value: str | None, limit: int = SUMMARY_MAX) -> str:
    """Plain text from an RSS field: HTML tags out, entities decoded, spaces collapsed."""
    text = html.unescape(_TAGS.sub(" ", value or ""))
    text = _SPACES.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def canonical_url(url: str) -> str:
    """https, lower-case host without "www.", no fragment, no tracking parameters."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k.lower())]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    return _NOT_WORD.sub(" ", clean_text(title).lower()).strip()


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode()).hexdigest()[:20]


def dedupe_key(url: str, title: str) -> str:
    """Hash of the canonical URL plus the normalized title."""
    raw = f"{canonical_url(url)}\n{normalize_title(title)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def parse_time(value: str | None) -> datetime | None:
    """A feed timestamp (RFC 822, ISO 8601 or GDELT's 20261119T214500Z) in UTC, or None."""
    text = (value or "").strip()
    if not text:
        return None
    parsed: datetime | None = None
    if re.fullmatch(r"\d{8}T\d{6}Z", text):
        parsed = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    else:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
