"""Form 144 signal rules. Pure functions: the live monitor and the backtest call them alike."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from radar.models import Signal

from ..base import AVOID, CONTEXT, FORM144, SignalSpec

FORM144_CLUSTER = "form144_cluster"
FORM144_LARGE = "form144_large"

CLUSTER_MIN_SELLERS = 3
CLUSTER_WINDOW_DAYS = 10
COOLDOWN_DAYS = 30
LARGE_MIN_VALUE = 10_000_000.0
LARGE_MIN_PERCENT = 1.0

SPECS = {
    FORM144_CLUSTER: SignalSpec(
        FORM144_CLUSTER,
        FORM144,
        "Form 144 cluster",
        AVOID,
        3,
        f"≥{CLUSTER_MIN_SELLERS} distinct sellers file Form 144 for the same issuer "
        f"within {CLUSTER_WINDOW_DAYS} days",
    ),
    FORM144_LARGE: SignalSpec(
        FORM144_LARGE,
        FORM144,
        "Large planned sale (144)",
        CONTEXT,
        None,
        f"one Form 144 ≥ US$ {LARGE_MIN_VALUE / 1e6:.0f} mi or ≥ {LARGE_MIN_PERCENT:.0f}% "
        "of units outstanding (not tested)",
    ),
}


@dataclass(frozen=True)
class Notice:
    """The minimum a rule needs from a Form 144: who, which issuer, when it went public."""

    accession: str
    issuer_cik: str
    issuer_name: str
    seller_cik: str
    seller_name: str
    filing_date: date
    ticker: str = ""
    market_value: float | None = None
    percent_outstanding: float | None = None
    relationships: tuple[str, ...] = field(default_factory=tuple)
    units: float | None = None
    units_outstanding: float | None = None
    approx_sale_date: date | None = None


def detect_clusters(
    notices: Iterable[Notice],
    *,
    min_sellers: int = CLUSTER_MIN_SELLERS,
    window_days: int = CLUSTER_WINDOW_DAYS,
    cooldown_days: int = COOLDOWN_DAYS,
    prior_signals: Mapping[str, Iterable[date]] | None = None,
) -> list[Signal]:
    """`form144_cluster`: the day the N-th distinct seller files within the window.

    Only notices filed up to that day are visible to the rule, so the signal never
    uses information from the future.
    """
    by_issuer: dict[str, list[Notice]] = defaultdict(list)
    for notice in notices:
        if notice.issuer_cik and notice.seller_cik:
            by_issuer[notice.issuer_cik].append(notice)

    out: list[Signal] = []
    for issuer, items in by_issuer.items():
        items.sort(key=lambda n: (n.filing_date, n.accession))
        fired = sorted((prior_signals or {}).get(issuer, ()))
        last_fired = fired[-1] if fired else None
        for i, notice in enumerate(items):
            day = notice.filing_date
            if last_fired is not None and (day - last_fired).days < cooldown_days:
                continue
            start = day - timedelta(days=window_days - 1)
            window = [n for n in items[: i + 1] if n.filing_date >= start]
            sellers: dict[str, Notice] = {}
            for n in window:
                sellers.setdefault(n.seller_cik, n)
            if len(sellers) < min_sellers or notice.seller_cik not in sellers:
                continue
            # The notice that completes the cluster must be a new seller (else the
            # cluster was already complete and has fired or was in cooldown).
            if sellers[notice.seller_cik] is not notice:
                continue
            values = [n.market_value for n in window if n.market_value]
            total = sum(values) if values else None
            people = list(sellers.values())
            out.append(
                Signal(
                    type=FORM144_CLUSTER,
                    dedupe_key=f"{FORM144_CLUSTER}:{issuer}:{day.isoformat()}",
                    issuer_cik=issuer,
                    issuer_name=notice.issuer_name,
                    ticker=notice.ticker or next((n.ticker for n in window if n.ticker), ""),
                    signal_date=day,
                    score=min(100.0, 40.0 + 10.0 * len(sellers)),
                    explanation=(
                        f"{len(sellers)} insiders filed Form 144 (planned sale) for "
                        f"{notice.issuer_name} within {window_days} days"
                        + (f", about US$ {total / 1e6:,.1f} mi in total" if total else "")
                        + "."
                    ),
                    trigger_accession=notice.accession,
                    details={
                        "n_sellers": len(sellers),
                        "sellers": [
                            {
                                "name": p.seller_name,
                                "cik": p.seller_cik,
                                "role": ", ".join(p.relationships),
                                "value": p.market_value,
                                "date": p.filing_date.isoformat(),
                            }
                            for p in people
                        ],
                        "total_value": total,
                        "first_notice": window[0].filing_date.isoformat(),
                        "accessions": [n.accession for n in window],
                        "window_days": window_days,
                    },
                )
            )
            last_fired = day
    return sorted(out, key=lambda s: (s.signal_date, s.issuer_cik))


def large_sale(notice: Notice) -> Signal | None:
    """`form144_large` (context only): one big planned sale."""
    value = notice.market_value or 0.0
    percent = notice.percent_outstanding or 0.0
    if value < LARGE_MIN_VALUE and percent < LARGE_MIN_PERCENT:
        return None
    parts = []
    if value:
        parts.append(f"US$ {value / 1e6:,.1f} mi")
    if percent:
        parts.append(f"{percent:.2f}% of the shares outstanding")
    role = ", ".join(notice.relationships) or "affiliate"
    return Signal(
        type=FORM144_LARGE,
        dedupe_key=f"{FORM144_LARGE}:{notice.accession}",
        issuer_cik=notice.issuer_cik,
        issuer_name=notice.issuer_name,
        ticker=notice.ticker,
        signal_date=notice.filing_date,
        score=min(100.0, 50.0 + 5.0 * (value / LARGE_MIN_VALUE) + 10.0 * percent),
        explanation=(
            f"{notice.seller_name} ({role}) plans to sell {' / '.join(parts)} of "
            f"{notice.issuer_name} (Form 144)."
        ),
        trigger_accession=notice.accession,
        details={
            "seller": notice.seller_name,
            "role": role,
            "total_value": value or None,
            "percent_outstanding": percent or None,
            "tested": False,
        },
    )
