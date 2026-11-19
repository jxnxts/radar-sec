"""The pre-registered verdict rule, the phase-2 report and its dashboard summary."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from radar.config import Settings
from radar.research.report import Results, render, summary, verdict, write_reports


def result(median_spy, median_iwm, exc_spy, t_spy, exc_iwm, t_iwm, n=100, months=36):
    events = {
        "n": n,
        "median_spy": median_spy,
        "median_iwm": median_iwm,
        "n_corrected": 0,
        "mean_net": 0.01,
        "beats_spy": 0.5,
    }
    port = {
        "months": months,
        "exc_spy": exc_spy,
        "t_spy": t_spy,
        "exc_iwm": exc_iwm,
        "t_iwm": t_iwm,
        "alpha_spy": 0.0,
        "t_alpha_spy": 0.0,
        "alpha_iwm": 0.0,
        "t_alpha_iwm": 0.0,
        "avg_positions": 50.0,
    }
    block = {
        "events": {h: events for h in ("1", "3", "6")},
        "portfolio": {h: port for h in ("1", "3", "6")},
        "by_year": {},
    }
    return {"generated": n, "corrected": block, "raw": block}


GOOD = result(0.01, 0.01, 0.01, 2.5, 0.01, 2.1)
WEAK = result(0.01, 0.01, 0.004, 1.4, 0.004, 1.2)
BAD = result(-0.04, -0.02, -0.004, -0.8, 0.005, 2.3)


@pytest.mark.parametrize(
    ("train", "test", "expected"),
    [
        (BAD, GOOD, "use"),  # only the test split decides a pass
        (WEAK, WEAK, "maybe"),
        (BAD, WEAK, "discard"),  # "maybe" also needs a positive train portfolio
        (GOOD, BAD, "discard"),  # beats IWM with t 2.3, but not SPY and the median is negative
        (GOOD, result(0.01, 0.01, 0.01, 2.5, 0.01, 1.9), "maybe"),  # one benchmark only
    ],
)
def test_verdict_rule(train, test, expected):
    assert verdict("V1", {"V1": train}, {"V1": test})[0] == expected


def test_verdict_without_test_data():
    assert verdict("V1", {"V1": GOOD}, {}) == ("discard", "no test data")


@pytest.fixture
def results_dir(tmp_path):
    data = tmp_path / "data" / "phase2"
    data.mkdir(parents=True)
    train = {
        "V1_opportunistic_buy": WEAK,
        "V3_stake_jump@10%": WEAK,
        "V3_stake_jump@20%": WEAK,
        "R2_big_officer_buy": WEAK,
    }
    test = {"V1_opportunistic_buy": GOOD, "V3_stake_jump@20%": WEAK, "R2_big_officer_buy": BAD}
    (data / "train.json").write_text(json.dumps(train))
    (data / "test.json").write_text(json.dumps(test))
    (data / "frozen_params.json").write_text(json.dumps({"stake": 0.2, "dip": 0.3}))
    return tmp_path


def test_candidates_keep_only_the_frozen_parameters(results_dir):
    results = Results.load(results_dir / "data" / "phase2")
    assert results.candidates() == [
        "V1_opportunistic_buy",
        "V3_stake_jump@20%",
        "R2_big_officer_buy",
    ]


def test_report_and_summary(results_dir):
    data = results_dir / "data" / "phase2"
    text = render(data, "2026-01-01")
    assert "**1 variant(s) passed the pre-registered out-of-sample test**" in text
    assert "| V3 `stake_jump` (20%) |" in text
    assert "## Limitations" in text
    brief = summary(data, "2026-01-01")
    assert brief["passed"] == ["V1_opportunistic_buy"]
    assert [v["verdict"] for v in brief["variants"]] == ["use", "maybe", "discard"]
    assert brief["variants"][1]["key"] == "V3_stake_jump"
    assert brief["survivorship"] is None


def test_write_reports_needs_the_test_split(tmp_path, results_dir):
    settings = replace(Settings(), data_dir=tmp_path / "empty", reports_dir=tmp_path / "reports")
    with pytest.raises(RuntimeError):
        write_reports(settings)
    settings = replace(settings, data_dir=results_dir / "data")
    paths = write_reports(settings, "2026-01-01")
    assert [p.name for p in paths] == ["phase2-2026-01-01.md", "phase2-2026-01-01.json"]
    assert json.loads(paths[1].read_text())["passed"] == ["V1_opportunistic_buy"]
