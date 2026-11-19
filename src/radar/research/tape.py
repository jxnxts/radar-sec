"""SEC price tape: prices reported on Form 4s, a free point-in-time price source that exists for
every company whose insiders trade, listed or not.

Codes P and S are open-market trades, F is tax withholding (valued at the market close), and D
is a disposition to the issuer (at a merger close, the per-share consideration).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

MARKET_CODES = "PSF"


class SecTape:
    def __init__(self, frame: pd.DataFrame):
        """`frame`: issuer_cik, trans_date, code, price (one row per issuer, day and code)."""
        frame = frame.dropna(subset=["trans_date"]).copy()
        frame["trans_date"] = pd.to_datetime(frame["trans_date"]).to_numpy(dtype="datetime64[D]")
        frame = frame.sort_values(["issuer_cik", "trans_date"])
        self._by: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
        for (cik, code), group in frame.groupby(["issuer_cik", "code"], sort=False):
            self._by[(cik, code)] = (group["trans_date"].to_numpy(), group["price"].to_numpy(float))

    @classmethod
    def from_parquet(cls, path: Path) -> SecTape:
        frame = duckdb.sql(
            f"SELECT issuer_cik, trans_date, code, median(price) AS price FROM '{path}' "
            "WHERE trans_date IS NOT NULL GROUP BY ALL"
        ).df()
        return cls(frame)

    def _merged(self, cik: str, codes: str):
        parts = [self._by[(cik, code)] for code in codes if (cik, code) in self._by]
        if not parts:
            return None
        days = np.concatenate([p[0] for p in parts])
        prices = np.concatenate([p[1] for p in parts])
        order = np.argsort(days, kind="stable")
        return days[order], prices[order]

    def near(
        self, cik: str, day: date, *, before: int, after: int, codes: str = MARKET_CODES
    ) -> tuple[date, float] | None:
        """(closest tape date, median of every tape price in [day − before, day + after]).

        The median over the whole window is robust to a single mistyped price.
        """
        merged = self._merged(cik, codes)
        if merged is None:
            return None
        days, prices = merged
        target = np.datetime64(day, "D")
        lo = np.searchsorted(days, target - np.timedelta64(before, "D"))
        hi = np.searchsorted(days, target + np.timedelta64(after, "D"), side="right")
        if lo >= hi:
            return None
        window = days[lo:hi]
        closest = window[np.argmin(np.abs((window - target).astype(int)))]
        return pd.Timestamp(closest).date(), float(np.median(prices[lo:hi]))
