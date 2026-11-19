"""10-K text change ("Lazy Prices", Cohen, Malloy & Nguyen 2020).

Each 10-K is reduced to word counts (numbers and one-letter tokens dropped) and compared with
the same company's previous 10-K. Low similarity = the company changed its disclosure a lot.
"""

from __future__ import annotations

import math
import re
from collections import Counter

import lxml.html
import numpy as np
import pandas as pd

_TOKEN = re.compile(r"[a-z][a-z'\-]*[a-z]")
_ITEM_1A = re.compile(r"item\s*1a\s*[\.\-–—:]?\s*risk\s+factors", re.I)
_ITEM_1A_END = re.compile(
    r"item\s*1b\s*[\.\-–—:]?\s*unresolved|item\s*1c\s*[\.\-–—:]?\s*cybersecurity"
    r"|item\s*2\s*[\.\-–—:]?\s*properties",
    re.I,
)
MIN_SECTION_WORDS = 500
PREVIOUS_GAP_DAYS = (300, 450)  # the previous 10-K must be roughly a year older
ROLLING_DAYS = 365
MIN_REFERENCE = 200


def html_to_text(raw: bytes) -> str:
    if not raw.strip():
        return ""
    try:
        doc = lxml.html.fromstring(raw)
    except (ValueError, lxml.etree.ParserError):
        return re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore"))
    # Scripts and styles are not text. The hidden inline-XBRL block (<ix:header>) is kept: the
    # HTML parser does not see its namespace, and its content is mostly numbers and XBRL names,
    # which the tokenizer drops or which repeat every year (stated in the phase-2 report).
    for node in doc.xpath("//script|//style|//*[local-name()='header']"):
        node.drop_tree()
    return re.sub(r"\s+", " ", doc.text_content().replace("\xa0", " "))


def tokens(text: str) -> Counter:
    return Counter(_TOKEN.findall(text.lower()))


def risk_factors(text: str) -> str:
    """The longest "Item 1A. Risk Factors" section (the table of contents entry is short)."""
    best = ""
    for match in _ITEM_1A.finditer(text):
        end = _ITEM_1A_END.search(text, match.end())
        if end and end.start() - match.end() > len(best):
            best = text[match.end() : end.start()]
    return best if len(best.split()) >= MIN_SECTION_WORDS else ""


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return float("nan")
    small, big = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(count * big.get(word, 0) for word, count in small.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b)


def jaccard(a: Counter, b: Counter) -> float:
    if not a or not b:
        return float("nan")
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def rolling_quintiles(filing_dates: pd.Series, similarity: pd.Series) -> np.ndarray:
    """Quintile (1 = most change ... 5 = least change) of each filing against every filing of the
    previous 365 days, strictly earlier, so the breakpoints are known on the filing date."""
    order = np.argsort(pd.to_datetime(filing_dates).to_numpy(), kind="stable")
    dates = pd.to_datetime(filing_dates).to_numpy()[order]
    values = similarity.to_numpy(dtype=float)[order]
    out = np.full(len(values), np.nan)
    for i in range(len(values)):
        lo = np.searchsorted(dates, dates[i] - np.timedelta64(ROLLING_DAYS, "D"))
        hi = np.searchsorted(dates, dates[i])
        reference = values[lo:hi]
        reference = reference[~np.isnan(reference)]
        if len(reference) >= MIN_REFERENCE and not np.isnan(values[i]):
            out[i] = 1 + min(4, int(5 * (reference < values[i]).mean()))
    result = np.full(len(values), np.nan)
    result[order] = out
    return result
