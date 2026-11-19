"""Human-facing text of the new signals and events, rendered per language from stored
details (the database keeps English codes and numbers only)."""

from __future__ import annotations

from typing import Any

from radar import fmt
from radar.i18n import CATALOGS, DEFAULT_LANG, EN, LANGS, PT_BR, role_label, t
from radar.models import Signal


def _shares(value: float | None, lang: str) -> str:
    if value is None:
        return fmt.na(lang)
    if abs(value) >= 1e6:
        unit = " mi" if lang == PT_BR else "M"
        return fmt.number(value / 1e6, 1, lang=lang) + unit
    if abs(value) >= 1e3:
        unit = " mil" if lang == PT_BR else "K"
        return fmt.number(value / 1e3, 0, lang=lang) + unit
    return fmt.number(value, 0, lang=lang)


def explain(signal: Signal, lang: str = DEFAULT_LANG) -> str | None:
    """Why a signal of a new type fired; None for types this package does not own."""
    d: dict[str, Any] = signal.details
    company = signal.issuer_name or signal.ticker
    kind = signal.type
    if kind == "form144_cluster":
        sellers = d.get("sellers", [])
        who = "; ".join(
            f"{s.get('name', '')} ({role_label(s.get('role') or '', lang) or '—'})"
            for s in sellers[:5]
        )
        total = d.get("total_value")
        return t(
            "explain.form144_cluster",
            lang,
            n=d.get("n_sellers", len(sellers)),
            company=company,
            window=d.get("window_days", 10),
            total=t("explain.form144_cluster.total", lang, value=fmt.usd(total, lang))
            if total
            else "",
            who=who,
        )
    if kind == "form144_large":
        pct = d.get("percent_outstanding")
        return t(
            "explain.form144_large",
            lang,
            seller=d.get("seller", ""),
            role=role_label(d.get("role") or "", lang) or t("event.role.affiliate", lang),
            value=fmt.usd(d.get("total_value"), lang),
            pct=t("explain.form144_large.pct", lang, pct=fmt.pct_points(pct, lang=lang))
            if pct
            else "",
            company=company,
        )
    if kind == "fund_consensus_13f":
        before, now = d.get("holders_before", 0), d.get("holders_now", 0)
        return t(
            "explain.fund_consensus_13f",
            lang,
            delta=f"{now - before:+d}",
            company=company,
            before=before,
            now=now,
            total=d.get("active_filers", 0),
            period=fmt.iso_day(d.get("period"), lang),
            rank=d.get("rank", 0),
        )
    if kind == "notable_fund_new_13f":
        return t(
            "explain.notable_fund_new_13f",
            lang,
            manager=d.get("manager", ""),
            company=company,
            weight=fmt.pct(d.get("weight"), lang=lang),
            period=fmt.iso_day(d.get("period"), lang),
        )
    if kind in ("buyback_8k", "bankruptcy_8k", "auditor_change_8k"):
        return t(f"explain.{kind}", lang, company=company)
    if kind == "ceo_cfo_exit_8k":
        return t(
            "explain.ceo_cfo_exit_8k",
            lang,
            company=company,
            who="/".join(d.get("titles") or ["CEO/CFO"]),
        )
    if kind == "late_filing_nt":
        form = d.get("form", "NT 10-Q")
        report = "annual" if form == "NT 10-K" else "quarterly"
        return t(
            "explain.late_filing_nt",
            lang,
            company=company,
            form=form,
            report=t(f"explain.late_filing_nt.{report}", lang),
        )
    if kind in ("short_crowded", "squeeze_setup"):
        return t(
            f"explain.{kind}",
            lang,
            ticker=signal.ticker or d.get("symbol", ""),
            change=fmt.pct(d.get("change"), 0, signed=True, lang=lang),
            shares=_shares(d.get("short_shares"), lang),
            dtc=fmt.number(d.get("days_to_cover"), 1, lang=lang),
            settled=fmt.iso_day(d.get("settlement_date"), lang),
            move=fmt.pct(d.get("momentum"), 0, signed=True, lang=lang),
        )
    if kind == "ftd_persistent":
        return t(
            "explain.ftd_persistent",
            lang,
            ticker=signal.ticker or d.get("symbol", ""),
            days=d.get("run_days", 0),
            peak=_shares(d.get("peak_fails"), lang),
            fraction=fmt.pct(d.get("peak_fraction"), 1, lang=lang),
        )
    return None


def explanations(signal: Signal) -> dict[str, str] | None:
    if explain(signal, EN) is None:
        return None
    return {lang: explain(signal, lang) or "" for lang in LANGS}


def item_label(code: str, lang: str = DEFAULT_LANG) -> str:
    key = f"item.{code}"
    return t(key, lang) if key in CATALOGS[EN] else code


def event_title(kind: str, data: dict[str, Any], fallback: str, lang: str = DEFAULT_LANG) -> str:
    """Tape line of a market event, in `lang`."""
    if kind == "form144":
        roles = data.get("relationships") or []
        role = ", ".join(role_label(r, lang) for r in roles) or t("event.role.affiliate", lang)
        return t(
            "event.form144",
            lang,
            seller=data.get("seller", ""),
            role=role,
            value=fmt.usd(data.get("value"), lang),
        )
    if kind == "8k":
        items = [item_label(i, lang) for i in data.get("items", []) if i != "9.01"]
        return t("event.8k", lang, items="; ".join(items)) if items else t("event.8k.none", lang)
    if kind == "nt_filing":
        form = data.get("form", "")
        report = "annual" if form == "NT 10-K" else "quarterly"
        return t("event.nt_filing", lang, form=form, report=t(f"event.nt_filing.{report}", lang))
    if kind == "13f_filing":
        return t(
            "event.13f_filing",
            lang,
            manager=data.get("manager", ""),
            period=fmt.iso_day(data.get("period"), lang),
            positions=data.get("positions", 0),
            new=data.get("new_positions", 0),
        )
    if kind == "13f_consensus":
        return t(
            "event.13f_consensus",
            lang,
            period=fmt.iso_day(data.get("period"), lang),
            filers=fmt.number(data.get("active_filers"), lang=lang),
        )
    if kind == "short_interest_release":
        return t(
            "event.short_interest_release",
            lang,
            settled=fmt.iso_day(data.get("settlement_date"), lang),
            symbols=fmt.number(data.get("symbols"), lang=lang),
            flagged=len(data.get("flagged") or []),
        )
    if kind == "ftd_release":
        return t(
            "event.ftd_release",
            lang,
            file=data.get("file", ""),
            rows=fmt.number(data.get("rows"), lang=lang),
            flagged=len(data.get("flagged") or []),
        )
    return fallback
