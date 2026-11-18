"""Signal rules.

The functions here are pure: they take already normalized filings and return
signals. `watch` and the backtest call exactly the same functions, so what the
backtest measures is what live monitoring fires.

Time principle: a signal is born on the FILING date of the filing that completes
it (when the information becomes public) and only sees filings filed up to that
date. The transaction date decides whether a purchase is recent, never the
signal date.

Signal `details` use English keys and codes; `explain(signal, lang)` renders the
human explanation from them in any supported language.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from radar import fmt
from radar.config import SignalConfig
from radar.i18n import DEFAULT_LANG, LANGS, role_label, t
from radar.models import PurchaseFiling, Schedule13D, Signal

CLUSTER_BUY = "cluster_buy"
BIG_OFFICER_BUY = "big_officer_buy"
ACTIVIST_13D = "activist_13d"
SIGNAL_TYPES = (CLUSTER_BUY, BIG_OFFICER_BUY, ACTIVIST_13D)

# English labels (the API sends them; other languages come from the catalogs).
SIGNAL_LABELS = {kind: t(f"signal.{kind}", "en") for kind in SIGNAL_TYPES}

# Role codes stored in signal details (translated for display by `i18n.role_label`).
ROLE_DIRECTOR = "Director"
ROLE_OFFICER = "Officer"
ROLE_TEN_PERCENT = "10% owner"
ROLE_DIRECTOR_OFFICER = "Director/Officer"
ROLE_OTHER = "Other"
ROLE_13D_FILER = "13D filer"
ROLE_JOINT_FILER = "Joint filer"
UNIDENTIFIED_FILER = "Unidentified filer"

# Default cluster window, for details stored before `window_days` was recorded.
DEFAULT_WINDOW_DAYS = SignalConfig().cluster_window_days

_ACTIVIST_WORDS = re.compile(
    r"nominat|proxy|strategic alternative|sale of the (company|issuer)|board represent"
    r"|consent solicitation|undervalued|replace .{0,40}(director|management)|change .{0,20}board",
    re.I,
)

PriorSignals = Mapping[str, Iterable[date]]


def dedupe_key(signal_type: str, issuer_cik: str, signal_date: date) -> str:
    return f"{signal_type}:{issuer_cik}:{signal_date.isoformat()}"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _by_issuer(filings: Iterable[PurchaseFiling]) -> dict[str, list[PurchaseFiling]]:
    grouped: dict[str, list[PurchaseFiling]] = defaultdict(list)
    for filing in filings:
        if filing.issuer_cik and filing.purchases:
            grouped[filing.issuer_cik].append(filing)
    for items in grouped.values():
        items.sort(key=lambda f: (f.filing_date, f.accession))
    return grouped


class _Cooldown:
    """Blocks a new signal of the same type for the same issuer for `days` days."""

    def __init__(self, days: int, prior: Iterable[date] = ()):
        self.days = days
        self.dates = sorted(prior)

    def blocked(self, when: date) -> bool:
        return any(0 <= (when - d).days < self.days for d in self.dates)

    def mark(self, when: date) -> None:
        self.dates.append(when)


class _Groups:
    """Union-find to count truly distinct insiders.

    A joint Form 4 (fund + manager + partner) lists several people for the same
    purchase; they all count as a single insider. The same goes for two separate
    Form 4s reporting exactly the same transaction.
    """

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def purchase_role(filing: PurchaseFiling) -> str:
    """Role of a Form 4 buyer: the free-text title, else a role code."""
    if filing.officer_title:
        return filing.officer_title
    if filing.is_officer_or_director:
        return ROLE_DIRECTOR_OFFICER
    return ROLE_TEN_PERCENT


# ---------------------------------------------------------------- cluster_buy


def _cluster_at(
    trigger: PurchaseFiling, history: list[PurchaseFiling], cfg: SignalConfig
) -> dict | None:
    """Evaluates the cluster on the day `trigger` was filed; None if it does not close."""
    today = trigger.filing_date
    start = today - timedelta(days=cfg.cluster_window_days)

    groups = _Groups()
    seen_tx: dict[tuple, str] = {}
    counted_shares = 0.0
    value_by_filing: dict[str, float] = {}
    members: dict[str, PurchaseFiling] = {}
    first_buy: date | None = None
    last_buy: date | None = None

    for filing in history:
        # Only what was already public on the signal day counts. And a Form 4 filed
        # before the window starts cannot contain a purchase inside it.
        if not (start <= filing.filing_date <= today):
            continue
        recent = [p for p in filing.purchases if start <= p.date <= today]
        if not recent:
            continue
        anchor = f"filing:{filing.accession}"
        for cik in filing.owner_ciks:
            groups.union(anchor, f"cik:{cik}")
        members[filing.accession] = filing
        value = 0.0
        for buy in recent:
            # Same date, quantity, price AND final position: it is the same transaction
            # reported in another Form 4 (affiliates filing separately). Different
            # insiders buying equal lots on the same day end up with different
            # positions, so they still count separately.
            key = (buy.date, round(buy.shares, 4), round(buy.price, 4), buy.shares_after)
            if buy.shares_after is not None and key in seen_tx:
                groups.union(anchor, seen_tx[key])
                continue
            seen_tx.setdefault(key, anchor)
            value += buy.value
            counted_shares += buy.shares
            first_buy = buy.date if first_buy is None or buy.date < first_buy else first_buy
            last_buy = buy.date if last_buy is None or buy.date > last_buy else last_buy
        value_by_filing[filing.accession] = value

    if trigger.accession not in members:  # the day's filing brought no recent purchase
        return None

    insiders: dict[str, dict] = {}
    for accession, filing in members.items():
        root = groups.find(f"filing:{accession}")
        entry = insiders.setdefault(
            root,
            {"names": [], "role": "", "value": 0.0, "ceo": False, "cfo": False, "od": False},
        )
        for name in filing.owner_names:
            if name not in entry["names"]:
                entry["names"].append(name)
        entry["value"] += value_by_filing[accession]
        entry["ceo"] |= filing.is_ceo
        entry["cfo"] |= filing.is_cfo
        entry["od"] |= filing.is_officer_or_director
        if not entry["role"] or filing.officer_title:
            entry["role"] = purchase_role(filing)

    total = sum(e["value"] for e in insiders.values())
    if len(insiders) < cfg.cluster_min_insiders or total < cfg.cluster_min_value:
        return None

    ranked = sorted(insiders.values(), key=lambda e: -e["value"])
    total_shares = counted_shares
    return {
        "insiders": [
            {"name": " / ".join(e["names"][:3]), "role": e["role"], "value": round(e["value"], 2)}
            for e in ranked
        ],
        "n_insiders": len(insiders),
        "n_officer_director": sum(1 for e in insiders.values() if e["od"]),
        "total_value": round(total, 2),
        "shares": total_shares,
        "avg_price": round(total / total_shares, 4) if total_shares else None,
        "first_buy": first_buy.isoformat() if first_buy else None,
        "last_buy": last_buy.isoformat() if last_buy else None,
        "has_ceo_cfo": any(e["ceo"] or e["cfo"] for e in insiders.values()),
        "window_days": cfg.cluster_window_days,
        "accessions": sorted(members),
    }


def _cluster_score(details: dict, cfg: SignalConfig) -> float:
    extra_insiders = details["n_insiders"] - cfg.cluster_min_insiders
    size = math.log10(max(details["total_value"] / cfg.cluster_min_value, 1.0))
    score = 50 + _clamp(10 * extra_insiders, 0, 20) + _clamp(10 * size, 0, 20)
    return round(score + (10 if details["has_ceo_cfo"] else 0), 1)


def detect_cluster_buys(
    filings: Iterable[PurchaseFiling],
    cfg: SignalConfig,
    *,
    prior_signals: PriorSignals | None = None,
) -> list[Signal]:
    """At least N distinct insiders buying the same issuer on the market within the window."""
    signals: list[Signal] = []
    for issuer, history in _by_issuer(filings).items():
        cooldown = _Cooldown(cfg.cooldown_days, (prior_signals or {}).get(issuer, ()))
        filed = [f.filing_date for f in history]
        window = timedelta(days=cfg.cluster_window_days)
        for trigger in history:
            when = trigger.filing_date
            if cooldown.blocked(when):
                continue
            # `history` is in filing order: looking at the window slice is enough.
            nearby = history[bisect_left(filed, when - window) : bisect_right(filed, when)]
            details = _cluster_at(trigger, nearby, cfg)
            if details is None:
                continue
            cooldown.mark(when)
            signals.append(
                _with_explanation(
                    Signal(
                        type=CLUSTER_BUY,
                        dedupe_key=dedupe_key(CLUSTER_BUY, issuer, when),
                        issuer_cik=issuer,
                        issuer_name=trigger.issuer_name,
                        ticker=trigger.ticker,
                        signal_date=when,
                        score=_cluster_score(details, cfg),
                        explanation="",
                        trigger_accession=trigger.accession,
                        details=details,
                    )
                )
            )
    signals.sort(key=lambda s: (s.signal_date, s.issuer_cik))
    return signals


# ------------------------------------------------------------ big_officer_buy


def _officer_role(filing: PurchaseFiling) -> str:
    if filing.is_ceo and filing.is_cfo:
        return "CEO/CFO"
    return "CEO" if filing.is_ceo else "CFO"


def _stake_increase(filing: PurchaseFiling) -> float | None:
    """How much the position grew with the purchase (0.25 = +25%)."""
    if not filing.shares_after:
        return None
    before = filing.shares_after - filing.shares
    return filing.shares / before if before > 0 else None


def detect_big_officer_buys(
    filings: Iterable[PurchaseFiling],
    cfg: SignalConfig,
    *,
    prior_signals: PriorSignals | None = None,
) -> list[Signal]:
    """A CEO or CFO buying at least the minimum value on the market in a single Form 4."""
    signals: list[Signal] = []
    for issuer, history in _by_issuer(filings).items():
        cooldown = _Cooldown(cfg.cooldown_days, (prior_signals or {}).get(issuer, ()))
        for filing in history:
            if not (filing.is_ceo or filing.is_cfo) or filing.value < cfg.officer_min_value:
                continue
            when = filing.filing_date
            if cooldown.blocked(when):
                continue
            cooldown.mark(when)

            increase = _stake_increase(filing)
            dates = [p.date for p in filing.purchases]
            size = math.log10(max(filing.value / cfg.officer_min_value, 1.0))
            score = 50 + _clamp(20 * size, 0, 30) + (10 if filing.is_ceo else 5)
            if increase is not None:
                score += _clamp(100 * increase, 0, 10)

            signals.append(
                _with_explanation(
                    Signal(
                        type=BIG_OFFICER_BUY,
                        dedupe_key=dedupe_key(BIG_OFFICER_BUY, issuer, when),
                        issuer_cik=issuer,
                        issuer_name=filing.issuer_name,
                        ticker=filing.ticker,
                        signal_date=when,
                        score=round(score, 1),
                        explanation="",
                        trigger_accession=filing.accession,
                        details={
                            "insider": " / ".join(filing.owner_names[:2]) or ROLE_OFFICER,
                            "role": _officer_role(filing),
                            "title": filing.officer_title,
                            "total_value": round(filing.value, 2),
                            "shares": filing.shares,
                            "avg_price": round(filing.avg_price, 4),
                            "first_buy": min(dates).isoformat(),
                            "last_buy": max(dates).isoformat(),
                            "stake_increase": (
                                round(increase, 4) if increase is not None else None
                            ),
                            "accessions": [filing.accession],
                        },
                    )
                )
            )
    signals.sort(key=lambda s: (s.signal_date, s.issuer_cik))
    return signals


# --------------------------------------------------------------- activist_13d


def detect_activist_13d(
    doc: Schedule13D,
    *,
    accession: str,
    filing_date: date,
    cfg: SignalConfig,
    ticker: str = "",
) -> Signal | None:
    """A new 13D (not an amendment) reporting a stake of at least the configured minimum."""
    percent = doc.max_percent
    if doc.is_amendment or percent is None or percent < cfg.activist_min_percent:
        return None

    lead = max((r for r in doc.reporters if r.percent is not None), key=lambda r: r.percent)
    others = [r.name for r in doc.reporters if r is not lead and r.name]
    activist_tone = bool(_ACTIVIST_WORDS.search(doc.purpose or ""))

    score = 50 + _clamp(2 * (percent - cfg.activist_min_percent), 0, 30)
    score += 10 if activist_tone else 0

    return _with_explanation(
        Signal(
            type=ACTIVIST_13D,
            dedupe_key=dedupe_key(ACTIVIST_13D, doc.issuer_cik or accession, filing_date),
            issuer_cik=doc.issuer_cik,
            issuer_name=doc.issuer_name,
            ticker=ticker,
            signal_date=filing_date,
            score=round(score, 1),
            explanation="",
            trigger_accession=accession,
            details={
                "filer": lead.name or UNIDENTIFIED_FILER,
                "percent": percent,
                "shares": lead.shares,
                "co_filers": others,
                "event_date": doc.event_date.isoformat() if doc.event_date else None,
                "cusip": doc.cusip,
                "source_format": doc.source_format,
                "activist_tone": activist_tone,
                "purpose": (doc.purpose or "")[:1500],
                "accessions": [accession],
            },
        )
    )


# ---------------------------------------------------------------- explanation


def _with_explanation(signal: Signal) -> Signal:
    """Stores the English explanation (the database column is always English)."""
    signal.explanation = explain(signal, "en")
    return signal


def _company(signal: Signal) -> str:
    return signal.issuer_name + (f" ({signal.ticker})" if signal.ticker else "")


def explain(signal: Signal, lang: str = DEFAULT_LANG) -> str:
    """Why the signal fired, in `lang`, rendered from `signal.details` alone."""
    d = signal.details
    if signal.type == CLUSTER_BUY:
        who = "; ".join(
            t(
                "explain.cluster.member",
                lang,
                name=i.get("name", ""),
                role=role_label(i.get("role"), lang),
                value=fmt.usd(i.get("value"), lang),
            )
            for i in d.get("insiders", [])[:5]
        )
        n_insiders = d.get("n_insiders") or 0
        if n_insiders > 5:
            who += t("explain.cluster.more", lang, n=n_insiders - 5)
        return t(
            "explain.cluster",
            lang,
            n=n_insiders,
            value=fmt.usd(d.get("total_value"), lang),
            company=_company(signal),
            first=fmt.iso_day(d.get("first_buy"), lang),
            last=fmt.iso_day(d.get("last_buy"), lang),
            window=d.get("window_days") or DEFAULT_WINDOW_DAYS,
            who=who,
        )
    if signal.type == BIG_OFFICER_BUY:
        role = d.get("role", "")
        title = role + (f", {d['title']}" if d.get("title") else "")
        text = t(
            "explain.officer",
            lang,
            who=role_label(d.get("insider"), lang),
            title=title,
            value=fmt.usd(d.get("total_value"), lang),
            company=_company(signal),
            shares=fmt.number(d.get("shares"), lang=lang),
            price=fmt.price(d.get("avg_price"), lang),
            day=fmt.iso_day(d.get("last_buy"), lang),
        )
        if d.get("stake_increase") is not None:
            text += t("explain.officer.increase", lang, pct=fmt.pct(d["stake_increase"], lang=lang))
        return text
    if signal.type == ACTIVIST_13D:
        shares = d.get("shares")
        text = t(
            "explain.activist",
            lang,
            who=role_label(d.get("filer"), lang),
            pct=fmt.pct_points(d.get("percent"), lang=lang),
            company=signal.issuer_name,
            shares=(
                t("explain.activist.shares", lang, shares=fmt.number(shares, lang=lang))
                if shares
                else ""
            ),
        )
        if others := d.get("co_filers"):
            text += t("explain.activist.joint", lang, names=", ".join(others[:4]))
        if d.get("activist_tone"):
            text += t("explain.activist.tone", lang)
        if d.get("source_format") == "legacy":
            text += t("explain.activist.legacy", lang)
        return text
    return signal.explanation


def explanations(signal: Signal) -> dict[str, str]:
    """The explanation in every supported language (`{lang: text}`)."""
    return {lang: explain(signal, lang) for lang in LANGS}
