"""Shape of the data the dashboard receives (REST and WebSocket).

Codes and labels are English; free text written for people (explanation and
summary) goes as a `{lang: text}` map so the dashboard can switch languages live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from radar.backtest.datasets import normalize_symbol
from radar.edgar import filing_index_url
from radar.models import Signal
from radar.signals import (
    ACTIVIST_13D,
    BIG_OFFICER_BUY,
    CLUSTER_BUY,
    ROLE_13D_FILER,
    ROLE_JOINT_FILER,
    SIGNAL_LABELS,
    explanations,
)
from radar.sources.views import signal_extras
from radar.summary import localized_summaries

KIND_LABELS = {
    "buy": "Open-market buy",
    "sale": "Sale",
    "grant": "Grant",
    "exercise": "Option exercise",
    "tax": "Tax withholding",
    "gift": "Gift",
    "return_to_issuer": "Return to issuer",
    "conversion": "Conversion",
    "new_13d": "New 13D",
    "amended_13d": "13D amendment",
    "other": "Other",
}


def price_symbol(ticker: str | None) -> str:
    """Ticker in the format of the price and logo sources ("BRK.B" → "BRK-B"); "" if invalid."""
    return normalize_symbol(ticker)


def logo_url(ticker: str | None) -> str | None:
    symbol = price_symbol(ticker)
    return f"/api/logo/{quote(symbol)}" if symbol else None


def _insiders(signal: Signal) -> list[dict[str, Any]]:
    d = signal.details
    if signal.type == CLUSTER_BUY:
        return [
            {"name": i.get("name", ""), "role": i.get("role", ""), "value": i.get("value")}
            for i in d.get("insiders", [])
        ]
    if signal.type == BIG_OFFICER_BUY:
        role = d.get("role", "")
        if d.get("title") and d["title"].upper() != role.upper():
            role = f"{role} · {d['title']}" if role else d["title"]
        return [{"name": d.get("insider", ""), "role": role, "value": d.get("total_value")}]
    if signal.type == ACTIVIST_13D:
        people = [
            {
                "name": d.get("filer", ""),
                "role": ROLE_13D_FILER,
                "value": None,
                "percent": d.get("percent"),
            }
        ]
        people += [
            {"name": name, "role": ROLE_JOINT_FILER, "value": None}
            for name in d.get("co_filers", [])
        ]
        return people
    return []


def signal_view(
    signal: Signal,
    *,
    signal_id: str,
    mode: str,
    published_at: datetime | None = None,
    sector: str = "",
    outcome: dict[str, Any] | None = None,
    logo: bool = True,
    cached_ai: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`logo=False` when it is not certain the ticker still belongs to this company:
    a monogram is better than another company's logo. `cached_ai` holds the AI
    summaries already generated for this signal, by language."""
    d = signal.details
    published = published_at or signal.created_at or datetime.now(UTC)
    accessions = d.get("accessions") or [signal.trigger_accession]
    summaries, sources = localized_summaries(signal, cached_ai)
    return {
        "id": signal_id,
        "mode": mode,
        "type": signal.type,
        "label": SIGNAL_LABELS.get(signal.type, signal.type),
        "ticker": signal.ticker or "",
        "symbol": price_symbol(signal.ticker),
        "company": signal.issuer_name,
        "cik": signal.issuer_cik,
        "sector": sector,
        "date": signal.signal_date.isoformat(),
        "published_at": published.isoformat(timespec="seconds"),
        "score": signal.score,
        "explanation": explanations(signal),
        "summary": summaries,
        "summary_source": sources,
        "value": d.get("total_value"),
        "shares": d.get("shares"),
        "avg_price": d.get("avg_price"),
        "percent": d.get("percent"),
        "stake_increase": d.get("stake_increase"),
        "n_insiders": d.get("n_insiders") or (1 if signal.type != CLUSTER_BUY else 0),
        "insiders": _insiders(signal),
        "first_buy": d.get("first_buy"),
        "last_buy": d.get("last_buy"),
        "event_date": d.get("event_date"),
        "has_ceo_cfo": bool(d.get("has_ceo_cfo")) or signal.type == BIG_OFFICER_BUY,
        "activist_tone": bool(d.get("activist_tone")),
        "filing_url": (
            filing_index_url(signal.issuer_cik, signal.trigger_accession)
            if signal.issuer_cik and signal.trigger_accession
            else None
        ),
        "accession": signal.trigger_accession,
        "n_filings": len(accessions),
        "logo": logo_url(signal.ticker) if logo else None,
        "outcome": outcome,
        # Source of the signal and, for the extra sources, their own card fields.
        **signal_extras(signal),
    }


def filing_view(brief: dict[str, Any]) -> dict[str, Any]:
    """One entry of the filing tape."""
    kind = brief.get("kind", "other")
    return {
        "accession": brief["accession"],
        "form": brief["form"],
        "company": brief.get("company", ""),
        "ticker": brief.get("ticker", "") or "",
        "cik": brief.get("cik", ""),
        "filed_date": brief.get("filed_date"),
        "accepted_at": brief.get("accepted_at"),
        "url": brief.get("url"),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, KIND_LABELS["other"]),
        "who": brief.get("who", ""),
        "role": brief.get("role", ""),
        "value": brief.get("value"),
        "percent": brief.get("percent"),
    }
