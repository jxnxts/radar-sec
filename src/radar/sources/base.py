"""Common shapes for the extra market-signal sources.

Every source (Form 144, 13F, 8-K, short data) turns what it collects into
`MarketEvent`s (one row per thing that happened, shown on the panel tape and in
the company context) and, through the same rule functions in live mode and in
the backtest, into `Signal`s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from radar.models import Signal

# Source names. They are also the `source` column of `market_events`.
FORM144 = "form144"
THIRTEENF = "thirteenf"
EIGHTK = "eightk"
SHORT = "short"
SOURCES = (FORM144, THIRTEENF, EIGHTK, SHORT)

# Direction of a signal's hypothesis.
LONG = "long"  # expected to beat the index
AVOID = "avoid"  # expected to lag the index (a filter, never a short recommendation)
CONTEXT = "context"  # shown for context, not tested


@dataclass(frozen=True)
class MarketEvent:
    """Something a source saw, in a shape common to all sources.

    `key` is unique per source (accession number, "SYMBOL:settlement date"...).
    `event_date` is the day the information became public.
    """

    source: str
    kind: str  # e.g. "form144", "8k_item", "nt_filing", "13f_new_position", "short_interest"
    key: str
    event_date: date
    issuer_cik: str = ""
    issuer_name: str = ""
    ticker: str = ""
    title: str = ""  # one line for the tape
    data: dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    seen_at: datetime | None = None


@dataclass(frozen=True)
class SignalSpec:
    """Static description of a signal type (labels, direction, primary horizon)."""

    type: str
    source: str
    label: str
    direction: str
    primary_months: int | None
    rule: str


@dataclass
class PollResult:
    events: list[MarketEvent] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    requests: int = 0
    note: str = ""


class Source(Protocol):
    """Interface every source package implements for the live loop.

    `poll` fetches what is new (cached and rate-limited), normalizes it into
    `MarketEvent`s, stores the source's own rows and applies the signal rules — the
    same pure functions the backtest uses (each package's `history` module feeds them
    point-in-time data instead).
    """

    name: str
    interval_s: float

    def poll(self, ctx: Any) -> PollResult: ...


_CIK_IN_NAME = re.compile(r"\(CIK (\d{1,10})\)")
_TICKERS_IN_NAME = re.compile(r"\(([A-Z0-9.\-]+(?:,\s*[A-Z0-9.\-]+)*)\)\s+\(CIK")


def split_display_name(display: str) -> tuple[str, list[str], str]:
    """'RESMED INC  (RMD, RSMDF)  (CIK 0000943819)' → ('RESMED INC', ['RMD', 'RSMDF'], '943819')."""
    cik_match = _CIK_IN_NAME.search(display)
    cik = str(int(cik_match.group(1))) if cik_match else ""
    tick_match = _TICKERS_IN_NAME.search(display)
    tickers = [t.strip() for t in tick_match.group(1).split(",")] if tick_match else []
    name = display
    cut = display.find("(")
    if cut > 0:
        name = display[:cut]
    return name.strip(), tickers, cik


def cooldown_filter(signals: list[Signal], days: int) -> list[Signal]:
    """Keep the first signal per (type, issuer) and drop repeats within `days`."""
    last: dict[tuple[str, str], date] = {}
    kept: list[Signal] = []
    for signal in sorted(signals, key=lambda s: (s.signal_date, s.issuer_cik, s.dedupe_key)):
        key = (signal.type, signal.issuer_cik or signal.ticker)
        previous = last.get(key)
        if previous is not None and (signal.signal_date - previous).days < days:
            continue
        last[key] = signal.signal_date
        kept.append(signal)
    return kept
