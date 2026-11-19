"""8-K items and the fixed phrase lists used by the text rules.

The same phrases drive the live classifier (regex over the downloaded filing) and
the backtest (exact-phrase EDGAR full-text search), so both see the same events.
"""

from __future__ import annotations

import html
import re

ITEM_LABELS = {
    "1.01": "Material definitive agreement",
    "1.02": "Termination of a material agreement",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety",
    "1.05": "Cybersecurity incident",
    "2.01": "Completed acquisition or disposition",
    "2.02": "Results of operations (earnings)",
    "2.03": "New direct financial obligation",
    "2.04": "Triggering event (debt acceleration)",
    "2.05": "Exit or disposal costs",
    "2.06": "Material impairment",
    "3.01": "Delisting notice",
    "3.02": "Unregistered sale of equity",
    "3.03": "Change in shareholder rights",
    "4.01": "Change of auditor",
    "4.02": "Non-reliance on prior financials",
    "5.01": "Change in control",
    "5.02": "Officer or director change",
    "5.03": "Bylaws or fiscal year change",
    "5.07": "Shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits",
}

BUYBACK_PHRASES = (
    "authorized a share repurchase program",
    "approved a share repurchase program",
    "authorized a new share repurchase program",
    "approved a new share repurchase program",
    "authorized a stock repurchase program",
    "approved a stock repurchase program",
    "authorized a new stock repurchase program",
    "approved a new stock repurchase program",
    "new share repurchase program",
    "new stock repurchase program",
)

_EXIT_VERBS = (
    "resigned as",
    "resign as",
    "resignation as",
    "step down as",
    "stepping down as",
    "terminated as",
)
CEO = "chief executive officer"
CFO = "chief financial officer"
EXIT_PHRASES = tuple(f"{verb} {title}" for title in (CEO, CFO) for verb in _EXIT_VERBS)

MERGER_PHRASE = "agreement and plan of merger"

# Items whose text is worth downloading live (buyback news, executive exits, mergers).
TEXT_ITEMS = frozenset({"1.01", "2.02", "5.02", "7.01", "8.01"})

_ITEM_IN_SUMMARY = re.compile(r"Item\s+(\d\.\d{2})", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def items_from_summary(summary: str) -> tuple[str, ...]:
    """Items listed in the `getcurrent` feed summary ("Item 5.02: Departure of ...")."""
    found = dict.fromkeys(_ITEM_IN_SUMMARY.findall(html.unescape(summary or "")))
    return tuple(found)


# Distinctive words of each official item title, for the "ITEM INFORMATION:" header lines.
_ITEM_TITLES = (
    ("1.01", "entry into a material definitive agreement"),
    ("1.02", "termination of a material definitive agreement"),
    ("1.03", "bankruptcy or receivership"),
    ("1.04", "mine safety"),
    ("1.05", "cybersecurity incident"),
    ("2.01", "completion of acquisition or disposition"),
    ("2.02", "results of operations and financial condition"),
    ("2.03", "creation of a direct financial obligation"),
    ("2.04", "triggering events"),
    ("2.05", "costs associated with exit or disposal"),
    ("2.06", "material impairments"),
    ("3.01", "notice of delisting"),
    ("3.02", "unregistered sales of equity"),
    ("3.03", "material modification"),
    ("4.01", "certifying accountant"),
    ("4.02", "non-reliance on previously issued"),
    ("5.01", "changes in control of registrant"),
    ("5.02", "departure of directors or certain officers"),
    ("5.03", "amendments to articles of incorporation"),
    ("5.04", "temporary suspension of trading"),
    ("5.05", "code of ethics"),
    ("5.06", "shell company status"),
    ("5.07", "submission of matters to a vote"),
    ("5.08", "shareholder director nominations"),
    ("7.01", "regulation fd disclosure"),
    ("8.01", "other events"),
    ("9.01", "financial statements and exhibits"),
)


def items_from_header(submission_text: str) -> tuple[str, ...]:
    """Items from the SGML header of a submission.

    The `-index-headers` page lists codes (`<ITEMS>5.02`); the `.txt` lists the titles
    (`ITEM INFORMATION: Departure of Directors or Certain Officers; ...`).
    """
    header = submission_text.split("</SEC-HEADER>", 1)[0]
    found = re.findall(r"<ITEMS>\s*(\d\.\d{2})", header)
    for line in re.findall(r"ITEM INFORMATION:\s*(.+)", header):
        lowered = line.lower()
        found += [code for code, words in _ITEM_TITLES if words in lowered]
    return tuple(dict.fromkeys(found))


def plain_text(raw: str) -> str:
    """Filing text without tags or entities, lowercase, single-spaced."""
    # Binary exhibits (graphics, PDFs, XBRL zips) are uuencoded; they hold no phrases.
    raw = re.sub(r"<TYPE>(GRAPHIC|ZIP|PDF|EXCEL|XML)\b.*?</DOCUMENT>", " ", raw, flags=re.S | re.I)
    text = html.unescape(_TAG.sub(" ", raw))
    text = text.replace(" ", " ").replace("’", "'")
    return _SPACE.sub(" ", text).lower()


def find_phrases(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Phrases present in already-normalized text, in the order of the list."""
    return [p for p in phrases if p in text]


def exit_titles(matches: list[str]) -> list[str]:
    titles = []
    if any(CEO in m for m in matches):
        titles.append("CEO")
    if any(CFO in m for m in matches):
        titles.append("CFO")
    return titles


def quote_around(text: str, phrase: str, width: int = 160) -> str:
    """A short excerpt around the first occurrence of `phrase` (for the cards)."""
    index = text.find(phrase)
    if index < 0:
        return ""
    start = max(0, index - width // 2)
    end = min(len(text), index + len(phrase) + width)
    excerpt = text[start:end].strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")
