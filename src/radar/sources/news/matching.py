"""Which US-listed companies a news item is about, from the SEC ticker registry.

Precision over recall; nothing is guessed:

1. explicit exchange tickers in the text ("(NASDAQ: XYZ)", "NYSE: XYZ",
   "NYSE symbol-XYZ") that exist in the SEC registry;
2. tickers the provider attached (Tiingo), again only if the registry knows them;
3. exact company names: a run of capitalized words followed by a corporate suffix
   ("Matador Resources Company", "Matson, Inc.") whose core, once the suffix is
   dropped, equals the core of exactly one registrant's name.

A name shared by several registrants, a bare word without a suffix ("Apple said...")
and an exchange that is not a US market ("TSX: ABC") never produce a match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar.backtest.datasets import normalize_symbol

from ..registry import Registry

EXCHANGE = "exchange"
PROVIDER = "provider"
NAME = "name"
FILING = "filing"  # the filer itself (SEC exhibits): no matching at all

_US_EXCHANGES = (
    r"NYSE\s+American|NYSE\s+Arca|NYSE\s+MKT|NYSE|"
    r"Nasdaq\s+Global\s+Select(?:\s+Market)?|Nasdaq\s+Global(?:\s+Market)?|"
    r"Nasdaq\s+Capital(?:\s+Market)?|NASDAQ\s*(?:GS|GM|CM)|Nasdaq\s*(?:GS|GM|CM)|NASDAQ|Nasdaq|"
    r"Cboe\s+BZX|CBOE|AMEX|OTCQX|OTCQB|OTC\s+Pink|OTC\s+Markets|OTC"
)
_EXPLICIT = re.compile(
    rf"(?<![\w-])({_US_EXCHANGES})\s*(?:symbol\s*)?[:\-–]\s*[\"“]?"
    r"([A-Z]{1,5}(?:[.\-/][A-Z]{1,2})?)(?![\w])"
)

_SUFFIX = re.compile(
    r",?\s+(Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|Ltd\.?|Limited|plc|PLC|"
    r"N\.V\.|S\.A\.|L\.P\.|SE|AG)(?=$|[\s,;:)\"'’”.])"
)
_SUFFIX_WORDS = frozenset(
    "inc incorporated corp corporation co company ltd limited plc llc lp l p nv n v sa s a "
    "se ag the".split()
)
_CONNECTORS = frozenset({"&", "and", "of", "the", "de", "for"})
# Capitalized words that end a headline phrase rather than start a company name. A
# shorter name inside a run of capitalized words is only accepted right after one of
# these, so "National Capital Bancorp, Inc." never becomes "Capital Bancorp Inc".
_BOUNDARY = frozenset(
    """
    a about acquire acquires acquired acquisition across action after against agreement
    alert alerts all an and announce announced announces announcement as at backed
    before between buy by class closes completes congratulates deadline did divests
    for from has have holders in investigation investing investor investors into
    invests is joins launch launches lawsuit loss losses lose merge merger money names
    news newswire notice of on over partner partners partnership prnewswire purchase
    regarding reminder reports sell sells selects shareholder shareholders signs
    stockholder stockholders than the to today update urges versus via vs welcomes
    wire with
    """.split()
)
_TOKEN_SPLIT = re.compile(r"[\s()\[\]\"“”]+|--|—")
_STATE_TAG = re.compile(r"\s*/[a-z]{2,3}/?\s*$")
_NOT_WORD = re.compile(r"[^a-z0-9&]+")
MAX_NAME_WORDS = 7


@dataclass(frozen=True)
class Match:
    ticker: str
    cik: str
    name: str
    method: str  # exchange | provider | name | filing
    exchange: str = ""

    def view(self) -> dict[str, str]:
        out = {"ticker": self.ticker, "cik": self.cik, "name": self.name, "method": self.method}
        if self.exchange:
            out["exchange"] = self.exchange
        return out


def name_core(name: str) -> str:
    """'Matador Resources Co' and 'Matador Resources Company' → 'matador resources'."""
    text = _STATE_TAG.sub("", (name or "").lower())
    text = text.replace("&", " & ").replace("’", "'").replace("'s ", "s ")
    words = [w for w in _NOT_WORD.split(text) if w]
    while words and words[-1] in _SUFFIX_WORDS:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


class CompanyIndex:
    """Ticker and exact-name lookups over the SEC registry (`company_tickers.json`)."""

    def __init__(self, registry: Registry):
        self.registry = registry
        self._by_core: dict[str, set[str]] = {}
        self._name: dict[str, str] = {}
        for cik, _ticker, title in registry.by_ticker.values():
            self._name.setdefault(cik, title)
            core = name_core(title)
            if len(core) >= 3:
                self._by_core.setdefault(core, set()).add(cik)

    def __len__(self) -> int:
        return len(self.registry.by_ticker)

    def ticker(self, symbol: str) -> tuple[str, str, str] | None:
        """(cik, ticker, name) of a listed symbol, or None."""
        return self.registry.registrant(symbol)

    def by_name(self, core: str) -> str | None:
        """CIK of the only registrant whose name core is `core`."""
        ciks = self._by_core.get(core)
        return next(iter(ciks)) if ciks and len(ciks) == 1 else None

    def name_of(self, cik: str) -> str:
        return self._name.get(cik, "")

    def ticker_of(self, cik: str) -> str:
        return self.registry.ticker_for(cik)


def explicit_tickers(text: str) -> list[tuple[str, str]]:
    """(exchange, symbol) pairs written in the text, in order of appearance."""
    out: list[tuple[str, str]] = []
    for match in _EXPLICIT.finditer(text or ""):
        exchange = re.sub(r"\s+", " ", match.group(1))
        pair = (exchange, normalize_symbol(match.group(2).replace("/", ".")))
        if pair[1] and pair not in out:
            out.append(pair)
    return out


def name_candidates(text: str) -> list[list[str]]:
    """Runs of capitalized words that end right before a corporate suffix."""
    out: list[list[str]] = []
    for match in _SUFFIX.finditer(text or ""):
        before = [t for t in _TOKEN_SPLIT.split(text[: match.start()]) if t]
        run: list[str] = []
        for token in reversed(before):
            if len(run) >= MAX_NAME_WORDS:
                break
            word = token.strip(",;:")
            if token != word and run:  # a comma or colon ends the name (", Inc." is handled)
                break
            if word and (word[0].isupper() or word[0].isdigit()):
                run.insert(0, word)
            elif word.lower() in _CONNECTORS and run:
                run.insert(0, word)
            else:
                break
        while run and run[0].lower() in _CONNECTORS:
            run.pop(0)
        if run:
            out.append(run)
    return out


def match_companies(
    index: CompanyIndex,
    title: str,
    summary: str = "",
    provider_tickers: tuple[str, ...] = (),
) -> list[Match]:
    """Companies the item names, explicit tickers first; never more than one per CIK."""
    text = f"{title}\n{summary}"
    found: dict[str, Match] = {}

    for exchange, symbol in explicit_tickers(text):
        who = index.ticker(symbol)
        if who and who[0] not in found:
            cik, ticker, name = who
            found[cik] = Match(ticker, cik, name, EXCHANGE, exchange)

    for symbol in provider_tickers:
        who = index.ticker(symbol)
        if who and who[0] not in found:
            cik, ticker, name = who
            found[cik] = Match(ticker, cik, name, PROVIDER)

    for run in name_candidates(text):
        # Longest first: "Matador Resources" before "Resources"; a shorter name only
        # right after a word that cannot be part of it ("... Against Build-A-Bear").
        for start in range(len(run)):
            if run[start].lower() in _CONNECTORS:
                continue
            if start > 0 and run[start - 1].lower().strip(".'’") not in _BOUNDARY:
                continue
            core = name_core(" ".join(run[start:]))
            if len(core) < 3:
                continue
            cik = index.by_name(core)
            if cik is None:
                continue
            ticker = index.ticker_of(cik)
            if ticker and cik not in found:
                found[cik] = Match(ticker, cik, index.name_of(cik), NAME)
            break
    return list(found.values())
