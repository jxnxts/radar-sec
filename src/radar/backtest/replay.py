"""Replay file: the backtest signals, with details and outcome, for the dashboard.

The backtest CSV has the returns but not each signal's details (who bought,
when, how much). This file joins both in one compressed JSON line per signal,
small enough to be versioned. The dashboard plays it back in REPLAY mode and
shows, on each signal, what happened next.

The records store English codes and keys; the explanation is not stored, since
it is rendered from the details in the viewer's language. Files written by the
first (Portuguese) version are upgraded on read.
"""

from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from radar import legacy
from radar.backtest.returns import OK, UNMEASURED
from radar.models import PurchaseFiling, Signal
from radar.signals import explain, purchase_role

REPLAY_SUFFIX = "-replay.jsonl.gz"
MAX_PURCHASE_ROWS = 24

SectorOf = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class ReplayRecord:
    """A historical signal ready for the dashboard."""

    type: str
    date: date
    cik: str
    name: str
    ticker: str  # ticker for prices (current SEC registry or the Form 4's)
    # True when the ticker is the company's current one in the SEC registry. The ticker
    # typed in an old Form 4 may belong to another company today.
    ticker_current: bool = False
    score: float = 0.0
    accession: str = ""
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    sector: str = ""
    purchases: tuple[dict[str, Any], ...] = ()
    outcome: dict[str, Any] = field(default_factory=dict)

    def to_signal(self) -> Signal:
        signal = Signal(
            type=self.type,
            dedupe_key=f"{self.type}:{self.cik}:{self.date.isoformat()}",
            issuer_cik=self.cik,
            issuer_name=self.name,
            ticker=self.ticker,
            signal_date=self.date,
            score=self.score,
            explanation=self.explanation,
            trigger_accession=self.accession,
            details=self.details,
        )
        if not signal.explanation:
            signal.explanation = explain(signal, "en")
        return signal


def purchase_rows(signal: Signal, filings: dict[str, PurchaseFiling]) -> list[dict[str, Any]]:
    """The purchases behind the signal, one row per Form 4 and day."""
    try:
        first = date.fromisoformat(signal.details.get("first_buy") or "")
    except ValueError:
        first = date.min
    rows: list[dict[str, Any]] = []
    for accession in signal.details.get("accessions") or [signal.trigger_accession]:
        filing = filings.get(accession)
        if filing is None:
            continue
        by_day: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for buy in filing.purchases:
            if first <= buy.date <= signal.signal_date:
                by_day[buy.date][0] += buy.shares
                by_day[buy.date][1] += buy.value
        for day, (shares, value) in sorted(by_day.items()):
            rows.append(
                {
                    "date": day.isoformat(),
                    "name": " / ".join(filing.owner_names[:2]),
                    "role": purchase_role(filing),
                    "shares": round(shares, 2),
                    "price": round(value / shares, 4) if shares else None,
                    "value": round(value, 2),
                    "accession": accession,
                }
            )
    rows.sort(key=lambda r: (r["date"], -r["value"]))
    return rows[-MAX_PURCHASE_ROWS:]


def _number(value: Any, digits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else round(number, digits)


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value)
    return text[:10] if text else None


def outcome_from_row(row: dict[str, Any], horizons: Iterable[int]) -> dict[str, Any]:
    """Outcome measured by the backtest for one signal (a CSV row)."""
    outcome: dict[str, Any] = {"status": row.get("status") or UNMEASURED}
    if outcome["status"] != OK:
        return outcome
    outcome["entry_date"] = _text(row.get("entry_date"))
    outcome["entry_price"] = _number(row.get("entry_price"))
    outcome["market_cap"] = _number(row.get("market_cap"), 0)
    outcome["horizons"] = {
        str(months): {
            "exit_date": _text(row.get(f"exit_date_{months}m")),
            "ret": _number(row.get(f"ret_{months}m")),
            "spy": _number(row.get(f"spy_{months}m")),
            "excess": _number(row.get(f"excess_spy_{months}m")),
        }
        for months in horizons
    }
    return outcome


def build_records(
    signals: list[Signal],
    measured: pd.DataFrame,
    filings: Iterable[PurchaseFiling],
    *,
    horizons: Iterable[int] = (1, 3, 6),
    sector_of: SectorOf | None = None,
) -> list[ReplayRecord]:
    """Joins each signal with the purchases behind it and with the measured outcome."""
    horizons = tuple(horizons)
    by_accession = {f.accession: f for f in filings}
    rows = {(row["type"], row["accession"]): row for row in measured.to_dict("records")}
    sectors: dict[str, str] = {}
    records: list[ReplayRecord] = []
    for signal in signals:
        row = rows.get((signal.type, signal.trigger_accession), {})
        if sector_of is not None and signal.issuer_cik not in sectors:
            sectors[signal.issuer_cik] = sector_of(signal.issuer_cik)[1]
        ticker = row.get("ticker")
        records.append(
            ReplayRecord(
                type=signal.type,
                date=signal.signal_date,
                cik=signal.issuer_cik,
                name=signal.issuer_name,
                ticker=ticker if isinstance(ticker, str) else "",
                ticker_current=row.get("ticker_source") == "sec_current",
                score=signal.score,
                accession=signal.trigger_accession,
                details=signal.details,
                sector=sectors.get(signal.issuer_cik, ""),
                purchases=tuple(purchase_rows(signal, by_accession)),
                outcome=outcome_from_row(row, horizons),
            )
        )
    records.sort(key=lambda r: (r.date, r.type, r.cik))
    return records


def write_replay(path: Path, records: Iterable[ReplayRecord]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # mtime=0 keeps the file identical between runs with the same data.
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as sink:
        for record in records:
            line = {
                "type": record.type,
                "date": record.date.isoformat(),
                "cik": record.cik,
                "name": record.name,
                "ticker": record.ticker,
                "ticker_current": record.ticker_current,
                "score": record.score,
                "accession": record.accession,
                "details": record.details,
                "sector": record.sector,
                "purchases": list(record.purchases),
                "outcome": record.outcome,
            }
            sink.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode())
            sink.write(b"\n")
            count += 1
    return count


def read_replay(path: Path) -> Iterator[ReplayRecord]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            kind = item["type"]
            yield ReplayRecord(
                type=kind,
                date=date.fromisoformat(item["date"]),
                cik=item.get("cik", ""),
                name=item.get("name", ""),
                ticker=item.get("ticker", ""),
                ticker_current=bool(item.get("ticker_current", False)),
                score=float(item.get("score", 0)),
                accession=item.get("accession", ""),
                details=legacy.upgrade_details(kind, item.get("details", {})),
                sector=legacy.sector(item.get("sector", "")) or "",
                purchases=tuple(legacy.upgrade_purchase_rows(item.get("purchases", []))),
                outcome=legacy.upgrade_outcome(item.get("outcome", {})),
            )


def latest_replay(reports_dir: Path) -> Path | None:
    """The latest replay file in the reports folder."""
    files = sorted(reports_dir.glob(f"backtest-*{REPLAY_SUFFIX}"))
    return files[-1] if files else None
