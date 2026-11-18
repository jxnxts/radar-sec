"""Replay file: joins signals, purchases and outcomes, and survives a round trip to disk."""

import gzip
import json
from datetime import date

import pandas as pd

from radar.backtest.replay import (
    build_records,
    latest_replay,
    outcome_from_row,
    purchase_rows,
    read_replay,
    write_replay,
)
from radar.config import SignalConfig
from radar.models import Purchase, PurchaseFiling
from radar.signals import detect_big_officer_buys, detect_cluster_buys


def filing(accession, owner, day, shares, price, *, ceo=False, title=""):
    return PurchaseFiling(
        accession=accession,
        issuer_cik="777",
        issuer_name="Acme Corp",
        ticker="ACME",
        filing_date=day,
        owner_ciks=frozenset({owner}),
        owner_names=(owner,),
        is_ceo=ceo,
        is_cfo=False,
        is_officer_or_director=True,
        officer_title=title,
        purchases=(Purchase(day, shares, price, shares * 3),),
        shares_after=shares * 3,
    )


FILINGS = [
    filing("a-1", "Jane Doe", date(2021, 3, 1), 10_000, 30.0, ceo=True, title="CEO"),
    filing("a-2", "Richard Roe", date(2021, 3, 3), 2_000, 31.0),
]
CFG = SignalConfig()


def measured_frame(signals):
    rows = []
    for signal in signals:
        row = {
            "type": signal.type,
            "accession": signal.trigger_accession,
            "ticker": "ACME",
            "ticker_source": "sec_current",
            "status": "ok",
            "entry_date": "2021-03-04",
            "entry_price": 31.5,
            "market_cap": float("nan"),
        }
        for months in (1, 3, 6):
            row |= {
                f"exit_date_{months}m": "2021-09-04",
                f"ret_{months}m": 0.1 * months,
                f"spy_{months}m": 0.05,
                f"excess_spy_{months}m": 0.1 * months - 0.05,
            }
        rows.append(row)
    return pd.DataFrame(rows)


def test_records_join_signal_purchases_and_outcome():
    signals = detect_cluster_buys(FILINGS, CFG) + detect_big_officer_buys(FILINGS, CFG)
    assert {s.type for s in signals} == {"cluster_buy", "big_officer_buy"}

    records = build_records(
        signals, measured_frame(signals), FILINGS, sector_of=lambda cik: ("2834", "Healthcare")
    )

    cluster = next(r for r in records if r.type == "cluster_buy")
    assert cluster.sector == "Healthcare" and cluster.ticker == "ACME" and cluster.ticker_current
    assert [(p["name"], p["value"]) for p in cluster.purchases] == [
        ("Jane Doe", 300_000.0),
        ("Richard Roe", 62_000.0),
    ]
    assert cluster.outcome["status"] == "ok" and cluster.outcome["market_cap"] is None
    assert cluster.outcome["horizons"]["6"] == {
        "exit_date": "2021-09-04",
        "ret": 0.6,
        "spy": 0.05,
        "excess": 0.55,
    }
    officer = next(r for r in records if r.type == "big_officer_buy")
    assert [p["name"] for p in officer.purchases] == ["Jane Doe"]  # only the CEO's Form 4


def test_unmeasured_signal_keeps_only_the_reason():
    assert outcome_from_row({"status": "no_prices"}, (1, 3, 6)) == {"status": "no_prices"}
    assert outcome_from_row({}, (1, 3, 6)) == {"status": "unmeasured"}


def test_purchase_rows_ignore_buys_outside_the_signal_window():
    signals = detect_cluster_buys(FILINGS, CFG)
    old = filing("a-0", "Jane Doe", date(2020, 1, 1), 1, 1.0)
    signals[0].details["accessions"].append("a-0")
    rows = purchase_rows(signals[0], {f.accession: f for f in [*FILINGS, old]})
    assert all(row["date"] >= "2021-03-01" for row in rows) and len(rows) == 2


def test_write_and_read_roundtrip(tmp_path):
    signals = detect_cluster_buys(FILINGS, CFG)
    records = build_records(signals, measured_frame(signals), FILINGS)
    path = tmp_path / "backtest-2026-01-01-replay.jsonl.gz"

    assert write_replay(path, records) == 1
    assert list(read_replay(path)) == records
    assert path.read_bytes() == (write_replay(path, records), path.read_bytes())[1]  # deterministic
    restored = next(read_replay(path)).to_signal()
    assert restored.type == "cluster_buy" and restored.signal_date == date(2021, 3, 3)
    assert restored.details["n_insiders"] == 2
    assert restored.explanation.startswith("2 distinct insiders bought")

    (tmp_path / "backtest-2025-06-30-replay.jsonl.gz").write_bytes(b"")
    assert latest_replay(tmp_path) == path
    assert latest_replay(tmp_path / "empty") is None


def test_records_store_english_codes_and_no_explanation(tmp_path):
    signals = detect_cluster_buys(FILINGS, CFG)
    path = tmp_path / "backtest-2026-01-01-replay.jsonl.gz"
    write_replay(path, build_records(signals, measured_frame(signals), FILINGS))
    line = json.loads(gzip.decompress(path.read_bytes()))
    assert "explanation" not in line
    assert {"total_value", "first_buy", "window_days"} <= set(line["details"])
    assert line["purchases"][1]["role"] == "Director/Officer"


def test_a_replay_file_from_the_first_version_is_upgraded_on_read(tmp_path):
    old = {
        "type": "cluster_buy",
        "date": "2021-03-03",
        "cik": "777",
        "name": "Acme Corp",
        "ticker": "ACME",
        "ticker_current": True,
        "score": 70.0,
        "accession": "a-2",
        "explanation": "2 insiders distintos compraram US$ 362 mil.",
        "details": {
            "insiders": [{"nome": "Jane Doe", "cargo": "diretor/executivo", "valor": 1.0}],
            "n_insiders": 2,
            "n_insiders_od": 2,
            "valor_total": 362_000.0,
            "acoes": 12_000.0,
            "preco_medio": 30.17,
            "primeira_compra": "2021-03-01",
            "ultima_compra": "2021-03-03",
            "tem_ceo_cfo": True,
            "accessions": ["a-1", "a-2"],
        },
        "sector": "Saúde",
        "purchases": [{"date": "2021-03-01", "name": "Jane Doe", "role": "dono de 10%+"}],
        "outcome": {"status": "sem_precos"},
    }
    path = tmp_path / "backtest-2021-01-01-replay.jsonl.gz"
    path.write_bytes(gzip.compress((json.dumps(old) + "\n").encode()))
    (record,) = read_replay(path)
    assert record.sector == "Healthcare"
    assert record.outcome == {"status": "no_prices"}
    assert record.purchases[0]["role"] == "10% owner"
    assert record.details["insiders"] == [
        {"name": "Jane Doe", "role": "Director/Officer", "value": 1.0}
    ]
    assert record.details["total_value"] == 362_000.0 and record.details["has_ceo_cfo"]
    assert record.to_signal().explanation.startswith("2 distinct insiders bought $362K")
