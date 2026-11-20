"""Official press releases: the EX-99 exhibits of the 8-Ks the live 8-K source sees.

Companies attach the press release of an earnings report, a deal or an executive
change to their 8-K as exhibit 99.x. The exhibit is on EDGAR within seconds of the
filing's acceptance, from a free source, and the company is the filer: ticker and CIK
come from the filing, no name matching is needed.

Each exhibit becomes a news item of feed `sec-8k-ex99`: `published_at` is the SEC
acceptance time, `seen_at` the moment the radar fetched it, the title is the first
headline line, the summary plain text. The rest flows like any other news item (store,
tape, company context, forward log).

Where the documents come from, in order of cost:

1. the complete submission (`.txt`) when the 8-K rules already downloaded it (items
   1.01, 2.02, 5.02, 7.01, 8.01): no extra request;
2. otherwise, for 8-Ks that list Item 9.01 (exhibits), the filing index page and then
   each EX-99 document: a few requests, cached forever (filings never change), through
   the shared SEC limiter, at most `sec_exhibits_filings_per_poll` filings per poll.
"""

from __future__ import annotations

import html
import logging
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from radar.http import SecHttpError, decode

from ..base import PollResult
from .matching import FILING, Match
from .model import NewsItem, clean_text

log = logging.getLogger(__name__)

FEED = "sec-8k-ex99"
EVENT_KIND = "press_release"
SEC = "https://www.sec.gov"
TITLE_MAX = 300
PENDING_MAX = 500

_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_HREF = re.compile(r'href="([^"]+)"', re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_DOCUMENT = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S | re.I)
_SGML_FIELD = re.compile(r"<(TYPE|SEQUENCE|FILENAME|DESCRIPTION)>([^\n<]*)", re.I)
_TEXT = re.compile(r"<TEXT>(.*?)(?:</TEXT>|\Z)", re.S | re.I)
_DROP = re.compile(r"<(script|style|head|title)\b.*?</\1\s*>", re.S | re.I)
_BLOCK = re.compile(
    r"<\s*/?\s*(?:p|div|br|tr|table|h[1-6]|li|ul|ol|center|hr|section|article)\b[^>]*>", re.I
)
_EX99 = re.compile(r"^EX-99(?:\.\d+)?\b", re.I)

# Lines that frame a press release but are not its headline.
_BOILERPLATE = re.compile(
    r"^(?:exhibit\s*(?:no\.?\s*)?99(?:\.\d+)?|ex-99(?:\.\d+)?|"
    r"(?:\w+\s+)?(?:press|news|media|earnings)\s+release\b.*|for\s+immediate\s+release\b.*|"
    r"investor\s+(?:relations|contacts?)\b.*|media\s+contacts?\b.*|execution\s+(?:version|copy)|"
    r"page\s+\d+.*|[\d\s]+|.*:|"
    r"(?:nasdaq|nyse)(?:\s+american)?\s*:\s*[A-Z.]{1,6}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})$",
    re.I,
)
# Contact blocks: e-mails, phone numbers, web addresses.
_CONTACT = re.compile(
    r"@|\bwww\.|https?://|\(\d{3}\)\s*\d{3}[\s.\-]\d{4}|\b\d{3}[.\-]\d{3}[.\-]\d{4}\b"
)
_LEAD = re.compile(
    r"^(?:\d{1,3}\s+)?(?:(?:exhibit\s*(?:no\.?\s*)?99(?:\.\d+)?|ex-99(?:\.\d+)?|"
    r"for\s+immediate\s+release|(?:press|news)\s+release)[\s:.\-–—]*)+",
    re.I,
)
# Words that make a line read like a headline ("ACME Announces...", "... Reports Results").
_HEADLINE_WORD = re.compile(
    r"\b(?:announc\w*|reports?|reported|declares?|declared|appoints?|appointed|names?|named|"
    r"complet\w*|provides?|acquir\w*|acquisition|sells?|signs?|launch\w*|increases?|raises?|"
    r"receiv\w*|enters?|closes?|closing|prices?|pricing|approv\w*|adds?|elects?|expands?|"
    r"issues?|updates?|reaffirms?|hosts?|schedules?|achiev\w*|wins?|awarded|results|"
    r"dividends?|earnings|merger|agreement|offering|transition|retire\w*|resign\w*|"
    r"partners?\w*|unveils?|introduces?|delivers?|secures?|strengthens?|extends?)\b",
    re.I,
)
# A headline that ends on one of these goes on in the next block ("... and Eagle Announce"
# / "Receipt of Shareholder Approvals").
_UNFINISHED = re.compile(
    r"\b(?:and|of|to|for|the|with|on|in|a|an|at|by|from|announce|announces|report|reports)$",
    re.I,
)
_DATELINE = re.compile(r"\s(?:[A-Z][A-Z.'\-]+(?:\s+[A-Z][A-Z.'\-]+){0,3}),\s")
_NAME_SKIP = frozenset({"the", "inc", "corp", "co", "ltd", "plc", "group", "holdings", "company"})


@dataclass(frozen=True)
class Exhibit:
    """One EX-99 document of a filing."""

    type: str  # "EX-99.1"
    filename: str
    url: str
    description: str = ""
    size: int | None = None


@dataclass(frozen=True)
class FilingInfo:
    """What the press-release collector needs from an 8-K the feed listed."""

    accession: str
    form: str
    cik: str
    name: str
    ticker: str
    index_url: str
    accepted_at: datetime | None
    items: tuple[str, ...] = ()

    @property
    def folder(self) -> str:
        return self.index_url.rsplit("/", 1)[0] + "/"


def _cell_text(cell: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", cell))).replace("\xa0", " ").strip()


def parse_index(page: str) -> list[Exhibit]:
    """EX-99 documents listed on a filing index page (`...-index.htm`), in order."""
    out: list[Exhibit] = []
    for row in _ROW.findall(page):
        cells = _CELL.findall(row)
        if len(cells) < 4:
            continue
        kind = _cell_text(cells[3]).upper()
        if not _EX99.match(kind):
            continue
        link = _HREF.search(cells[2])
        if not link:
            continue
        href = link.group(1).replace("/ix?doc=", "")
        url = href if href.startswith("http") else SEC + href
        size_text = _cell_text(cells[4]) if len(cells) > 4 else ""
        out.append(
            Exhibit(
                type=kind,
                filename=url.rsplit("/", 1)[-1],
                url=url,
                description=_cell_text(cells[1]),
                size=int(size_text) if size_text.isdigit() else None,
            )
        )
    return out


def _sgml_fields(block: str) -> dict[str, str]:
    head = block.split("<TEXT>", 1)[0] if "<TEXT>" in block else block[:2000]
    return {k.upper(): v.strip() for k, v in _SGML_FIELD.findall(head)}


def document_body(raw: str) -> str:
    """The `<TEXT>` of a document, without the SGML wrapper EDGAR may serve around it."""
    match = _TEXT.search(raw)
    return match.group(1) if match else raw


def submission_exhibits(raw: str, folder: str) -> list[tuple[Exhibit, str]]:
    """EX-99 documents of a complete submission (`.txt`), with their bodies."""
    out: list[tuple[Exhibit, str]] = []
    for block in _DOCUMENT.findall(raw):
        fields = _sgml_fields(block)
        kind = fields.get("TYPE", "").upper()
        if not _EX99.match(kind):
            continue
        filename = fields.get("FILENAME", "")
        body = document_body(block)
        exhibit = Exhibit(
            type=kind,
            filename=filename,
            url=folder + filename if filename else folder,
            description=fields.get("DESCRIPTION", ""),
            size=len(body),
        )
        out.append((exhibit, body))
    return out


def text_lines(document: str) -> list[str]:
    """Plain-text lines of an HTML (or plain-text) exhibit, one per block element."""
    raw = document_body(document)
    if not re.search(r"<(?:html|body|p|div|table|font|b)\b", raw, re.I):
        lines = [_SPACE.sub(" ", line).strip() for line in html.unescape(raw).splitlines()]
        return [line for line in lines if line]
    raw = _DROP.sub(" ", raw)
    raw = _SPACE.sub(" ", raw)  # newlines inside a paragraph are only spaces
    raw = _BLOCK.sub("\n", raw)
    text = html.unescape(_TAG.sub(" ", raw)).replace("\xa0", " ").replace("​", "")
    lines = [_SPACE.sub(" ", line).strip() for line in text.split("\n")]
    return [line for line in lines if line and not re.fullmatch(r"[\W_]+", line)]


def _cut_dateline(line: str) -> str:
    """A headline glued to the body ("... Notes CHANDLER, Ariz.-- ...") loses the body."""
    match = _DATELINE.search(line)
    if match and match.start() >= 15:
        return line[: match.start()].strip()
    return line


def _company_word(name: str) -> re.Pattern[str] | None:
    """The first distinctive word of the filer's name ("Ames National Corp" → ames)."""
    for word in re.split(r"[^a-z0-9]+", name.lower().replace("’", "'").replace("'s", "")):
        if len(word) >= 3 and word not in _NAME_SKIP:
            return re.compile(rf"\b{re.escape(word)}", re.I)
    return None


def _candidate(line: str) -> str:
    text = _LEAD.sub("", line).strip()
    if len(text) < 12 or _BOILERPLATE.match(text) or _CONTACT.search(text):
        return ""
    if sum(c.isalpha() for c in text) < 8:
        return ""
    return text


def headline(lines: list[str], company: str = "") -> tuple[str, int]:
    """The headline of a release (and the index of its first body line), or ("", 0).

    Among the first lines that are not framing (exhibit number, "For immediate release",
    contacts, dates), the first that reads like a headline (a verb such as "announces"
    or the company's name) wins; failing that, the first such line.
    """
    candidates = [(i, c) for i, line in enumerate(lines[:40]) if (c := _candidate(line))][:12]
    if not candidates:
        return "", 0
    name = _company_word(company)
    chosen = next(
        (
            (i, c)
            for i, c in candidates
            if _HEADLINE_WORD.search(c) or (name is not None and name.search(c))
        ),
        candidates[0],
    )
    i, text = chosen
    nxt = i + 1
    # A headline broken over two blocks ("... Upon Closing" / "of Business ...").
    while (
        nxt < len(lines)
        and len(text) < TITLE_MAX
        and (lines[nxt][:1].islower() or _UNFINISHED.search(text))
        and not _CONTACT.search(lines[nxt])
    ):
        text = f"{text} {lines[nxt]}"
        nxt += 1
    if len(text) > 200:
        text = _cut_dateline(text)
    return clean_text(text, TITLE_MAX), nxt


def exhibit_item(
    filing: FilingInfo, exhibit: Exhibit, document: str, *, summary_max: int = 1000
) -> NewsItem:
    """A news item from one EX-99 document."""
    lines = text_lines(document)
    title, start = headline(lines, filing.name)
    if not title:
        what = exhibit.description if exhibit.description.upper() != exhibit.type else ""
        title = f"{filing.name}: {what or exhibit.type}"
    accepted = filing.accepted_at.astimezone(UTC) if filing.accepted_at else None
    return NewsItem(
        feed=FEED,
        url=exhibit.url,
        title=title,
        summary=clean_text(" ".join(lines[start:]), summary_max),
        published_at=accepted,
        published_raw=filing.accepted_at.isoformat() if filing.accepted_at else "",
        provider_tickers=(filing.ticker,) if filing.ticker else (),
        extra={
            "accession": filing.accession,
            "form": filing.form,
            "exhibit": exhibit.type,
            "description": exhibit.description,
            "cik": filing.cik,
            "company": filing.name,
            "items": list(filing.items),
            "filing_url": filing.index_url,
        },
    )


def filing_match(filing: FilingInfo) -> list[Match]:
    """The filer is the company: no matching, only its listed ticker."""
    return [Match(filing.ticker, filing.cik, filing.name, FILING)] if filing.ticker else []


class PressReleaseCollector:
    """Turns the EX-99 exhibits of new 8-Ks into news items (used by the 8-K source)."""

    def __init__(
        self,
        *,
        per_filing: int = 3,
        filings_per_poll: int = 40,
        max_bytes: int = 2_000_000,
        summary_max: int = 1000,
        now=lambda: datetime.now(UTC),
    ):
        self.per_filing = max(1, per_filing)
        self.filings_per_poll = max(0, filings_per_poll)
        self.max_bytes = max_bytes
        self.summary_max = summary_max
        self._now = now
        # Filings whose index is still to be read (more than one poll's share).
        self._pending: deque[FilingInfo] = deque(maxlen=PENDING_MAX)
        self.filings_seen = 0
        self.stored = 0
        self.requests = 0
        self.dropped = 0

    def pending(self) -> int:
        return len(self._pending)

    def wants_index(self, filing: FilingInfo) -> bool:
        """Only 8-Ks that list Item 9.01 (financial statements and exhibits) carry EX-99s;
        when the feed gave no items at all, look anyway."""
        return filing.form.startswith("8-K") and ("9.01" in filing.items or not filing.items)

    def collect(
        self,
        ctx,
        result: PollResult,
        *,
        from_text: Iterable[tuple[FilingInfo, str]] = (),
        need_index: Iterable[FilingInfo] = (),
    ) -> None:
        """Store the press releases of these filings and add them to `result`.

        `from_text`: filings whose complete submission was already downloaded;
        `need_index`: filings without it (their index is read, up to the per-poll cap).
        """
        from .live import store_item  # the news poller's storage path

        found: list[tuple[FilingInfo, Exhibit, str]] = []
        for filing, raw in from_text:
            self.filings_seen += 1
            exhibits = submission_exhibits(raw, filing.folder)[: self.per_filing]
            found += [(filing, ex, body) for ex, body in exhibits if len(body) <= self.max_bytes]

        queued = {f.accession for f in self._pending}
        for filing in need_index:
            self.filings_seen += 1
            if self.wants_index(filing) and filing.accession not in queued:
                if len(self._pending) == self._pending.maxlen:
                    self.dropped += 1
                self._pending.append(filing)
                queued.add(filing.accession)
        batch: list[FilingInfo] = []
        while self._pending and len(batch) < self.filings_per_poll:
            batch.append(self._pending.popleft())
        found += self._from_index(ctx, batch)

        seen_at = self._now()
        for filing, exhibit, body in found:
            item = exhibit_item(filing, exhibit, body, summary_max=self.summary_max)
            if store_item(
                ctx,
                item,
                seen_at,
                result,
                matches=filing_match(filing),
                event_kind=EVENT_KIND,
                dedupe_title=False,
                event_data={"accession": filing.accession, "exhibit": exhibit.type},
            ):
                self.stored += 1

    def _from_index(self, ctx, batch: list[FilingInfo]) -> list[tuple[FilingInfo, Exhibit, str]]:
        if not batch:
            return []
        client = ctx.client
        before = client.requests_made
        pages = client.fetch_many((f.index_url for f in batch), retries=1)
        wanted: list[tuple[FilingInfo, Exhibit]] = []
        for filing in batch:
            page = pages.get(filing.index_url)
            if page is None or isinstance(page, SecHttpError):
                log.info("8-K index %s unavailable: %s", filing.accession, page)
                continue
            exhibits = [
                e for e in parse_index(decode(page)) if e.size is None or e.size <= self.max_bytes
            ]
            wanted += [(filing, e) for e in exhibits[: self.per_filing]]
        docs = client.fetch_many((e.url for _, e in wanted), retries=1)
        self.requests += client.requests_made - before
        out = []
        for filing, exhibit in wanted:
            body = docs.get(exhibit.url)
            if body is None or isinstance(body, SecHttpError):
                log.info("exhibit %s unavailable: %s", exhibit.url, body)
                continue
            out.append((filing, exhibit, decode(body)))
        return out

    def health(self) -> dict[str, Any]:
        return {
            "feed": FEED,
            "filings_seen": self.filings_seen,
            "stored": self.stored,
            "requests": self.requests,
            "pending": len(self._pending),
            "dropped": self.dropped,
        }
