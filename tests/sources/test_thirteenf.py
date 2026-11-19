from __future__ import annotations

from datetime import date

from radar.sources.thirteenf.history import dataset_links, zip_window
from radar.sources.thirteenf.holdings import Holding, Report, parse_submission, read_dataset
from radar.sources.thirteenf.rules import (
    FUND_CONSENSUS_13F,
    NOTABLE_FUND_NEW_13F,
    filing_deadline,
    first_reports,
    fund_consensus,
    notable_new_positions,
    previous_quarter_end,
    quarter_end,
)
from tests.conftest import FIXTURES

T13F = FIXTURES / "sources" / "thirteenf"


def test_reads_the_sec_data_set():
    reports = {r.accession: r for r in read_dataset(T13F / "2022q1_form13f_sample.zip")}
    pershing = reports["0001172661-22-000776"]
    assert pershing.cik == "1336528"
    assert pershing.manager.startswith("Pershing Square")
    assert pershing.period == date(2021, 12, 31)
    assert pershing.filing_date == date(2022, 2, 14)
    assert pershing.positions >= 5
    assert 0 < pershing.weight(next(iter(pershing.shares))) <= 1


def test_parses_a_live_13f_submission():
    report = parse_submission((T13F / "0001172661-26-002336.txt").read_text())
    assert report.accession == "0001172661-26-002336"
    assert report.period == date(2026, 3, 31)
    assert report.filing_date == date(2026, 5, 15)
    assert report.positions == len(report.shares) > 0
    assert "02079K305" in report.shares  # Alphabet class A
    assert report.total_value >= sum(report.values.values())


def test_new_position_between_two_real_filings():
    old = parse_submission((T13F / "0001172661-26-001091.txt").read_text(), cik="1336528")
    new = parse_submission((T13F / "0001172661-26-002336.txt").read_text(), cik="1336528")
    pair = first_reports([old, new])
    signals = notable_new_positions(pair, lambda cusip, day: (f"T{cusip[:3]}", "", "X"))
    opened = set(new.shares) - set(old.shares)
    expected = {c for c in opened if new.weight(c) >= 0.01}
    assert {s.details["cusip"] for s in signals} == expected
    assert all(s.type == NOTABLE_FUND_NEW_13F and s.signal_date == new.filing_date for s in signals)


def test_quarter_helpers():
    assert quarter_end(date(2024, 2, 10)) == date(2024, 3, 31)
    assert previous_quarter_end(date(2024, 3, 31)) == date(2023, 12, 31)
    assert previous_quarter_end(date(2024, 12, 31)) == date(2024, 9, 30)
    assert filing_deadline(date(2024, 3, 31)) == date(2024, 5, 15)
    assert filing_deadline(date(2026, 9, 30)) == date(2026, 11, 16)  # Saturday → Monday


def test_zip_windows_and_links():
    assert zip_window("2022q1_form13f.zip") == (date(2022, 1, 1), date(2022, 3, 31))
    assert zip_window("01mar2025-31may2025_form13f.zip") == (date(2025, 3, 1), date(2025, 5, 31))
    html = '<a href="/files/structureddata/data/form-13f-data-sets/2023q4_form13f.zip">x</a>'
    assert dataset_links(html) == [
        "/files/structureddata/data/form-13f-data-sets/2023q4_form13f.zip"
    ]


def _holding(cik: str, period: date, filed: date, cusips: list[str]) -> Holding:
    return Holding(f"{cik}-{period}", cik, period, filed, tuple(cusips))


def test_consensus_ranks_by_breadth_change_and_respects_the_deadline():
    q0, q1 = date(2023, 12, 31), date(2024, 3, 31)
    base = [f"C{i:08d}" for i in range(30)]
    reports = {}
    for i in range(25):
        held_before = base[:20]
        held_now = base[:20] + (["NEWSTOCK1"] if i < 15 else []) + (["C00000000"] if True else [])
        # "C00000025" gains 10 holders; it was held by 20 before (universe needs ≥ 20).
        before = held_before + ["C00000025"] * (1 if i < 20 else 0)
        now = held_now + ["C00000025"] * 1
        reports[(str(i), q0)] = _holding(str(i), q0, date(2024, 2, 1), sorted(set(before)))
        reports[(str(i), q1)] = _holding(str(i), q1, date(2024, 5, 1), sorted(set(now)))
    late = _holding("late", q1, date(2024, 5, 20), base[:25])
    reports[("late", q1)] = late
    reports[("late", q0)] = _holding("late", q0, date(2024, 2, 1), base[:25])

    signals, stats = fund_consensus(reports, q1, lambda c, d: (c[:4], "", c), top_n=3)
    assert stats.active_filers == 25  # the late filer is out
    assert signals[0].type == FUND_CONSENSUS_13F
    assert signals[0].details["cusip"] == "C00000025"  # 20 → 25 holders
    assert signals[0].signal_date == filing_deadline(q1)
    assert "NEWSTOCK1" not in {s.details["cusip"] for s in signals}  # not in the universe


def test_unmapped_cusips_stay_in_the_top_without_ticker():
    q0, q1 = date(2023, 12, 31), date(2024, 3, 31)
    cusips = [f"C{i:08d}" for i in range(25)]
    reports = {}
    for i in range(25):
        reports[(str(i), q0)] = _holding(str(i), q0, date(2024, 2, 1), cusips)
        reports[(str(i), q1)] = _holding(str(i), q1, date(2024, 5, 1), cusips)
    signals, stats = fund_consensus(reports, q1, lambda c, d: None, top_n=2)
    assert len(signals) == 2 and all(s.ticker == "" for s in signals)
    assert stats.unmapped == 2


def test_report_compact_keeps_cusips():
    r = Report("a", "1", "M", date(2024, 3, 31), date(2024, 5, 1), shares={"X": 1.0, "Y": 2.0})
    assert set(r.compact().cusips) == {"X", "Y"}
