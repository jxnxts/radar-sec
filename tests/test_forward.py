"""Forward-test log: append-only daily partitions, the price snapshot and the summary CLI."""

from __future__ import annotations

import gzip
import sqlite3
from datetime import UTC, date, datetime

import pandas as pd
from typer.testing import CliRunner

from radar.cli import app
from radar.forward import SNAPSHOT_STATE, ForwardLog, ForwardRecorder, signal_record
from radar.models import Signal
from radar.sources.base import MarketEvent
from radar.sources.store import SourceStore

DAY = date(2026, 11, 19)  # a Thursday


def _at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _record(seen: datetime, key: str, kind: str = "news", source: str = "prnewswire") -> dict:
    return {"kind": kind, "source": source, "key": key, "seen_at": seen.isoformat(), "data": {}}


def test_records_go_to_the_partition_of_their_seen_at_day(tmp_path):
    log_ = ForwardLog(tmp_path / "forward")
    assert log_.append([_record(_at(23, 59), "a"), _record(_at(0, 1, date(2026, 11, 20)), "b")])
    assert log_.days() == [DAY, date(2026, 11, 20)]
    assert [r["key"] for r in log_.read(DAY)] == ["a"]
    assert [r["key"] for r in log_.read(date(2026, 11, 20))] == ["b"]
    assert next(log_.read(DAY))["v"] == 1
    assert (tmp_path / "forward" / "2026-11-19.jsonl.gz").exists()


def test_appending_never_rewrites_what_is_there(tmp_path):
    log_ = ForwardLog(tmp_path)
    log_.append([_record(_at(10), "a")])
    before = log_.partition(DAY).read_bytes()
    log_.append([_record(_at(11), "b"), _record(_at(12), "c")])
    after = log_.partition(DAY).read_bytes()
    assert after.startswith(before)  # old bytes untouched; a new gzip member at the end
    assert [r["key"] for r in log_.read(DAY)] == ["a", "b", "c"]
    # Standard tools read the multi-member file as one stream.
    assert gzip.decompress(after).decode().count("\n") == 3


def test_a_truncated_last_write_is_skipped(tmp_path):
    log_ = ForwardLog(tmp_path)
    log_.append([_record(_at(10), "a")])
    log_.append([_record(_at(11), "b")])
    path = log_.partition(DAY)
    path.write_bytes(path.read_bytes()[:-7])  # a crash in the middle of the last write
    assert [r["key"] for r in log_.read(DAY)] == ["a"]


def test_records_without_seen_at_are_refused(tmp_path):
    log_ = ForwardLog(tmp_path)
    try:
        log_.append([{"kind": "news", "source": "x", "key": "k"}])
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    assert log_.days() == []


def test_summary_counts_per_source_and_day(tmp_path):
    log_ = ForwardLog(tmp_path)
    log_.append(
        [
            _record(_at(10), "a"),
            _record(_at(11), "b"),
            _record(_at(12), "c", "event", "news"),
            _record(_at(9, day=date(2026, 11, 18)), "d", "signal", "eightk"),
        ]
    )
    summary = log_.summary()
    assert summary[DAY] == {"news:prnewswire": 2, "event:news": 1}
    assert summary[date(2026, 11, 18)] == {"signal:eightk": 1}
    assert list(log_.summary(since=DAY)) == [DAY]


def _signal(kind: str = "buyback_8k") -> Signal:
    return Signal(
        type=kind,
        dedupe_key=f"{kind}:1:2026-11-19",
        issuer_cik="1",
        issuer_name="ACME",
        ticker="ACME",
        signal_date=DAY,
        score=60.0,
        explanation="x",
        trigger_accession="0000000001-26-000001",
        details={"items": ["8.01"]},
        summary="AI text",
    )


def test_signal_and_event_records(tmp_path):
    record = signal_record(_signal(), _at(15), alerted=True)
    assert record["kind"] == "signal" and record["source"] == "eightk"
    assert record["data"]["direction"] == "long" and record["data"]["fresh"] is True
    assert "summary" not in record["data"]
    assert signal_record(_signal("cluster_buy"), _at(15), alerted=False)["source"] == "insiders"

    log_ = ForwardLog(tmp_path)
    recorder = ForwardRecorder(log_, now=lambda: _at(15))
    recorder.signal(_signal(), alerted=True)
    event = MarketEvent(
        source="eightk",
        kind="8k",
        key="acc-1",
        event_date=DAY,
        issuer_cik="1",
        ticker="ACME",
        title="8-K",
        seen_at=_at(15, 1),
    )
    recorder.events([(7, event)])
    rows = list(log_.read(DAY))
    assert [r["kind"] for r in rows] == ["signal", "event"]
    assert rows[1]["data"]["id"] == 7 and rows[1]["seen_at"] == "2026-11-19T15:01:00+00:00"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE signals (ticker TEXT, signal_date TEXT)")
    conn.executemany(
        "INSERT INTO signals VALUES (?, ?)",
        [("ACME", "2026-11-10"), ("OLD", "2025-01-01"), ("BRK.B", "2026-11-01")],
    )
    store = SourceStore(conn)
    store.add_event(
        MarketEvent(
            source="news",
            kind="news",
            key="k1",
            event_date=DAY,
            ticker="NEWZ",
            title="t",
        )
    )
    return conn


def test_daily_price_snapshot_runs_once_after_the_close(tmp_path):
    now = [_at(20)]
    asked: list[list[str]] = []

    def fetch(symbols, start, end):
        asked.append(symbols)
        index = pd.to_datetime(["2026-11-18", "2026-11-19"])
        frame = pd.DataFrame(
            {"close": [10.0, 11.0], "adj_close": [9.9, 10.9], "split": [0.0, 0.0]}, index=index
        )
        return {s: frame for s in symbols if s != "NEWZ"}, {"NEWZ": "no data"}

    conn = _db()
    log_ = ForwardLog(tmp_path)
    recorder = ForwardRecorder(
        log_,
        conn=conn,
        benchmarks=("SPY", "IWM"),
        fetch_closes=fetch,
        now=lambda: now[0],
        background=False,
    )
    assert not recorder.maybe_snapshot()  # before 21:00 UTC
    now[0] = _at(21, 5)
    assert recorder.maybe_snapshot()
    assert asked == [["SPY", "IWM", "ACME", "BRK-B", "NEWZ"]]
    prices = [r for r in log_.read(DAY) if r["kind"] == "price"]
    symbols = [r["data"].get("symbol") for r in prices if not r["data"].get("snapshot")]
    assert symbols == ["SPY", "IWM", "ACME", "BRK-B"]
    assert prices[0]["data"] == {
        "symbol": "SPY",
        "day": "2026-11-19",
        "close": 11.0,
        "adj_close": 10.9,
        "split": 0.0,
        "source": "yahoo",  # a frame without a source tag counts as Yahoo
    }
    summary = prices[-1]["data"]
    assert summary["snapshot"] and summary["missing"] == ["NEWZ"] and summary["recorded"] == 4
    assert summary["sources"] == {"yahoo": 4}
    assert SourceStore(conn).get_state(SNAPSHOT_STATE) == "2026-11-19"

    now[0] = _at(23)
    assert not recorder.maybe_snapshot()  # once a day
    # A new recorder (after a restart) reads the state and does not repeat it either.
    again = ForwardRecorder(
        log_, conn=conn, fetch_closes=fetch, now=lambda: now[0], background=False
    )
    assert not again.maybe_snapshot()
    assert len(asked) == 1


def test_no_snapshot_on_weekends_and_a_failed_one_is_retried(tmp_path):
    saturday = date(2026, 11, 21)
    now = [_at(22, day=saturday)]
    calls = []

    def broken(symbols, start, end):
        calls.append(1)
        raise RuntimeError("Yahoo is down")

    recorder = ForwardRecorder(
        ForwardLog(tmp_path),
        conn=_db(),
        fetch_closes=broken,
        now=lambda: now[0],
        background=False,
    )
    assert not recorder.maybe_snapshot()
    now[0] = _at(22)
    assert recorder.maybe_snapshot() and calls == [1]
    assert recorder.maybe_snapshot() and calls == [1, 1]  # not marked done: retried


def test_forward_summary_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    empty = runner.invoke(app, ["forward-summary"])
    assert empty.exit_code == 0 and "Nothing recorded yet" in empty.output

    log_ = ForwardLog(tmp_path / "data" / "forward")
    log_.append([_record(_at(10), "a"), _record(_at(11), "b", "event", "news")])
    result = runner.invoke(app, ["forward-summary", "--days", "3"])
    assert result.exit_code == 0, result.output
    assert "2026-11-19" in result.output and "news:prnewswire" in result.output
    assert "2 records over 1 day(s)" in result.output
    pt = runner.invoke(app, ["forward-summary", "--lang", "pt-BR"])
    assert "2 registros em 1 dia(s)" in pt.output
