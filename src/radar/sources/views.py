"""What the dashboard receives about the extra sources (REST and WebSocket).

Codes and numbers go as they are; text written for people (event titles) goes as a
`{lang: text}` map, like the rest of the API.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from radar.backtest.datasets import normalize_symbol
from radar.edgar import filing_index_url
from radar.i18n import localized
from radar.models import Signal

from .base import EIGHTK, FORM144, SHORT, THIRTEENF
from .explain import event_title
from .short.data import FTD_PAGE_URL
from .specs import SPECS
from .store import SourceStore

INSIDERS = "insiders"
FINRA_SHORT_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")

CONTEXT_DAYS = {FORM144: 180, EIGHTK: 365, THIRTEENF: 400}


def source_of(signal_type: str) -> str:
    spec = SPECS.get(signal_type)
    return spec.source if spec else INSIDERS


def _fact(key: str, value: Any, kind: str) -> dict[str, Any] | None:
    """One labeled number of a card; the dashboard labels `key` and formats by `kind`."""
    if value is None or value == "" or value == []:
        return None
    return {"key": key, "value": value, "kind": kind}


def _facts(signal: Signal) -> list[dict[str, Any]]:
    d = signal.details
    kind = signal.type
    if kind == "form144_cluster":
        items = [
            _fact("sellers", d.get("n_sellers"), "number"),
            _fact("planned_value", d.get("total_value"), "usd"),
            _fact("first_notice", d.get("first_notice"), "date"),
        ]
    elif kind == "form144_large":
        items = [
            _fact("planned_value", d.get("total_value"), "usd"),
            _fact("of_outstanding", d.get("percent_outstanding"), "points"),
            _fact("seller", d.get("seller"), "text"),
        ]
    elif kind == "fund_consensus_13f":
        items = [
            _fact("breadth_change", d.get("breadth_change"), "pct"),
            _fact("holders", f"{d.get('holders_before')} → {d.get('holders_now')}", "text"),
            _fact("rank", d.get("rank"), "number"),
            _fact("quarter", d.get("period"), "date"),
        ]
    elif kind == "notable_fund_new_13f":
        items = [
            _fact("manager", d.get("manager"), "text"),
            _fact("weight", d.get("weight"), "pct"),
            _fact("quarter", d.get("period"), "date"),
        ]
    elif kind in (
        "buyback_8k",
        "ceo_cfo_exit_8k",
        "bankruptcy_8k",
        "auditor_change_8k",
        "late_filing_nt",
    ):
        items = [
            _fact("form", d.get("form"), "text"),
            _fact("items", d.get("items"), "items"),
            _fact("excerpt", d.get("excerpt"), "quote"),
        ]
    elif kind in ("short_crowded", "squeeze_setup"):
        items = [
            _fact("days_to_cover", d.get("days_to_cover"), "decimal"),
            _fact("short_change", d.get("change"), "pct"),
            _fact("short_shares", d.get("short_shares"), "shares"),
            _fact("momentum", d.get("momentum"), "pct"),
            _fact("settlement", d.get("settlement_date"), "date"),
        ]
    elif kind == "ftd_persistent":
        items = [
            _fact("fail_days", d.get("run_days"), "number"),
            _fact("peak_fraction", d.get("peak_fraction"), "pct"),
            _fact("peak_fails", d.get("peak_fails"), "shares"),
            _fact("peak_date", d.get("peak_date"), "date"),
        ]
    else:
        items = []
    return [item for item in items if item is not None]


def _people(signal: Signal) -> list[dict[str, Any]] | None:
    """People on the card of a new signal type, in the same shape as the insiders."""
    d = signal.details
    if signal.type == "form144_cluster":
        return [
            {"name": s.get("name", ""), "role": s.get("role", ""), "value": s.get("value")}
            for s in d.get("sellers", [])
        ]
    if signal.type == "form144_large":
        return [
            {"name": d.get("seller", ""), "role": d.get("role", ""), "value": d.get("total_value")}
        ]
    if signal.type == "notable_fund_new_13f":
        return [{"name": d.get("manager", ""), "role": "13F", "value": None}]
    return None


def _url(signal: Signal) -> str | None:
    d = signal.details
    if signal.type == "notable_fund_new_13f" and d.get("manager_cik") and d.get("accession"):
        return filing_index_url(d["manager_cik"], d["accession"])
    if signal.type in ("short_crowded", "squeeze_setup"):
        return FINRA_SHORT_URL
    if signal.type == "ftd_persistent":
        return FTD_PAGE_URL
    if signal.issuer_cik and _ACCESSION.match(signal.trigger_accession or ""):
        return filing_index_url(signal.issuer_cik, signal.trigger_accession)
    return None


def signal_extras(signal: Signal) -> dict[str, Any]:
    """Fields added to every signal view: its source and, for the new types, card data."""
    source = source_of(signal.type)
    if source == INSIDERS:
        return {"source": INSIDERS, "facts": [], "tested": True}
    spec = SPECS[signal.type]
    extras: dict[str, Any] = {
        "source": source,
        "facts": _facts(signal),
        "direction": spec.direction,
        "tested": spec.primary_months is not None,
        "filing_url": _url(signal),
        "value": signal.details.get("total_value"),
    }
    if (people := _people(signal)) is not None:
        extras["insiders"] = people
        extras["n_insiders"] = len(people)
    return extras


def event_view(row: dict[str, Any]) -> dict[str, Any]:
    """One market event (a `SourceStore.event_row`) for the tape and the company context."""
    data = row.get("data") or {}
    fallback = row.get("title", "")
    return {
        "id": f"e{row['id']}",
        "source": row["source"],
        "kind": row["kind"],
        "date": row["date"],
        "cik": row.get("cik", ""),
        "company": row.get("company", ""),
        "ticker": row.get("ticker", ""),
        "symbol": normalize_symbol(row.get("ticker")),
        "title": localized(lambda lang: event_title(row["kind"], data, fallback, lang)),
        "data": data,
        "url": row.get("url"),
        "seen_at": row.get("seen_at"),
    }


def company_context(
    store: SourceStore, cik: str, ticker: str, *, today: date | None = None
) -> dict[str, Any]:
    """Everything the extra sources know about one company, newest first."""
    today = today or date.today()
    symbol = normalize_symbol(ticker)
    rows = store.company_events(
        cik, symbol, since=today - timedelta(days=max(CONTEXT_DAYS.values()))
    )
    by_source: dict[str, list[dict[str, Any]]] = {FORM144: [], EIGHTK: [], THIRTEENF: []}
    for row in rows:
        limit = CONTEXT_DAYS.get(row["source"])
        if limit is None or row["date"] < (today - timedelta(days=limit)).isoformat():
            continue
        by_source[row["source"]].append(event_view(row))
    interest = store.short_history(symbol, 6) if symbol else []
    volume = store.short_volume_history(symbol, 20) if symbol else []
    fails = store.fails_history(symbol, 20) if symbol else []
    return {
        "cik": cik,
        "symbol": symbol,
        FORM144: by_source[FORM144][:20],
        EIGHTK: by_source[EIGHTK][:20],
        THIRTEENF: by_source[THIRTEENF][:20],
        SHORT: {
            "interest": [
                {
                    "settlement_date": r["settlement_date"],
                    "short_shares": r["short_shares"],
                    "days_to_cover": r["days_to_cover"],
                    "avg_volume": r["avg_volume"],
                }
                for r in interest
            ],
            "volume": [
                {
                    "day": r["day"],
                    "ratio": r["short_volume"] / r["total_volume"] if r["total_volume"] else None,
                }
                for r in volume
            ],
            "fails": [
                {
                    "settlement_date": r["settlement_date"],
                    "quantity": r["quantity"],
                    "price": r["price"],
                }
                for r in fails
            ],
        },
    }
