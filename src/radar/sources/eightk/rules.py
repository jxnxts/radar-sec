"""8-K and NT 10-K/10-Q signal rules (pure; shared by the live monitor and the backtest)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from radar.models import Signal

from ..base import AVOID, EIGHTK, LONG, SignalSpec, cooldown_filter
from .text import ITEM_LABELS

BUYBACK_8K = "buyback_8k"
CEO_CFO_EXIT_8K = "ceo_cfo_exit_8k"
BANKRUPTCY_8K = "bankruptcy_8k"
AUDITOR_CHANGE_8K = "auditor_change_8k"
LATE_FILING_NT = "late_filing_nt"

NT_FORMS = frozenset({"NT 10-K", "NT 10-Q"})

SPECS = {
    BUYBACK_8K: SignalSpec(
        BUYBACK_8K,
        EIGHTK,
        "Buyback authorized (8-K)",
        LONG,
        6,
        "8-K text announces a new share repurchase authorization",
    ),
    CEO_CFO_EXIT_8K: SignalSpec(
        CEO_CFO_EXIT_8K,
        EIGHTK,
        "CEO/CFO exit (8-K 5.02)",
        AVOID,
        3,
        "8-K Item 5.02 says the CEO or CFO resigned, stepped down or was terminated",
    ),
    BANKRUPTCY_8K: SignalSpec(
        BANKRUPTCY_8K,
        EIGHTK,
        "Bankruptcy (8-K 1.03)",
        AVOID,
        1,
        "8-K Item 1.03 (bankruptcy or receivership)",
    ),
    AUDITOR_CHANGE_8K: SignalSpec(
        AUDITOR_CHANGE_8K,
        EIGHTK,
        "Auditor change (8-K 4.01)",
        AVOID,
        3,
        "8-K Item 4.01 (change in certifying accountant)",
    ),
    LATE_FILING_NT: SignalSpec(
        LATE_FILING_NT,
        EIGHTK,
        "Late filing (NT 10-K/10-Q)",
        AVOID,
        3,
        "NT 10-K or NT 10-Q notice of late filing",
    ),
}

COOLDOWN_DAYS = {BUYBACK_8K: 90}
DEFAULT_COOLDOWN = 30


@dataclass(frozen=True)
class Filing8K:
    """One 8-K or NT filing, reduced to what the rules need."""

    accession: str
    form: str
    cik: str
    name: str
    filing_date: date
    ticker: str = ""
    items: tuple[str, ...] = ()
    buyback_phrases: tuple[str, ...] = ()
    exit_phrases: tuple[str, ...] = ()
    exit_titles: tuple[str, ...] = ()
    merger: bool = False
    excerpt: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")


def _signal(kind: str, filing: Filing8K, score: float, explanation: str, **details) -> Signal:
    return Signal(
        type=kind,
        dedupe_key=f"{kind}:{filing.cik}:{filing.filing_date.isoformat()}",
        issuer_cik=filing.cik,
        issuer_name=filing.name,
        ticker=filing.ticker,
        signal_date=filing.filing_date,
        score=score,
        explanation=explanation,
        trigger_accession=filing.accession,
        details={
            "form": filing.form,
            "items": list(filing.items),
            "item_labels": [ITEM_LABELS.get(i, i) for i in filing.items],
            "excerpt": filing.excerpt,
            **details,
        },
    )


def classify(filing: Filing8K) -> list[Signal]:
    """Every signal this one filing triggers, before cooldowns."""
    if filing.is_amendment or not filing.cik:
        return []
    out: list[Signal] = []
    name = filing.name
    if filing.form in NT_FORMS:
        kind = "annual report (10-K)" if filing.form == "NT 10-K" else "quarterly report (10-Q)"
        out.append(
            _signal(
                LATE_FILING_NT,
                filing,
                60.0 if filing.form == "NT 10-K" else 50.0,
                f"{name} told the SEC its {kind} will be late ({filing.form}).",
            )
        )
        return out
    if not filing.form.startswith("8-K"):
        return out
    if filing.buyback_phrases:
        out.append(
            _signal(
                BUYBACK_8K,
                filing,
                60.0,
                f"{name} announced a new share repurchase authorization (8-K).",
                phrases=list(filing.buyback_phrases),
            )
        )
    if "5.02" in filing.items and filing.exit_phrases:
        who = "/".join(filing.exit_titles) or "CEO/CFO"
        out.append(
            _signal(
                CEO_CFO_EXIT_8K,
                filing,
                70.0 if "CEO" in filing.exit_titles else 60.0,
                f"{name}: the {who} is leaving (8-K Item 5.02).",
                titles=list(filing.exit_titles),
                phrases=list(filing.exit_phrases),
            )
        )
    if "1.03" in filing.items:
        out.append(
            _signal(
                BANKRUPTCY_8K,
                filing,
                90.0,
                f"{name} reported a bankruptcy or receivership (8-K Item 1.03).",
            )
        )
    if "4.01" in filing.items:
        out.append(
            _signal(AUDITOR_CHANGE_8K, filing, 50.0, f"{name} changed its auditor (8-K Item 4.01).")
        )
    return out


def detect(
    filings: Iterable[Filing8K],
    *,
    prior_signals: Mapping[tuple[str, str], Iterable[date]] | None = None,
) -> list[Signal]:
    """Signals from many filings, with the per-type cooldown applied.

    `prior_signals[(type, cik)]` holds dates of signals already fired (live mode).
    """
    raw: list[Signal] = []
    for filing in filings:
        raw += classify(filing)
    out: list[Signal] = []
    for kind in SPECS:
        of_kind = [s for s in raw if s.type == kind]
        days = COOLDOWN_DAYS.get(kind, DEFAULT_COOLDOWN)
        if prior_signals:
            of_kind = [
                s
                for s in of_kind
                if all(
                    abs((s.signal_date - d).days) >= days or d == s.signal_date
                    for d in prior_signals.get((kind, s.issuer_cik), ())
                )
            ]
        out += cooldown_filter(of_kind, days)
    return sorted(out, key=lambda s: (s.signal_date, s.type, s.issuer_cik))
