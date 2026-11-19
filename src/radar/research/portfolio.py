"""Event statistics and calendar-time portfolios with Newey-West standard errors."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from radar.research.measure import HORIZONS, Engine

# Daily moves beyond these make a daily path unreliable (plan addendum e): with daily
# rebalancing, a one-day spike that reverts would add a gain that nobody could have earned.
MAX_DAILY_UP = 2.0
MAX_DAILY_DOWN = -0.75


def newey_west_t(values, lag: int = 3) -> tuple[float, float]:
    """(mean, t) of a series with Newey-West (Bartlett) standard errors."""
    x = np.asarray(values, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 6:
        return float("nan"), float("nan")
    mean = x.mean()
    e = x - mean
    s = e @ e / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    se = math.sqrt(s / n)
    return float(mean), float(mean / se) if se > 0 else float("nan")


def ols_newey_west(y, x, lag: int = 3) -> tuple[float, float, float]:
    """(alpha, beta, t of alpha) of y = alpha + beta·x, Newey-West covariance."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    n = len(y)
    if n < 8:
        return float("nan"), float("nan"), float("nan")
    X = np.column_stack([np.ones(n), x])
    inv = np.linalg.inv(X.T @ X)
    b = inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu / n
    for k in range(1, lag + 1):
        G = Xu[k:].T @ Xu[:-k] / n
        S += (1 - k / (lag + 1)) * (G + G.T)
    V = n * inv @ S @ inv
    return float(b[0]), float(b[1]), float(b[0] / math.sqrt(V[0, 0]))


def event_stats(frame: pd.DataFrame, months: int) -> dict:
    """Per-signal statistics of one horizon (net of costs)."""
    net = pd.to_numeric(frame[f"net_{months}m"], errors="coerce")
    ok = net.notna()
    out: dict = {"n": int(ok.sum())}
    if not ok.any():
        return out
    for bench in ("spy", "iwm"):
        excess = pd.to_numeric(frame.loc[ok, f"exc_{bench}_{months}m"], errors="coerce")
        low, high = excess.quantile(0.01), excess.quantile(0.99)
        out.update(
            {
                f"mean_{bench}": float(excess.mean()),
                f"median_{bench}": float(excess.median()),
                f"winsor_{bench}": float(excess.clip(low, high).mean()),
                f"beats_{bench}": float((excess > 0).mean()),
            }
        )
    how = frame.loc[ok, f"how_{months}m"].astype(str)
    out.update(
        {
            "mean_net": float(net[ok].mean()),
            "median_net": float(net[ok].median()),
            "hit": float((net[ok] > 0).mean()),
            "n_corrected": int(how.ne("yahoo").sum()),
        }
    )
    return out


def daily_paths(frame: pd.DataFrame, engine: Engine, months: int) -> tuple[np.ndarray, np.ndarray]:
    """Sum and count of the daily returns of the positions open on each trading day.

    Yahoo-measured positions follow their daily adjusted closes. Positions valued only at the
    start and the end (survivorship correction) get their total return spread evenly in log
    terms. The round-trip cost is charged on the first day.
    """
    calendar = engine.calendar
    total = np.zeros(len(calendar))
    count = np.zeros(len(calendar))
    for row in frame.itertuples(index=False):
        gross = getattr(row, f"gross_{months}m")
        if gross is None or (isinstance(gross, float) and math.isnan(gross)):
            continue
        a = int(np.searchsorted(calendar, np.datetime64(row.entry_date, "D")))
        b = int(np.searchsorted(calendar, np.datetime64(getattr(row, f"exit_{months}m"), "D")))
        if b <= a:
            continue
        returns = None
        if getattr(row, f"how_{months}m") == "yahoo":
            series = engine.prices.get(row.ticker)
            if series is not None:
                idx = np.clip(
                    np.searchsorted(series.dates, calendar[a : b + 1]), 0, len(series) - 1
                )
                closes = series.adj_close[idx]
                returns = closes[1:] / closes[:-1] - 1
                if returns.max(initial=0) > MAX_DAILY_UP or returns.min(initial=0) < MAX_DAILY_DOWN:
                    returns = None  # a Yahoo glitch (a spike that reverts): keep only the total
        if returns is None:
            step = math.log1p(max(gross, -0.9999)) / (b - a)
            returns = np.full(b - a, math.expm1(step))
        returns = returns.copy()
        returns[0] = (1 + returns[0]) * (1 - row.cost) - 1
        total[a + 1 : b + 1] += returns
        count[a + 1 : b + 1] += 1
    return total, count


def monthly_portfolio(
    frame: pd.DataFrame,
    engine: Engine,
    months: int,
    rf_daily: np.ndarray,
    start: date,
    end: date,
    min_positions: float = 5.0,
) -> pd.DataFrame:
    """Equal-weighted calendar portfolio, compounded into calendar months."""
    total, count = daily_paths(frame, engine, months)
    calendar = engine.calendar
    with np.errstate(invalid="ignore", divide="ignore"):
        port = np.where(count > 0, total / np.maximum(count, 1), np.nan)

    def daily(series) -> np.ndarray:
        idx = np.clip(np.searchsorted(series.dates, calendar), 0, len(series) - 1)
        closes = series.adj_close[idx]
        return np.r_[np.nan, closes[1:] / closes[:-1] - 1]

    days = pd.DataFrame(
        {
            "day": pd.to_datetime(calendar),
            "port": port,
            "n": count,
            "spy": daily(engine.spy),
            "iwm": daily(engine.iwm),
            "rf": rf_daily,
        }
    )
    days = days[(days.day >= pd.Timestamp(start)) & (days.day <= pd.Timestamp(end))]
    days["month"] = days.day.dt.to_period("M")

    def compound(values: pd.Series) -> float:
        values = values.dropna()
        return float(np.prod(1 + values) - 1) if len(values) else float("nan")

    table = days.groupby("month").agg(
        port=("port", compound),
        spy=("spy", compound),
        iwm=("iwm", compound),
        rf=("rf", compound),
        n=("n", "mean"),
    )
    table["kept"] = table.n >= min_positions
    return table


def portfolio_stats(table: pd.DataFrame, lag: int = 3) -> dict:
    kept = table[table.kept].dropna(subset=["port", "spy", "iwm"])
    out = {
        "months": int(len(kept)),
        "months_dropped": int((~table.kept).sum()),
        "avg_positions": float(kept.n.mean()) if len(kept) else float("nan"),
        "mean_month": float(kept.port.mean()) if len(kept) else float("nan"),
    }
    for bench in ("spy", "iwm"):
        mean, t = newey_west_t((kept.port - kept[bench]).to_numpy(), lag)
        alpha, beta, t_alpha = ols_newey_west(
            (kept.port - kept.rf).to_numpy(), (kept[bench] - kept.rf).to_numpy(), lag
        )
        out.update(
            {
                f"exc_{bench}": mean,
                f"t_{bench}": t,
                f"alpha_{bench}": alpha,
                f"beta_{bench}": beta,
                f"t_alpha_{bench}": t_alpha,
            }
        )
    return out


__all__ = [
    "HORIZONS",
    "event_stats",
    "monthly_portfolio",
    "newey_west_t",
    "ols_newey_west",
    "portfolio_stats",
]
