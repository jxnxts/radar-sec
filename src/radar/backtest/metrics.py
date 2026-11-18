"""Statistics of the measured signals."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def t_stat(values: pd.Series) -> float:
    values = values.dropna()
    if len(values) < 3:
        return float("nan")
    spread = values.std(ddof=1)
    if not spread or math.isnan(spread):
        return float("nan")
    return float(values.mean() / (spread / math.sqrt(len(values))))


def winsorized_mean(values: pd.Series, lower: float = 0.01, upper: float = 0.99) -> float:
    values = values.dropna()
    if values.empty:
        return float("nan")
    low, high = values.quantile(lower), values.quantile(upper)
    return float(values.clip(low, high).mean())


def horizon_stats(frame: pd.DataFrame, months: int, benchmark: str) -> dict:
    """Numbers for one horizon. `ret_*` is already net of cost; `excess_*` = net − index."""
    net = frame[f"ret_{months}m"]
    excess = frame[f"excess_{benchmark}_{months}m"]
    valid = net.notna() & excess.notna()
    net, excess = net[valid], excess[valid]
    if net.empty:
        return {"n": 0}
    # One number per signal month: signals of the same month rise and fall together,
    # so the independent evidence is the number of months, not the number of signals.
    cohorts = excess.groupby(frame.loc[valid, "cohort"]).mean()
    return {
        "n": int(len(net)),
        "hit_rate": float((net > 0).mean()),
        "beats": float((excess > 0).mean()),
        "mean": float(net.mean()),
        "median": float(net.median()),
        "std": float(net.std(ddof=1)) if len(net) > 1 else float("nan"),
        "worst": float(net.min()),
        "best": float(net.max()),
        "bench_mean": float(frame.loc[valid, f"{benchmark}_{months}m"].mean()),
        "excess_mean": float(excess.mean()),
        "excess_median": float(excess.median()),
        "excess_winsor": winsorized_mean(excess),
        "t_naive": t_stat(excess),
        "t_cohort": t_stat(cohorts),
        "months": int(len(cohorts)),
    }


def summarize(
    frame: pd.DataFrame, horizons: tuple[int, ...], benchmark: str, by: str = "type"
) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(by, sort=True):
        for months in horizons:
            rows.append({by: key, "horizon": months, **horizon_stats(group, months, benchmark)})
    return pd.DataFrame(rows)


# Verdict codes for one horizon, from worst to best.
NO_DATA = "no_data"
NO_BEAT = "no_beat"  # mean and median of the excess are negative or zero
NO_BEAT_MEAN = "no_beat_mean"  # only the median is positive
CONCENTRATED = "concentrated"  # mean above the index, median below
WEAK = "weak"  # mean and median above, without statistical significance
BEATS = "beats"


def verdict_for(stats: dict) -> str:
    """Classifies one horizon (a verdict code). Deliberately conservative criterion."""
    if not stats.get("n"):
        return NO_DATA
    mean, median, t = stats["excess_mean"], stats["excess_median"], stats["t_cohort"]
    if mean <= 0 and median <= 0:
        return NO_BEAT
    if mean <= 0:
        return NO_BEAT_MEAN
    if median <= 0:
        return CONCENTRATED
    if np.isnan(t) or t < 2:
        return WEAK
    return BEATS
