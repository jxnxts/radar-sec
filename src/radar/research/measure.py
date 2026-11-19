"""Measuring a phase-2 signal: Yahoo first, then the SEC-based survivorship correction.

Rules (research/phase2-plan.md, front 1 and addenda a–b):
- With Yahoo prices, the phase-1 measurement is used unchanged (entry at the close of the first
  session after the filing date, exit N months later). If the series stops before the exit,
  the company's terminal event (acquisition, bankruptcy, delisting) values the exit.
- Without Yahoo prices, the entry comes from the SEC price tape (or the insider's own price,
  scaled by the train-period drift), and the exit from the terminal event or from the tape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from radar.backtest.prices import PriceSeries
from radar.backtest.returns import OK, SUSPECT_JUMP, first_session_after, measure
from radar.research.outcomes import ACQUISITION, BANKRUPTCY, Outcome, OutcomeBook
from radar.research.prices import PriceBook
from radar.research.tape import SecTape

HORIZONS = (1, 3, 6)
COST = 0.002  # round trip
COST_PENNY = 0.01  # round trip below US$ 5
PENNY = 5.0
INSIDER_ENTRY_BIAS = 0.021  # addendum (b): median drift from the insider's price to the entry
TAPE_RATIO = (1 / 50, 20.0)  # tape returns outside this range are unit errors

OK_CORRECTED = "ok_corrected"
NO_TICKER = "no_ticker"


def cost_for(price: float | None) -> float:
    return COST_PENNY if price is not None and price < PENNY else COST


@dataclass
class Position:
    status: str
    source: str = ""  # yahoo | sec
    outcome: str = ""
    entry_date: date | None = None
    entry_price: float | None = None  # as traded (decides the cost tier)
    cost: float = COST
    gross: dict[int, float] = field(default_factory=dict)
    exit_date: dict[int, date] = field(default_factory=dict)
    how: dict[int, str] = field(default_factory=dict)  # how each exit was valued
    ticker: str = ""


def benchmark_return(series: PriceSeries, start: date, end: date) -> float | None:
    i = int(np.searchsorted(series.dates, np.datetime64(start, "D")))
    j = int(np.searchsorted(series.dates, np.datetime64(end, "D")))
    if i >= len(series) or j >= len(series):
        return None
    return float(series.adj_close[j] / series.adj_close[i] - 1)


def _within(ratio: float) -> bool:
    return TAPE_RATIO[0] < ratio < TAPE_RATIO[1]


class Engine:
    def __init__(
        self,
        prices: PriceBook,
        tape: SecTape,
        outcomes: OutcomeBook,
        *,
        correct: bool = True,
        deal_prices: dict[str, float] | None = None,
    ):
        self.prices, self.tape, self.outcomes, self.correct = prices, tape, outcomes, correct
        self.spy, self.iwm = prices.get("SPY"), prices.get("IWM")
        if self.spy is None or self.iwm is None:
            raise RuntimeError("phase 2 needs SPY and IWM prices")
        self.calendar = self.spy.dates
        self.deal_prices = dict(deal_prices or {})  # merger document accession -> cash per share

    # -------------------------------------------------------------------- one signal
    def position(
        self,
        cik: str,
        ticker: str,
        filing_date: date,
        insider_price: float | None,
        last_trade: date | None,
    ) -> Position:
        series = self.prices.get(ticker) if ticker else None
        m = None
        if ticker:
            m = measure(
                series,
                self.calendar,
                filing_date,
                HORIZONS,
                trade_date=last_trade,
                reported_price=insider_price,
            )
        if m is not None and m.status == SUSPECT_JUMP:
            return Position(SUSPECT_JUMP, ticker=ticker)
        if m is not None and m.status == OK:
            i = int(np.searchsorted(series.dates, np.datetime64(m.entry_date, "D")))
            raw = float(series.raw_close[i])
            pos = Position(
                OK,
                "yahoo",
                "",
                m.entry_date,
                raw,
                cost_for(raw),
                dict(m.returns),
                dict(m.exit_dates),
                {h: "yahoo" for h in m.returns},
                ticker,
            )
            if m.missing_exit and self.correct:
                self._fill_terminal(pos, cik, filing_date, m.missing_exit, series, raw)
            return pos
        status = m.status if m is not None else NO_TICKER
        if not self.correct:
            return Position(status, ticker=ticker)
        return self._sec_position(cik, filing_date, insider_price, status, ticker)

    def terminal_value(
        self, cik: str, outcome: Outcome, series: PriceSeries | None = None
    ) -> tuple[float | None, str]:
        """Value per share on the terminal date and how it was obtained."""
        end = outcome.terminal
        if outcome.kind == BANKRUPTCY:
            return 0.0, "bankruptcy"
        if series is not None and len(series):
            j = int(np.searchsorted(series.dates, np.datetime64(end, "D"), side="right")) - 1
            if j >= 0 and (np.datetime64(end, "D") - series.dates[j]).astype(int) <= 30:
                return float(series.raw_close[j]), "yahoo_last"
        if outcome.kind == ACQUISITION:
            disposal = self.tape.near(cik, end, before=15, after=5, codes="D")
            if disposal:
                return disposal[1], "merger_form4_d"
            if outcome.merger_doc and outcome.merger_doc[0] in self.deal_prices:
                return self.deal_prices[outcome.merger_doc[0]], "merger_doc_cash"
        last = self.tape.near(cik, end, before=30, after=0)
        if last:
            return last[1], "tape_last"
        return None, ""

    def _fill_terminal(
        self,
        pos: Position,
        cik: str,
        filing_date: date,
        horizons: list[int],
        series: PriceSeries,
        entry_raw: float,
    ) -> None:
        outcome = self.outcomes.outcome(cik, filing_date)
        pos.outcome = outcome.kind
        if outcome.terminal is None:
            return
        value, how = self.terminal_value(cik, outcome, series)
        if value is None:
            return
        for h in horizons:
            goal = (pd.Timestamp(pos.entry_date) + pd.DateOffset(months=h)).date()
            if outcome.terminal <= goal + timedelta(days=10):
                pos.gross[h] = value / entry_raw - 1
                pos.exit_date[h] = max(outcome.terminal, pos.entry_date)
                pos.how[h] = how

    def _sec_position(
        self, cik: str, filing_date: date, insider_price: float | None, status: str, ticker: str
    ) -> Position:
        first = first_session_after(self.calendar, filing_date)
        if first is None:
            return Position(status, ticker=ticker)
        entry_date = pd.Timestamp(first).date()
        tape_entry = self.tape.near(cik, filing_date + timedelta(days=1), before=0, after=5)
        if tape_entry:
            entry_price, entry_how = tape_entry[1], "tape"
        else:
            entry_price, entry_how = (
                (insider_price or 0) * (1 + INSIDER_ENTRY_BIAS),
                "insider_price",
            )
        if not entry_price:
            return Position(status, ticker=ticker)
        outcome = self.outcomes.outcome(cik, filing_date)
        pos = Position(
            status,
            "sec",
            outcome.kind,
            entry_date,
            entry_price,
            cost_for(entry_price),
            ticker=ticker,
        )
        value, value_how = self.terminal_value(cik, outcome) if outcome.terminal else (None, "")
        for h in HORIZONS:
            goal = (pd.Timestamp(entry_date) + pd.DateOffset(months=h)).date()
            ended = outcome.terminal is not None and outcome.terminal <= goal + timedelta(days=10)
            if ended and value is not None and (value == 0 or _within(value / entry_price)):
                pos.gross[h] = value / entry_price - 1
                pos.exit_date[h] = max(outcome.terminal, entry_date)
                pos.how[h] = f"{value_how}|entry:{entry_how}"
                continue
            if outcome.terminal is not None and outcome.terminal < goal - timedelta(days=10):
                continue  # ended before the horizon without a usable value: unmeasured
            point = self.tape.near(cik, goal, before=10, after=10)
            if point and _within(point[1] / entry_price):
                pos.gross[h] = point[1] / entry_price - 1
                pos.exit_date[h] = max(point[0], entry_date)
                pos.how[h] = f"tape|entry:{entry_how}"
        if pos.gross:
            pos.status = OK_CORRECTED
        return pos

    # ------------------------------------------------------------------------ table
    def measure_frame(self, events: pd.DataFrame) -> pd.DataFrame:
        """`events`: cik, ticker, filing_date, insider_price, last_trade (dates as `date`)."""
        rows = []
        for r in events.itertuples(index=False):
            pos = self.position(r.cik, r.ticker, r.filing_date, r.insider_price, r.last_trade)
            row = {
                "status": pos.status,
                "source": pos.source,
                "outcome": pos.outcome,
                "entry_date": pos.entry_date,
                "entry_price": pos.entry_price,
                "cost": pos.cost,
            }
            for h in HORIZONS:
                gross = pos.gross.get(h)
                net = None if gross is None else gross - pos.cost
                row.update(
                    {
                        f"exit_{h}m": pos.exit_date.get(h),
                        f"how_{h}m": pos.how.get(h, ""),
                        f"gross_{h}m": gross,
                        f"net_{h}m": net,
                    }
                )
                for name, series in (("spy", self.spy), ("iwm", self.iwm)):
                    bench = (
                        None
                        if gross is None
                        else benchmark_return(series, pos.entry_date, pos.exit_date[h])
                    )
                    row[f"{name}_{h}m"] = bench
                    row[f"exc_{name}_{h}m"] = None if bench is None or net is None else net - bench
            rows.append(row)
        measured = pd.DataFrame(rows, index=events.index)
        return pd.concat([events, measured], axis=1)
