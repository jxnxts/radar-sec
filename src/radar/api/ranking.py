"""Ranking of the companies and sectors with the most buying, in the shape the dashboard draws."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from radar.api.views import logo_url, price_symbol
from radar.sectors import SECTORS, UNKNOWN

WINDOWS = (7, 30)


def build_ranking(
    rows: Iterable[dict[str, Any]],
    *,
    days: int,
    as_of: date,
    basis: str,
    coverage_since: str | None = None,
    top: int = 8,
    max_blips: int = 80,
) -> dict[str, Any]:
    """`rows`: one dict per company with cik, name, ticker, sector, value, insiders,
    filings, last_date (ISO) and, optionally, logo_ok (False hides the logo).
    `basis` is a code: "open_market_buys" (live) or "replayed_signals" (replay)."""
    companies = sorted(rows, key=lambda r: -(r.get("value") or 0.0))
    total = sum(r.get("value") or 0.0 for r in companies)

    by_sector: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value": 0.0, "companies": 0, "insiders": 0}
    )
    for row in companies:
        bucket = by_sector[row.get("sector") or UNKNOWN]
        bucket["value"] += row.get("value") or 0.0
        bucket["companies"] += 1
        bucket["insiders"] += row.get("insiders") or 0

    def company(row: dict[str, Any]) -> dict[str, Any]:
        last = row.get("last_date") or as_of.isoformat()
        try:
            age = max(0, (as_of - date.fromisoformat(last[:10])).days)
        except ValueError:
            age = 0
        return {
            "cik": row.get("cik", ""),
            "ticker": row.get("ticker", ""),
            "symbol": price_symbol(row.get("ticker")),
            "name": row.get("name", ""),
            "sector": row.get("sector") or UNKNOWN,
            "value": round(row.get("value") or 0.0, 2),
            "insiders": row.get("insiders") or 0,
            "filings": row.get("filings") or 0,
            "last_date": last[:10],
            "age_days": age,
            "logo": logo_url(row.get("ticker")) if row.get("logo_ok", True) else None,
        }

    return {
        "days": days,
        "as_of": as_of.isoformat(),
        "basis": basis,
        "coverage_since": coverage_since,
        "total_value": round(total, 2),
        "total_companies": len(companies),
        "companies": [company(r) for r in companies[:top]],
        # Every sector, in the list's fixed order: the radar does not move on every event.
        "sectors": [
            {
                "sector": name,
                "value": round(by_sector[name]["value"], 2) if name in by_sector else 0.0,
                "companies": by_sector[name]["companies"] if name in by_sector else 0,
                "insiders": by_sector[name]["insiders"] if name in by_sector else 0,
                "share": (by_sector[name]["value"] / total) if total and name in by_sector else 0.0,
            }
            for name in SECTORS
        ],
        "blips": [company(r) for r in companies[:max_blips]],
    }
