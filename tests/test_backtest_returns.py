"""Return measurement: entry and exit dates, cost, index and price check."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from radar.backtest.metrics import horizon_stats, t_stat, verdict_for, winsorized_mean
from radar.backtest.prices import PriceSeries, build_series
from radar.backtest.returns import (
    NO_ENTRY,
    NO_PRICES,
    OK,
    PRICE_MISMATCH,
    SUSPECT_JUMP,
    benchmark_return,
    first_session_after,
    measure,
)


def series(start: str, end: str, first: float = 100.0, daily: float = 0.0) -> PriceSeries:
    days = pd.bdate_range(start, end)
    prices = first * (1 + daily) ** np.arange(len(days))
    return build_series(days, prices, prices, np.zeros(len(days)))


CALENDAR = series("2023-01-02", "2024-06-28").dates


def test_entry_is_the_first_session_after_the_filing():
    # Filed on a Thursday: enters on Friday. Filed on Friday or Saturday: Monday.
    assert first_session_after(CALENDAR, date(2023, 3, 9)) == np.datetime64("2023-03-10")
    assert first_session_after(CALENDAR, date(2023, 3, 10)) == np.datetime64("2023-03-13")
    assert first_session_after(CALENDAR, date(2023, 3, 11)) == np.datetime64("2023-03-13")
    assert first_session_after(CALENDAR, date(2030, 1, 1)) is None


def test_measure_never_enters_on_the_filing_day_itself():
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    # Price jumps exactly on the filing day: whoever reads the filing already pays up.
    prices = np.where(days < pd.Timestamp("2023-03-09"), 10.0, 20.0)
    stock = build_series(days, prices, prices, np.zeros(len(days)))

    result = measure(stock, CALENDAR, date(2023, 3, 9), (1,))

    assert result.status == OK
    assert result.entry_date == date(2023, 3, 10)
    assert result.entry_price == 20.0  # does not capture the announcement-day rise
    assert result.returns[1] == pytest.approx(0.0)


def test_returns_at_one_three_and_six_months():
    stock = series("2023-01-02", "2024-06-28", first=50.0, daily=0.001)
    result = measure(stock, CALENDAR, date(2023, 3, 9), (1, 3, 6))

    assert result.entry_date == date(2023, 3, 10)
    assert result.exit_dates == {
        1: date(2023, 4, 10),
        3: date(2023, 6, 12),
        6: date(2023, 9, 11),  # Jun 10 and Sep 10 fall on weekends
    }
    for months, exit_day in result.exit_dates.items():
        sessions = len(pd.bdate_range(result.entry_date, exit_day)) - 1
        assert result.returns[months] == pytest.approx(1.001**sessions - 1)


def test_stock_delisted_before_the_exit_has_no_return_for_that_horizon():
    stock = series("2023-01-02", "2023-05-15")
    result = measure(stock, CALENDAR, date(2023, 3, 9), (1, 3, 6))
    assert result.status == OK
    assert set(result.returns) == {1}
    assert result.missing_exit == [3, 6]


def test_last_price_is_used_when_trading_stops_just_before_the_exit():
    # Stopped trading a few days before the exit: the last price is a good approximation.
    stock = series("2023-01-02", "2023-06-05", first=10.0, daily=0.001)
    result = measure(stock, CALENDAR, date(2023, 3, 9), (3,))
    assert result.exit_dates[3] == date(2023, 6, 5) and result.missing_exit == []


def test_no_prices_and_no_entry():
    assert measure(None, CALENDAR, date(2023, 3, 9), (1,)).status == NO_PRICES
    listed_later = series("2023-06-01", "2023-12-29")
    assert measure(listed_later, CALENDAR, date(2023, 3, 9), (1,)).status == NO_ENTRY
    already_gone = series("2023-01-02", "2023-02-15")
    assert measure(already_gone, CALENDAR, date(2023, 3, 9), (1,)).status == NO_ENTRY


def test_illiquid_stock_can_enter_a_few_days_late():
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    keep = (days < pd.Timestamp("2023-03-10")) | (days > pd.Timestamp("2023-03-14"))
    days = days[keep]
    stock = build_series(
        days, np.full(len(days), 5.0), np.full(len(days), 5.0), np.zeros(len(days))
    )
    result = measure(stock, CALENDAR, date(2023, 3, 9), (1,))
    assert result.status == OK and result.entry_date == date(2023, 3, 15)


def test_reported_price_far_from_the_market_discards_the_signal():
    stock = series("2023-01-02", "2023-12-29", first=10.0)
    args = (stock, CALENDAR, date(2023, 3, 9), (1,))
    typo = measure(*args, trade_date=date(2023, 3, 8), reported_price=15_000.0)
    assert typo.status == PRICE_MISMATCH and typo.price_ratio == pytest.approx(10 / 15_000)
    other_company = measure(*args, trade_date=date(2023, 3, 8), reported_price=1.0)
    assert other_company.status == PRICE_MISMATCH
    fine = measure(*args, trade_date=date(2023, 3, 8), reported_price=9.5)
    assert fine.status == OK and fine.price_ratio == pytest.approx(10 / 9.5)


def test_price_check_is_skipped_when_the_stock_was_not_trading_yet():
    # Bought in an offering, before the first session: nothing to compare with.
    stock = series("2023-03-09", "2023-12-29", first=10.0)
    result = measure(
        stock, CALENDAR, date(2023, 3, 9), (1,), trade_date=date(2023, 3, 1), reported_price=3.0
    )
    assert result.status == OK and result.price_ratio is None


def test_splits_are_undone_before_comparing_with_the_reported_price():
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    split_day = pd.Timestamp("2023-06-01")
    # 1-for-20 reverse split in June. Yahoo shows the past already multiplied by 20.
    yahoo_close = np.full(len(days), 30.0)
    splits = np.where(days == split_day, 0.05, 0.0)
    stock = build_series(days, yahoo_close, yahoo_close, splits)

    before = np.searchsorted(stock.dates, np.datetime64("2023-03-08"))
    after = np.searchsorted(stock.dates, np.datetime64("2023-06-01"))
    assert stock.raw_close[before] == pytest.approx(1.5)  # what the insider actually paid
    assert stock.raw_close[after] == pytest.approx(30.0)

    result = measure(
        stock, CALENDAR, date(2023, 3, 9), (1,), trade_date=date(2023, 3, 8), reported_price=1.5
    )
    assert result.status == OK and result.price_ratio == pytest.approx(1.0)


def step_series(first: float, factor: float, jump_day: str) -> PriceSeries:
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    prices = np.where(days < pd.Timestamp(jump_day), first, first * factor)
    return build_series(days, prices, prices, np.zeros(len(days)))


def test_unadjusted_reverse_split_is_discarded_instead_of_counted_as_a_gain():
    # Real case (COSM, Dec 2022): a 1-for-25 reverse split Yahoo did not record.
    # The series jumps from $0.33 to $23 overnight.
    fake_gain = step_series(0.33, 70.0, "2023-05-10")
    result = measure(fake_gain, CALENDAR, date(2023, 3, 9), (1, 3, 6))
    assert result.status == SUSPECT_JUMP
    assert result.jump == pytest.approx(70.0)
    assert result.returns == {}  # the 6,900% "gain" enters no statistic


def test_real_spikes_in_stocks_above_one_dollar_are_kept():
    # Real case (GLSI, Dec 2020): from $5.20 to $57 in one day, on news.
    real_gain = step_series(5.2, 11.0, "2023-05-10")
    result = measure(real_gain, CALENDAR, date(2023, 3, 9), (1, 3, 6))
    assert result.status == OK
    assert result.returns[3] == pytest.approx(10.0)


def test_jump_outside_the_holding_period_does_not_matter():
    before_entry = step_series(0.33, 70.0, "2023-02-01")
    after_exit = step_series(0.33, 70.0, "2023-11-01")
    for stock in (before_entry, after_exit):
        assert measure(stock, CALENDAR, date(2023, 3, 9), (1, 3, 6)).status == OK


def test_penny_noise_and_small_moves_are_not_jumps():
    doubled = step_series(0.33, 3.0, "2023-05-10")  # tripling is rare, but it happens
    assert measure(doubled, CALENDAR, date(2023, 3, 9), (6,)).status == OK
    sub_penny = step_series(0.0005, 50.0, "2023-05-10")  # worthless OTC quote
    assert measure(sub_penny, CALENDAR, date(2023, 3, 9), (6,)).status == OK
    crash = step_series(0.90, 0.02, "2023-05-10")  # a 98% drop is a real loss
    lost = measure(crash, CALENDAR, date(2023, 3, 9), (6,))
    assert lost.status == OK and lost.returns[6] == pytest.approx(-0.98)


def test_jump_filter_can_be_turned_off():
    fake_gain = step_series(0.33, 70.0, "2023-05-10")
    result = measure(fake_gain, CALENDAR, date(2023, 3, 9), (6,), jump_ratio=None)
    assert result.status == OK and result.returns[6] == pytest.approx(69.0)


def test_benchmark_is_measured_between_the_same_dates():
    spy = series("2023-01-02", "2024-06-28", first=400.0, daily=0.0005)
    value = benchmark_return(spy, date(2023, 3, 10), date(2023, 4, 10))
    sessions = len(pd.bdate_range("2023-03-10", "2023-04-10")) - 1
    assert value == pytest.approx(1.0005**sessions - 1)
    assert benchmark_return(spy, date(2023, 3, 10), date(2030, 1, 1)) is None


# ------------------------------------------------------------------ statistics


def frame(net: list[float], index: list[float], months: list[str] | None = None) -> pd.DataFrame:
    net_s, index_s = pd.Series(net), pd.Series(index)
    return pd.DataFrame(
        {
            "ret_3m": net_s,
            "spy_3m": index_s,
            "excess_spy_3m": net_s - index_s,
            "cohort": months or [f"2023-{i % 12 + 1:02d}" for i in range(len(net))],
        }
    )


def test_horizon_stats():
    stats = horizon_stats(frame([0.10, -0.05, 0.30, -0.20], [0.02, 0.02, 0.02, 0.02]), 3, "spy")
    assert stats["n"] == 4
    assert stats["hit_rate"] == 0.5
    assert stats["beats"] == 0.5
    assert stats["mean"] == pytest.approx(0.0375)
    assert stats["median"] == pytest.approx(0.025)
    assert stats["worst"] == -0.20 and stats["best"] == 0.30
    assert stats["excess_mean"] == pytest.approx(0.0175)
    assert stats["excess_median"] == pytest.approx(0.005)
    assert stats["bench_mean"] == pytest.approx(0.02)
    assert stats["std"] == pytest.approx(pd.Series([0.10, -0.05, 0.30, -0.20]).std())


def test_horizon_stats_ignores_signals_without_exit():
    stats = horizon_stats(frame([0.10, float("nan"), 0.30], [0.0, 0.0, 0.0]), 3, "spy")
    assert stats["n"] == 2 and stats["mean"] == pytest.approx(0.20)


def test_monthly_cohort_t_stat_does_not_reward_many_signals_in_one_month():
    # 200 great signals, all in the same month, plus two bad months.
    data = frame(
        [0.30] * 200 + [-0.10, -0.10],
        [0.0] * 202,
        ["2023-01"] * 200 + ["2023-02", "2023-03"],
    )
    stats = horizon_stats(data, 3, "spy")
    assert stats["t_naive"] > 20  # looks like certainty...
    assert (
        stats["t_cohort"] < 1 and stats["months"] == 3
    )  # ...but it is only three months of evidence


def test_winsorized_mean_tames_outliers():
    values = pd.Series([0.0] * 99 + [50.0])
    assert values.mean() == pytest.approx(0.5)
    assert winsorized_mean(values) < 0.01
    assert np.isnan(t_stat(pd.Series([0.1, 0.2])))


@pytest.mark.parametrize(
    ("stats", "code"),
    [
        ({"n": 0}, "no_data"),
        ({"n": 500, "excess_mean": -0.03, "excess_median": -0.05, "t_cohort": -3.0}, "no_beat"),
        ({"n": 500, "excess_mean": -0.01, "excess_median": 0.01, "t_cohort": -0.5}, "no_beat_mean"),
        ({"n": 500, "excess_mean": 0.04, "excess_median": -0.02, "t_cohort": 1.0}, "concentrated"),
        ({"n": 500, "excess_mean": 0.01, "excess_median": 0.005, "t_cohort": 0.8}, "weak"),
        ({"n": 500, "excess_mean": 0.04, "excess_median": 0.02, "t_cohort": 3.1}, "beats"),
    ],
)
def test_verdict_is_conservative(stats, code):
    assert verdict_for(stats) == code


def verdict_frame(excess_by_signal: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for signal, values in excess_by_signal.items():
        for i, value in enumerate(values):
            row = {"type": signal, "cohort": f"{2020 + i % 5}-{i % 12 + 1:02d}"}
            for months in (1, 3, 6):
                row |= {
                    f"ret_{months}m": value,
                    f"spy_{months}m": 0.0,
                    f"excess_spy_{months}m": value,
                }
            rows.append(row)
    return pd.DataFrame(rows)


def test_headline_says_no_when_only_a_few_big_winners_lift_the_average():
    from radar.backtest.report import build_verdict

    # Almost all lose 3% to the index; two extreme cases pull the mean up.
    mostly_losers = [-0.03] * 98 + [4.0, 5.0]
    frame = verdict_frame({"cluster_buy": mostly_losers, "big_officer_buy": [-0.02] * 100})
    lines = build_verdict(frame, (1, 3, 6), "spy")
    assert lines[0].startswith("**Conclusion: the signals do NOT beat SPY.**")
    assert "a few stocks" in lines[0]
    assert any("Mean above SPY, but the median is below" in line for line in lines)
    lines = build_verdict(frame, (1, 3, 6), "spy", "pt-BR")
    assert lines[0].startswith("**Conclusão: os sinais NÃO batem o SPY.**")
    assert "poucos papéis" in lines[0]
    assert any("Média acima do SPY, mas a mediana fica abaixo" in line for line in lines)


def test_headline_reports_evidence_only_when_it_is_statistically_solid():
    from radar.backtest.report import build_verdict

    steady_winners = [0.04 + 0.001 * (i % 7) for i in range(120)]
    lines = build_verdict(
        verdict_frame({"cluster_buy": steady_winners, "big_officer_buy": steady_winners}),
        (1, 3, 6),
        "spy",
    )
    assert "there is evidence of returns above SPY in 6 of 6" in lines[0]
    assert "(monthly cohort t = " in lines[2]
