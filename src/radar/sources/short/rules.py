"""Short-interest and fails-to-deliver signal rules (pure; live and backtest alike)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date

from radar.models import Signal

from ..base import AVOID, LONG, SHORT, SignalSpec, cooldown_filter
from .data import Fail, ShortInterest

SHORT_CROWDED = "short_crowded"
SQUEEZE_SETUP = "squeeze_setup"
FTD_PERSISTENT = "ftd_persistent"

CROWDED_MIN_DTC = 7.0
CROWDED_MIN_SHARES = 1_000_000.0
CROWDED_MIN_RISE = 0.25
CROWDED_MIN_VOLUME = 100_000.0
SQUEEZE_MIN_DTC = 7.0
SQUEEZE_MAX_CHANGE = -0.15
SQUEEZE_MIN_MOMENTUM = 0.20
SQUEEZE_SESSIONS = 10
FTD_MIN_SHARES = 10_000.0
FTD_MIN_FRACTION = 0.005
FTD_MIN_RUN = 5
COOLDOWN_DAYS = 30

SPECS = {
    SHORT_CROWDED: SignalSpec(
        SHORT_CROWDED,
        SHORT,
        "Crowded short (FINRA)",
        AVOID,
        1,
        f"days to cover ≥ {CROWDED_MIN_DTC:g}, short ≥ 1 mi shares and up ≥ "
        f"{CROWDED_MIN_RISE:.0%} vs the previous report",
    ),
    SQUEEZE_SETUP: SignalSpec(
        SQUEEZE_SETUP,
        SHORT,
        "Squeeze setup (FINRA + price)",
        LONG,
        1,
        f"days to cover ≥ {SQUEEZE_MIN_DTC:g}, short down ≥ {-SQUEEZE_MAX_CHANGE:.0%} and price "
        f"up ≥ {SQUEEZE_MIN_MOMENTUM:.0%} in {SQUEEZE_SESSIONS} sessions",
    ),
    FTD_PERSISTENT: SignalSpec(
        FTD_PERSISTENT,
        SHORT,
        "Persistent fails-to-deliver (SEC)",
        AVOID,
        1,
        f"fails ≥ 10k shares and ≥ {FTD_MIN_FRACTION:.1%} of shares outstanding on "
        f"{FTD_MIN_RUN} consecutive settlement days",
    ),
}

# symbol → (CIK, current ticker, company name), or None when it is not an SEC registrant.
Registrant = Callable[[str], tuple[str, str, str] | None]


def eligible(record: ShortInterest, registrant: Registrant) -> tuple[str, str, str] | None:
    if not record.listed or record.fund_like:
        return None
    return registrant(record.symbol)


def _change(record: ShortInterest) -> float | None:
    if not record.previous_short_shares or record.previous_short_shares <= 0:
        return None
    return record.short_shares / record.previous_short_shares - 1.0


def _short_signal(
    kind: str,
    record: ShortInterest,
    who: tuple[str, str, str],
    public: date,
    score: float,
    explanation: str,
    **details,
) -> Signal:
    cik, ticker, name = who
    return Signal(
        type=kind,
        dedupe_key=f"{kind}:{record.symbol}:{record.settlement_date.isoformat()}",
        issuer_cik=cik,
        issuer_name=name or record.name,
        ticker=ticker or record.symbol,
        signal_date=public,
        score=score,
        explanation=explanation,
        trigger_accession=f"finra-si:{record.settlement_date.isoformat()}:{record.symbol}",
        details={
            "symbol": record.symbol,
            "settlement_date": record.settlement_date.isoformat(),
            "short_shares": record.short_shares,
            "previous_short_shares": record.previous_short_shares,
            "days_to_cover": record.days_to_cover,
            "avg_daily_volume": record.avg_daily_volume,
            "change": _change(record),
            **details,
        },
    )


def crowded_shorts(
    records: Iterable[ShortInterest],
    registrant: Registrant,
    public_date: Callable[[date], date],
) -> list[Signal]:
    out: list[Signal] = []
    for r in records:
        change = _change(r)
        if (
            r.days_to_cover is None
            or r.days_to_cover < CROWDED_MIN_DTC
            or r.short_shares < CROWDED_MIN_SHARES
            or change is None
            or change < CROWDED_MIN_RISE
            or (r.avg_daily_volume or 0) < CROWDED_MIN_VOLUME
        ):
            continue
        who = eligible(r, registrant)
        if who is None:
            continue
        out.append(
            _short_signal(
                SHORT_CROWDED,
                r,
                who,
                public_date(r.settlement_date),
                min(100.0, 50.0 + 3.0 * r.days_to_cover + 30.0 * min(change, 1.0)),
                f"Short interest in {who[1] or r.symbol} rose {change:+.0%} to "
                f"{r.short_shares / 1e6:,.1f} mi shares ({r.days_to_cover:.1f} days to cover) "
                f"as of {r.settlement_date.isoformat()}.",
            )
        )
    return cooldown_filter(out, COOLDOWN_DAYS)


def squeeze_candidates(
    records: Iterable[ShortInterest], registrant: Registrant
) -> list[tuple[ShortInterest, tuple[str, str, str]]]:
    """Short-interest part of `squeeze_setup`; the price part needs a price series."""
    out = []
    for r in records:
        change = _change(r)
        if (
            r.days_to_cover is None
            or r.days_to_cover < SQUEEZE_MIN_DTC
            or change is None
            or change > SQUEEZE_MAX_CHANGE
        ):
            continue
        who = eligible(r, registrant)
        if who is not None:
            out.append((r, who))
    return out


def squeezes(
    candidates: Iterable[tuple[ShortInterest, tuple[str, str, str]]],
    public_date: Callable[[date], date],
    momentum: Callable[[str, date], float | None],
) -> list[Signal]:
    """`momentum(ticker, day)`: adjusted return over the 10 sessions ending on `day`."""
    out: list[Signal] = []
    for r, who in candidates:
        public = public_date(r.settlement_date)
        move = momentum(who[1] or r.symbol, public)
        if move is None or move < SQUEEZE_MIN_MOMENTUM:
            continue
        change = _change(r) or 0.0
        out.append(
            _short_signal(
                SQUEEZE_SETUP,
                r,
                who,
                public,
                min(100.0, 50.0 + 2.0 * (r.days_to_cover or 0) + 50.0 * min(move, 1.0)),
                f"Shorts in {who[1] or r.symbol} are covering ({change:+.0%}, "
                f"{r.days_to_cover:.1f} days to cover) while the price rose {move:+.0%} in "
                f"{SQUEEZE_SESSIONS} sessions.",
                momentum=move,
            )
        )
    return cooldown_filter(out, COOLDOWN_DAYS)


def persistent_fails(
    fails: Iterable[Fail],
    available: date,
    registrant: Registrant,
    shares_outstanding: Callable[[str, date], float | None],
    *,
    file_name: str = "",
) -> list[Signal]:
    """`ftd_persistent` for one half-month file, dated when the file became public."""
    rows = list(fails)
    calendar = sorted({f.settlement_date for f in rows})
    position = {day: i for i, day in enumerate(calendar)}
    by_symbol: dict[str, list[Fail]] = defaultdict(list)
    for fail in rows:
        by_symbol[fail.symbol].append(fail)

    out: list[Signal] = []
    for symbol, items in by_symbol.items():
        who = registrant(symbol)
        if who is None:
            continue
        cik, ticker, name = who
        outstanding = shares_outstanding(cik, available)
        if not outstanding:
            continue
        threshold = max(FTD_MIN_SHARES, FTD_MIN_FRACTION * outstanding)
        days = sorted({position[f.settlement_date] for f in items if f.quantity >= threshold})
        best = run = 0
        previous = None
        for index in days:
            run = run + 1 if previous is not None and index == previous + 1 else 1
            best = max(best, run)
            previous = index
        if best < FTD_MIN_RUN:
            continue
        peak = max(items, key=lambda f: f.quantity)
        out.append(
            Signal(
                type=FTD_PERSISTENT,
                dedupe_key=f"{FTD_PERSISTENT}:{symbol}:{file_name or available.isoformat()}",
                issuer_cik=cik,
                issuer_name=name or peak.description,
                ticker=ticker or symbol,
                signal_date=available,
                score=min(100.0, 50.0 + 5.0 * best + 2000.0 * peak.quantity / outstanding),
                explanation=(
                    f"{ticker or symbol} had fails-to-deliver above "
                    f"{FTD_MIN_FRACTION:.1%} of its shares on {best} consecutive settlement "
                    f"days (peak {peak.quantity / 1e3:,.0f}k shares, "
                    f"{peak.quantity / outstanding:.1%} of outstanding)."
                ),
                trigger_accession=f"sec-ftd:{file_name or available.isoformat()}:{symbol}",
                details={
                    "symbol": symbol,
                    "run_days": best,
                    "peak_fails": peak.quantity,
                    "peak_date": peak.settlement_date.isoformat(),
                    "peak_fraction": peak.quantity / outstanding,
                    "shares_outstanding": outstanding,
                    "file": file_name,
                    "cusip": peak.cusip,
                },
            )
        )
    return out
