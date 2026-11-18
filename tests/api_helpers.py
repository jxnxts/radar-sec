"""Shared pieces for the dashboard tests: replay records and fake sources."""

from __future__ import annotations

import struct
from datetime import date

from radar.api.prices import Bar, Quote
from radar.backtest.replay import ReplayRecord


def record(
    day: str,
    *,
    kind: str = "cluster_buy",
    cik: str = "100",
    name: str = "Acme Corp",
    ticker: str = "ACME",
    value: float = 200_000.0,
    excess_6m: float | None = -0.10,
    sector: str = "Technology",
    accession: str | None = None,
    ticker_current: bool = True,
) -> ReplayRecord:
    """A minimal historical signal, in the replay file format."""
    accession = accession or f"0000000{cik}-20-{day.replace('-', '')[2:]}"
    details = {
        "insiders": [
            {"name": "DOE JANE", "role": "CEO", "value": value * 0.75},
            {"name": "Roe Richard", "role": "Director/Officer", "value": value * 0.25},
        ],
        "n_insiders": 2,
        "total_value": value,
        "shares": 10_000.0,
        "avg_price": value / 10_000,
        "first_buy": day,
        "last_buy": day,
        "has_ceo_cfo": True,
        "window_days": 14,
        "accessions": [accession],
    }
    if kind == "big_officer_buy":
        details = {
            "insider": "DOE JANE",
            "role": "CEO",
            "title": "Chief Executive Officer",
            "total_value": value,
            "shares": 10_000.0,
            "avg_price": value / 10_000,
            "first_buy": day,
            "last_buy": day,
            "stake_increase": 0.2,
            "accessions": [accession],
        }
    outcome: dict = {"status": "no_prices"}
    if excess_6m is not None:
        outcome = {
            "status": "ok",
            "entry_date": day,
            "entry_price": 20.0,
            "market_cap": 5e8,
            "horizons": {
                "1": {"exit_date": day, "ret": 0.01, "spy": 0.02, "excess": -0.01},
                "3": {"exit_date": day, "ret": 0.02, "spy": 0.04, "excess": -0.02},
                "6": {"exit_date": day, "ret": 0.05, "spy": 0.05 - excess_6m, "excess": excess_6m},
            },
        }
    return ReplayRecord(
        type=kind,
        date=date.fromisoformat(day),
        cik=cik,
        name=name,
        ticker=ticker,
        ticker_current=ticker_current,
        score=70.0,
        accession=accession,
        details=details,
        sector=sector,
        purchases=(
            {
                "date": day,
                "name": "DOE JANE",
                "role": "CEO",
                "shares": 7_500.0,
                "price": 20.0,
                "value": value * 0.75,
                "accession": accession,
            },
            {
                "date": day,
                "name": "Roe Richard",
                "role": "Director/Officer",
                "shares": 2_500.0,
                "price": 20.0,
                "value": value * 0.25,
                "accession": accession + "b",
            },
        ),
        outcome=outcome,
    )


class FakePrices:
    """A fixed price source that records what was asked."""

    name = "Test source"
    delay_minutes = 15

    def __init__(self) -> None:
        self.quote_calls: list[list[str]] = []
        self.history_calls: list[tuple[str, date, date]] = []
        self.fail = False
        self.bars: list[Bar] = [
            Bar("2020-01-02", 10.0, 11.0, 9.5, 10.5, 1000.0),
            Bar("2020-01-03", 10.5, 12.0, 10.0, 11.5, 1500.0),
        ]

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        self.quote_calls.append(list(symbols))
        if self.fail:
            raise RuntimeError("source is down")
        return {
            symbol: Quote(symbol, 100.0, 98.0, "2026-11-17T16:00:00-05:00", [98.0, 99.0, 100.0])
            for symbol in symbols
        }

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        self.history_calls.append((symbol, start, end))
        if self.fail:
            raise RuntimeError("source is down")
        return list(self.bars)


def png(width: int = 128, height: int = 128) -> bytes:
    """A PNG header with the given size (enough for the logo validation)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00" * 16
    )
