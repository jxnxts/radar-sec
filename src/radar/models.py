"""Data structures shared by collection, parsers, signals and the backtest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, NamedTuple

FORM4_TYPES = frozenset({"4", "4/A"})
SC13D_ORIGINAL_TYPES = frozenset({"SC 13D", "SCHEDULE 13D"})
SC13D_AMENDMENT_TYPES = frozenset({"SC 13D/A", "SCHEDULE 13D/A"})
SC13D_TYPES = SC13D_ORIGINAL_TYPES | SC13D_AMENDMENT_TYPES


@dataclass(frozen=True)
class FilingRef:
    """A filing seen in the EDGAR feed (one row per accession number)."""

    accession: str
    form: str
    cik: str  # issuer/target CIK when the feed provides it; otherwise the filer's
    company: str
    filed_date: date
    url: str  # filing index page
    accepted_at: datetime | None = None
    filers: tuple[str, ...] = ()

    @property
    def txt_url(self) -> str:
        """URL of the complete submission file (.txt), which carries every document."""
        suffix = "-index.htm"
        base = self.url[: -len(suffix)] if self.url.endswith(suffix) else self.url
        return base + ".txt"


@dataclass(frozen=True)
class Owner:
    cik: str
    name: str
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str = ""

    @property
    def roles(self) -> list[str]:
        out = []
        if self.is_director:
            out.append("Director")
        if self.is_officer:
            out.append(self.officer_title or "Officer")
        if self.is_ten_percent_owner:
            out.append("10% owner")
        if self.is_other and not out:
            out.append("Other")
        return out


@dataclass(frozen=True)
class Transaction:
    """Non-derivative transaction (Form 4 Table I)."""

    security_title: str
    date: date | None
    code: str  # P = open-market buy, S = sale, A = grant, M = exercise, F = tax...
    shares: float | None
    price: float | None
    acquired_disposed: str  # A (acquired) or D (disposed)
    shares_after: float | None = None
    ownership: str = ""  # D (direct) or I (indirect)

    @property
    def value(self) -> float:
        if not self.shares or not self.price:
            return 0.0
        return self.shares * self.price

    @property
    def is_open_market_buy(self) -> bool:
        return self.code == "P" and self.acquired_disposed != "D" and self.value > 0


@dataclass(frozen=True)
class Form4:
    document_type: str
    issuer_cik: str
    issuer_name: str
    issuer_ticker: str
    period_of_report: date | None
    owners: tuple[Owner, ...]
    transactions: tuple[Transaction, ...]
    remarks: str = ""
    footnotes: tuple[str, ...] = ()

    @property
    def is_amendment(self) -> bool:
        return self.document_type.endswith("/A")

    @property
    def purchases(self) -> list[Transaction]:
        return [t for t in self.transactions if t.is_open_market_buy]


@dataclass(frozen=True)
class Reporter:
    name: str
    cik: str = ""
    shares: float | None = None
    percent: float | None = None


@dataclass(frozen=True)
class Schedule13D:
    form: str
    issuer_name: str
    issuer_cik: str
    reporters: tuple[Reporter, ...]
    source_format: str  # "xml" (Dec 2024 onward) or "legacy" (HTML/text)
    cusip: str = ""
    security_title: str = ""
    event_date: date | None = None
    purpose: str = ""  # Item 4 (purpose of the transaction), when available

    @property
    def is_amendment(self) -> bool:
        return self.form in SC13D_AMENDMENT_TYPES

    @property
    def max_percent(self) -> float | None:
        """Largest reported stake.

        In joint filings several people of the same group usually report the same
        shares, so we take the maximum, not the sum.
        """
        values = [r.percent for r in self.reporters if r.percent is not None]
        return max(values) if values else None


class Purchase(NamedTuple):
    """An open-market purchase (code P) reported in a Form 4."""

    date: date
    shares: float
    price: float
    shares_after: float | None = None  # position reported right after this purchase

    @property
    def value(self) -> float:
        return self.shares * self.price


@dataclass(frozen=True)
class PurchaseFiling:
    """A Form 4 with P purchases, in the normalized shape the signal rules consume.

    Both `watch` (from SQLite) and the backtest (from the historical datasets)
    convert their data to this structure, so the same rule functions apply in
    both places.
    """

    accession: str
    issuer_cik: str
    issuer_name: str
    ticker: str
    filing_date: date  # when the information became public
    owner_ciks: frozenset[str]
    owner_names: tuple[str, ...]
    is_ceo: bool
    is_cfo: bool
    is_officer_or_director: bool
    officer_title: str
    purchases: tuple[Purchase, ...]
    # largest position reported after the purchases (to measure the stake increase)
    shares_after: float | None = None

    @property
    def value(self) -> float:
        return sum(p.value for p in self.purchases)

    @property
    def shares(self) -> float:
        return sum(p.shares for p in self.purchases)

    @property
    def avg_price(self) -> float:
        return self.value / self.shares if self.shares else 0.0


@dataclass
class Signal:
    type: str
    dedupe_key: str
    issuer_cik: str
    issuer_name: str
    ticker: str
    signal_date: date
    score: float
    explanation: str  # English; other languages are rendered by `signals.explain`
    trigger_accession: str
    details: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    summary_source: str = ""  # "ai" or "template"
    id: int | None = None
    created_at: datetime | None = None  # when the radar stored the signal (UTC)
