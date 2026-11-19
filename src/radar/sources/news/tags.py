"""Deterministic topic tags for a news item, from keyword rules over title and summary.

No scoring and no model here: a tag only says the text talks about the topic. An LLM
score can be added later through `scoring.NewsScorer` without touching these rules.
"""

from __future__ import annotations

import re

EARNINGS = "earnings"
GUIDANCE = "guidance"
MNA = "mna"
OFFERING = "offering"
BUYBACK = "buyback"
FDA = "fda"
LAWSUIT = "lawsuit"
EXEC_CHANGE = "exec_change"
DIVIDEND = "dividend"

_I = re.IGNORECASE
_ROLE = (
    r"(?:CEO|CFO|COO|CTO|Chief [A-Z][a-z]+(?: [A-Z][a-z]+)? Officer|President|"
    r"Chair(?:man|woman|person)?)"
)

RULES: dict[str, list[re.Pattern[str]]] = {
    EARNINGS: [
        re.compile(r"\bearnings\b", _I),
        re.compile(
            r"\b(?:first|second|third|fourth|1st|2nd|3rd|4th|september|june|march|december)"
            r"[- ]quarter\b[^.]{0,80}\bresults\b",
            _I,
        ),
        re.compile(
            r"\b(?:quarterly|fiscal|full[- ]year|annual|interim|preliminary)\b"
            r"(?: \w+){0,3} (?:financial |operating )?results\b",
            _I,
        ),
        re.compile(r"\bQ[1-4](?: (?:FY)?\d{2,4})? (?:financial |operating )?results\b"),
    ],
    GUIDANCE: [
        re.compile(
            r"\b(?:raises|raised|lowers|lowered|cuts|reaffirms|reaffirmed|reiterates|updates|"
            r"updated|initiates|issues|provides|withdraws|narrows|increases|maintains)\b"
            r"(?: \S+){0,6}? (?:guidance|outlook|forecast)\b",
            _I,
        ),
        re.compile(r"\b(?:guidance|outlook)\b[^.]{0,30}\b(?:raised|lowered|reaffirmed|cut)\b", _I),
    ],
    MNA: [
        re.compile(
            r"\b(?:to acquire|acquires|acquired by|acquisition of|to be acquired|merger|"
            r"to merge|merge with|definitive agreement|take-private|takeover|tender offer|"
            r"business combination|buyout)\b",
            _I,
        ),
    ],
    OFFERING: [
        re.compile(
            r"\b(?:public|private|secondary|follow-on|registered direct|notes|debt|equity|"
            r"stock|share|unit|convertible|underwritten|proposed|upsized|senior notes)"
            r" offerings?\b",
            _I,
        ),
        re.compile(r"\b(?:private placement|at-the-market|pricing of)\b", _I),
    ],
    BUYBACK: [
        re.compile(
            r"\b(?:share|stock|equity) (?:repurchase|buyback)s?\b|\bbuy-?backs?\b|"
            r"\brepurchase (?:program|authorization|plan)\b",
            _I,
        ),
    ],
    FDA: [
        re.compile(r"\bFDA\b|\bPDUFA\b|\b(?:s?NDA|BLA|510\(k\))\b"),
        re.compile(
            r"\bFood and Drug Administration\b|\bbreakthrough therapy\b|"
            r"\bfast track designation\b|\borphan drug designation\b",
            _I,
        ),
    ],
    LAWSUIT: [
        re.compile(
            r"\b(?:class action|lawsuit|securities fraud|sued|subpoena|"
            r"shareholder rights law firm|investors? (?:alert|deadline|notice))\b",
            _I,
        ),
        re.compile(r"\b(?:investigation|investigates|investigating) (?:of|on behalf)\b", _I),
    ],
    EXEC_CHANGE: [
        re.compile(
            r"\b(?:appoints|appointed|appointment of|names|named|promotes|hires|elects|"
            r"resigns|resigned|resignation|steps down|to step down|stepping down|retires|"
            r"retirement|departure|successor|to succeed|transition)\b[^\n]{0,80}?\b"
            + _ROLE
            + r"\b",
            _I,
        ),
        re.compile(
            r"\b" + _ROLE + r"\b[^.]{0,60}\b(?:resigns|to step down|steps down|departs|"
            r"retires|to retire|transition)\b",
            _I,
        ),
    ],
    DIVIDEND: [
        re.compile(
            r"\b(?:declares|declared|announces|increases|raises)\b[^.]{0,40}\bdividends?\b", _I
        ),
        re.compile(r"\b(?:quarterly|monthly|special|annual) (?:cash )?dividend\b", _I),
    ],
}
TAGS: tuple[str, ...] = tuple(RULES)


def tag(title: str, summary: str = "") -> list[str]:
    """Tags the title or the summary support, in the fixed order of `TAGS`."""
    text = f"{title}\n{summary}"
    return [name for name, patterns in RULES.items() if any(p.search(text) for p in patterns)]
