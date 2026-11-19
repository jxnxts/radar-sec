"""13F signal rules (pure; shared by the live job and the backtest)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from radar.models import Signal

from ..base import LONG, THIRTEENF, SignalSpec
from .holdings import Holding, Report
from .managers import NOTABLE_MANAGERS

FUND_CONSENSUS_13F = "fund_consensus_13f"
NOTABLE_FUND_NEW_13F = "notable_fund_new_13f"

ACTIVE_MIN_POSITIONS = 20
ACTIVE_MAX_POSITIONS = 500
MIN_PRIOR_HOLDERS = 20
TOP_N = 30
NOTABLE_MIN_WEIGHT = 0.01
DEADLINE_DAYS = 45

SPECS = {
    FUND_CONSENSUS_13F: SignalSpec(
        FUND_CONSENSUS_13F,
        THIRTEENF,
        "Fund consensus (13F breadth)",
        LONG,
        3,
        f"top {TOP_N} stocks by change in the number of active 13F filers holding them "
        "(filings up to the 45-day deadline)",
    ),
    NOTABLE_FUND_NEW_13F: SignalSpec(
        NOTABLE_FUND_NEW_13F,
        THIRTEENF,
        "Notable fund, new position (13F)",
        LONG,
        3,
        f"a listed manager opens a position worth ≥{NOTABLE_MIN_WEIGHT:.0%} of its 13F",
    ),
}

# CUSIP → (ticker, CIK, name) at a date; None when the CUSIP cannot be mapped.
Resolver = Callable[[str, date], tuple[str, str, str] | None]


def quarter_end(day: date) -> date:
    month = ((day.month - 1) // 3 + 1) * 3
    nxt = date(day.year + (month == 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def previous_quarter_end(period: date) -> date:
    return date(period.year, period.month - 2, 1) - timedelta(days=1)


def filing_deadline(period: date) -> date:
    """45 days after quarter end, rolled forward past weekends."""
    deadline = period + timedelta(days=DEADLINE_DAYS)
    while deadline.weekday() >= 5:
        deadline += timedelta(days=1)
    return deadline


def first_reports(reports: Iterable[Report | Holding]) -> dict[tuple[str, date], Report | Holding]:
    """One original report per (manager, quarter): the first one filed."""
    out: dict[tuple[str, date], Report] = {}
    for report in sorted(reports, key=lambda r: (r.filing_date, r.accession)):
        out.setdefault((report.cik, report.period), report)
    return out


@dataclass
class ConsensusStats:
    period: date
    deadline: date
    active_filers: int = 0
    universe: int = 0
    unmapped: int = 0


def fund_consensus(
    reports: Mapping[tuple[str, date], Report | Holding],
    period: date,
    resolve: Resolver,
    *,
    top_n: int = TOP_N,
    issuer_names: Mapping[str, str] | None = None,
) -> tuple[list[Signal], ConsensusStats]:
    """`fund_consensus_13f` for one report quarter (Chen, Hong & Stein breadth change)."""
    deadline = filing_deadline(period)
    prior_period = previous_quarter_end(period)
    stats = ConsensusStats(period=period, deadline=deadline)
    pairs: list[tuple[Report, Report]] = []
    for (cik, quarter), report in reports.items():
        if quarter != period or report.filing_date > deadline:
            continue
        if not ACTIVE_MIN_POSITIONS <= report.positions <= ACTIVE_MAX_POSITIONS:
            continue
        prior = reports.get((cik, prior_period))
        if prior is None or prior.filing_date > deadline:
            continue
        pairs.append((report, prior))
    stats.active_filers = len(pairs)
    if not pairs:
        return [], stats

    now: Counter[str] = Counter()
    before: Counter[str] = Counter()
    names: dict[str, str] = dict(issuer_names or {})
    for report, prior in pairs:
        now.update(report.cusips)
        before.update(prior.cusips)
        for cusip, name in getattr(report, "names", {}).items():
            names.setdefault(cusip, name)
    universe = [c for c, n in before.items() if n >= MIN_PRIOR_HOLDERS]
    stats.universe = len(universe)
    total = len(pairs)
    ranked = sorted(universe, key=lambda c: ((now[c] - before[c]) / total, now[c], c), reverse=True)

    signals: list[Signal] = []
    for cusip in ranked:
        if len(signals) >= top_n:
            break
        # Unmapped CUSIPs stay in the top N (without a ticker) so the funnel shows them.
        mapped = resolve(cusip, deadline)
        if mapped is None:
            stats.unmapped += 1
            mapped = ("", "", names.get(cusip, ""))
        ticker, cik, name = mapped
        delta = now[cusip] - before[cusip]
        rank = len(signals) + 1
        signals.append(
            Signal(
                type=FUND_CONSENSUS_13F,
                dedupe_key=f"{FUND_CONSENSUS_13F}:{cusip}:{period.isoformat()}",
                issuer_cik=cik,
                issuer_name=name or names.get(cusip, ""),
                ticker=ticker,
                signal_date=deadline,
                score=max(50.0, 100.0 - 1.5 * (rank - 1)),
                explanation=(
                    f"{delta:+d} active funds now hold {name or names.get(cusip, cusip)} "
                    f"({before[cusip]} → {now[cusip]} of {total}) in the 13Fs for "
                    f"{period.isoformat()}: #{rank} breadth gain of the quarter."
                ),
                trigger_accession=f"13f-consensus:{period.isoformat()}:{cusip}",
                details={
                    "cusip": cusip,
                    "period": period.isoformat(),
                    "holders_before": before[cusip],
                    "holders_now": now[cusip],
                    "active_filers": total,
                    "breadth_change": delta / total,
                    "rank": rank,
                },
            )
        )
    return signals, stats


def notable_new_positions(
    reports: dict[tuple[str, date], Report],
    resolve: Resolver,
    *,
    managers: dict[str, str] = NOTABLE_MANAGERS,
    min_weight: float = NOTABLE_MIN_WEIGHT,
) -> list[Signal]:
    """`notable_fund_new_13f`: a listed manager's position absent from its previous 13F."""
    by_manager: dict[str, list[Report]] = {}
    for (cik, _), report in reports.items():
        if cik in managers:
            by_manager.setdefault(cik, []).append(report)
    signals: list[Signal] = []
    for cik, items in by_manager.items():
        items.sort(key=lambda r: r.period)
        for prior, report in zip(items, items[1:], strict=False):
            for cusip in report.shares:
                if cusip in prior.shares:
                    continue
                weight = report.weight(cusip)
                if weight < min_weight:
                    continue
                mapped = resolve(cusip, report.filing_date)
                if mapped is None:
                    continue
                ticker, issuer_cik, name = mapped
                manager = managers[cik]
                signals.append(
                    Signal(
                        type=NOTABLE_FUND_NEW_13F,
                        dedupe_key=f"{NOTABLE_FUND_NEW_13F}:{cik}:{cusip}:{report.period}",
                        issuer_cik=issuer_cik,
                        issuer_name=name or report.names.get(cusip, ""),
                        ticker=ticker,
                        signal_date=report.filing_date,
                        score=min(100.0, 55.0 + 300.0 * weight),
                        explanation=(
                            f"{manager} opened a new position in "
                            f"{name or report.names.get(cusip, cusip)} worth {weight:.1%} of "
                            f"its 13F for {report.period.isoformat()}."
                        ),
                        # One filing can open several positions: the key keeps them apart
                        # (the AI summary cache is keyed by it).
                        trigger_accession=f"{report.accession}:{cusip}",
                        details={
                            "accession": report.accession,
                            "cusip": cusip,
                            "manager": manager,
                            "manager_cik": cik,
                            "period": report.period.isoformat(),
                            "weight": weight,
                            "shares": report.shares[cusip],
                            "previous_accession": prior.accession,
                        },
                    )
                )
    return sorted(signals, key=lambda s: (s.signal_date, s.dedupe_key))
