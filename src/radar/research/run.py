"""Phase 2 runs: build the pre-registered variants for a split, measure them, keep the numbers.

The splits and the pass criterion are fixed in research/phase2-plan.md. `run_split("test")`
refuses to run before the train parameters are frozen (`data/phase2/frozen_params.json`).
"""

from __future__ import annotations

import gzip
import json
import pickle
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from radar.backtest import datasets
from radar.backtest.runner import generate_signals
from radar.config import Settings
from radar.research.features import cooldown
from radar.research.measure import HORIZONS, Engine
from radar.research.outcomes import OutcomeBook
from radar.research.portfolio import event_stats, monthly_portfolio, newey_west_t, portfolio_stats
from radar.research.prices import PriceBook
from radar.research.tape import SecTape
from radar.research.text import PREVIOUS_GAP_DAYS, cosine, jaccard, rolling_quintiles
from radar.signals import BIG_OFFICER_BUY, CLUSTER_BUY

SPLITS = {
    "train": (date(2020, 1, 1), date(2022, 12, 31)),
    "test": (date(2023, 1, 1), date(2025, 12, 31)),
}
GRID = {"stake": (0.10, 0.20), "dip": (0.20, 0.30)}
DRAWDOWN_SESSIONS = 63

Say = Callable[[str], None]


@dataclass
class Paths:
    root: Path  # data/phase2

    def __getattr__(self, name: str) -> Path:  # trades, tape, owners, subs, text, ...
        files = {
            "trades": "trades.parquet",
            "tape": "tape.parquet",
            "owners": "owners.parquet",
            "subs": "subs",
            "text": "text",
            "prices": "prices.duckdb",
            "base": "base_filings.pkl",
            "csuite": "csuite_events.pkl",
            "tenk": "tenk_filings.pkl",
            "similarity": "similarity.pkl",
            "deals": "deal_prices.json",
            "frozen": "frozen_params.json",
        }
        if name in files:
            return self.root / files[name]
        raise AttributeError(name)


def load_engine(paths: Paths, extra_price_stores: list[Path]) -> tuple[Engine, Engine, np.ndarray]:
    book = PriceBook([paths.prices, *extra_price_stores])
    deals = json.loads(paths.deals.read_text()) if paths.deals.exists() else {}
    tape = SecTape.from_parquet(paths.tape)
    outcomes = OutcomeBook(paths.subs)
    engine = Engine(book, tape, outcomes, deal_prices={k: v for k, v in deals.items() if v})
    raw = Engine(book, tape, outcomes, correct=False)
    bill = book.get("^IRX")
    if bill is not None:
        idx = np.clip(
            np.searchsorted(bill.dates, engine.calendar, side="right") - 1, 0, len(bill) - 1
        )
        rf_daily = (bill.adj_close[idx] / 100) / 252
    else:
        rf_daily = np.zeros(len(engine.calendar))
    return engine, raw, rf_daily


def drawdown(book: PriceBook, ticker: str, day: date) -> float:
    """Adjusted-close return over the 63 sessions ending on the filing date (NaN without data)."""
    series = book.get(ticker)
    if series is None:
        return float("nan")
    j = int(np.searchsorted(series.dates, np.datetime64(day, "D"), side="right")) - 1
    if j < DRAWDOWN_SESSIONS or (np.datetime64(day, "D") - series.dates[j]).astype(int) > 7:
        return float("nan")
    return float(series.adj_close[j] / series.adj_close[j - DRAWDOWN_SESSIONS] - 1)


# --------------------------------------------------------------------- text signal
def similarities(paths: Paths) -> pd.DataFrame:
    """Similarity of each universe 10-K with the previous one, plus its rolling quintile."""
    if paths.similarity.exists():
        return pd.read_pickle(paths.similarity)
    filings = pd.read_pickle(paths.tenk)
    filings = filings[filings.in_universe & filings.prev_acc.notna()]

    def load(acc: str) -> dict | None:
        path = paths.text / f"{acc}.json.gz"
        if not path.exists():
            return None
        payload = json.loads(gzip.decompress(path.read_bytes()))
        return None if "error" in payload else payload

    rows = []
    for r in filings.itertuples(index=False):
        if not PREVIOUS_GAP_DAYS[0] <= (r.filing_date - r.prev_date).days <= PREVIOUS_GAP_DAYS[1]:
            continue
        now, before = load(r.acc), load(r.prev_acc)
        if not now or not before:
            continue
        a, b = Counter(now["tf"]), Counter(before["tf"])
        ra, rb = Counter(now["rf"]), Counter(before["rf"])
        rows.append(
            {
                "cik": r.cik,
                "ticker": r.ticker,
                "filing_date": r.filing_date,
                "acc": r.acc,
                "mcap": r.mcap,
                "sim_cos": cosine(a, b),
                "sim_jac": jaccard(a, b),
                "sim_rf": cosine(ra, rb) if ra and rb else np.nan,
                "words": now["words"],
            }
        )
    frame = pd.DataFrame(rows).sort_values("filing_date").reset_index(drop=True)
    frame["quintile"] = rolling_quintiles(frame.filing_date, frame.sim_cos)
    frame.to_pickle(paths.similarity)
    return frame


def latest_quintile(sim: pd.DataFrame):
    sim = sim.dropna(subset=["quintile"]).sort_values("filing_date")
    by_cik = {cik: (list(g.filing_date), list(g.quintile)) for cik, g in sim.groupby("cik")}

    def lookup(cik: str, day: date) -> float:
        if cik not in by_cik:
            return float("nan")
        days, quintiles = by_cik[cik]
        i = bisect_right(days, day) - 1  # 10-K filed on or before the signal date
        return quintiles[i] if i >= 0 and (day - days[i]).days <= 400 else float("nan")

    return lookup


# ------------------------------------------------------------------------ variants
def _dates(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    for column in columns:
        frame[column] = pd.to_datetime(frame[column]).dt.date
    return frame


def build_variants(
    paths: Paths,
    settings: Settings,
    client,
    current: dict[str, str],
    book: PriceBook,
    split: str,
    params: dict[str, tuple],
) -> dict[str, pd.DataFrame]:
    from radar.research.collect import ticker_for

    start, end = SPLITS[split]
    base = _dates(
        pd.read_pickle(paths.base).rename(columns={"issuer_cik": "cik"}),
        "filing_date",
        "last_trade",
    )
    base = base[(base.filing_date >= start) & (base.filing_date <= end)].copy()
    base["ticker"] = [ticker_for(current, c, s) for c, s in zip(base.cik, base.symbol, strict=True)]
    base["insider_price"] = base.avg_price
    base["drawdown"] = [
        drawdown(book, t, d) for t, d in zip(base.ticker, base.filing_date, strict=True)
    ]

    out = {
        "V0_insider_buy": base,
        "V1_opportunistic_buy": base[base.opportunistic],
        "V2_first_buy": base[base.first_buy],
    }
    for x in params["stake"]:
        out[f"V3_stake_jump@{x:.0%}"] = base[base.stake_inc >= x]
        out[f"V7_first_big_stake@{x:.0%}"] = base[base.first_buy & (base.stake_inc >= x)]
    for y in params["dip"]:
        out[f"V4_dip_buy@{y:.0%}"] = base[base.drawdown <= -y]
        out[f"V6_opportunistic_dip@{y:.0%}"] = base[base.opportunistic & (base.drawdown <= -y)]
    if paths.similarity.exists():
        lookup = latest_quintile(pd.read_pickle(paths.similarity))
        base["text_q"] = [lookup(c, d) for c, d in zip(base.cik, base.filing_date, strict=True)]
        out["V0_text_covered"] = base[base.text_q.notna()]
        out["V9_insider_buy_text_ok"] = base[base.text_q.notna() & (base.text_q != 1)]
    out = {name: cooldown(frame) for name, frame in out.items()}

    clusters = _dates(
        pd.read_pickle(paths.csuite).rename(columns={"issuer_cik": "cik"}),
        "filing_date",
        "last_trade",
    )
    clusters = clusters[(clusters.filing_date >= start) & (clusters.filing_date <= end)].copy()
    clusters["ticker"] = [
        ticker_for(current, c, s) for c, s in zip(clusters.cik, clusters.symbol, strict=True)
    ]
    clusters["insider_price"] = clusters.avg_price
    out["V5_csuite_cluster"] = clusters

    # phase-1 references, generated by the same rules the monitor uses
    first_day = datasets.warmup_start(
        start, settings.signals.cluster_window_days + settings.signals.cooldown_days
    )
    folders = [
        datasets.ensure_quarter(client, q, datasets.dataset_links(client))
        for q in datasets.quarters_between(first_day, end)
    ]
    filings, _ = datasets.load_purchase_filings(folders, first_day=first_day, last_day=end)
    signals = generate_signals(filings, settings, start, end)
    for name, kind in (("R1_cluster_buy", CLUSTER_BUY), ("R2_big_officer_buy", BIG_OFFICER_BUY)):
        rows = [
            {
                "cik": s.issuer_cik.zfill(10),
                "ticker": ticker_for(current, s.issuer_cik.zfill(10), s.ticker),
                "filing_date": s.signal_date,
                "insider_price": s.details.get("avg_price"),
                "last_trade": date.fromisoformat(s.details["last_buy"]),
            }
            for s in signals
            if s.type == kind
        ]
        out[name] = pd.DataFrame(rows)
    return out


def measure_variants(
    variants: dict[str, pd.DataFrame],
    engine: Engine,
    raw: Engine,
    rf_daily: np.ndarray,
    split: str,
    say: Say,
) -> tuple[dict, dict]:
    start, end = SPLITS[split]
    columns = ["cik", "ticker", "filing_date", "insider_price", "last_trade"]
    cache: dict[tuple, dict] = {}
    results, frames = {}, {}
    for name, events in variants.items():
        events = events.reset_index(drop=True)
        result: dict = {"generated": len(events)}
        for mode, eng in (("corrected", engine), ("raw", raw)):
            rows = []
            for r in events[columns].itertuples(index=False):
                key = (mode, *r)
                if key not in cache:
                    cache[key] = eng.measure_frame(pd.DataFrame([r._asdict()])).iloc[0].to_dict()
                rows.append(cache[key])
            measured = pd.DataFrame(rows, columns=None if rows else columns)
            if measured.empty:
                result[mode] = {"status": {}, "events": {}, "portfolio": {}, "by_year": {}}
                continue
            measured["year"] = [d.year for d in measured.filing_date]
            frames[(name, mode)] = measured
            block = {
                "status": measured.status.value_counts().to_dict(),
                "events": {h: event_stats(measured, h) for h in HORIZONS},
                "portfolio": {},
                "by_year": {},
            }
            for h in HORIZONS:
                table = monthly_portfolio(measured, eng, h, rf_daily, start, end)
                block["portfolio"][h] = portfolio_stats(table)
                if h == 3:
                    block["monthly_3m"] = (
                        table.reset_index().astype({"month": str}).to_dict("records")
                    )
            for year, group in measured.groupby("year"):
                block["by_year"][int(year)] = {h: event_stats(group, h) for h in HORIZONS}
            result[mode] = block
        results[name] = result
        p, e = result["corrected"]["portfolio"].get(3, {}), result["corrected"]["events"].get(3, {})
        nan = float("nan")
        say(
            f"  {name:28s} signals {len(events):5d}, measured {e.get('n', 0):5d}; "
            f"excess/month vs SPY {p.get('exc_spy', nan):+.4f} (t {p.get('t_spy', nan):+.2f}), "
            f"vs IWM {p.get('exc_iwm', nan):+.4f} (t {p.get('t_iwm', nan):+.2f})"
        )
    return results, frames


def lazy_prices(
    paths: Paths, engine: Engine, rf_daily: np.ndarray, split: str, say: Say
) -> tuple[dict, dict]:
    start, end = SPLITS[split]
    sim = similarities(paths)
    period = sim[
        (sim.filing_date >= start) & (sim.filing_date <= end) & sim.quintile.notna()
    ].copy()
    period["insider_price"] = None
    period["last_trade"] = None
    results: dict = {"universe": {}}
    for year, group in period.groupby(pd.to_datetime(period.filing_date).dt.year):
        results["universe"][int(year)] = {
            "filings": len(group),
            "companies": int(group.cik.nunique()),
        }
    measured = engine.measure_frame(
        period[["cik", "ticker", "filing_date", "insider_price", "last_trade"]].reset_index(
            drop=True
        )
    )
    measured["quintile"] = period.quintile.to_numpy()
    measured["year"] = [d.year for d in measured.filing_date]
    frames = {}
    for name, selected in (
        ("V8_lazy_nonchangers(Q5)", measured.quintile == 5),
        ("lazy_Q1_changers", measured.quintile == 1),
        ("lazy_all", measured.quintile.notna()),
    ):
        group = measured[selected]
        frames[name] = group
        block = {
            "generated": int(selected.sum()),
            "events": {h: event_stats(group, h) for h in HORIZONS},
            "portfolio": {},
        }
        for h in HORIZONS:
            table = monthly_portfolio(group, engine, h, rf_daily, start, end)
            block["portfolio"][h] = portfolio_stats(table)
            if h == 3:
                block["monthly_3m"] = table.reset_index().astype({"month": str}).to_dict("records")
        block["by_year"] = {
            int(y): {h: event_stats(g, h) for h in HORIZONS} for y, g in group.groupby("year")
        }
        results[name] = block
        p = block["portfolio"][3]
        say(
            f"  {name:28s} filings {int(selected.sum()):5d}; excess/month vs SPY "
            f"{p['exc_spy']:+.4f} (t {p['t_spy']:+.2f}), "
            f"vs IWM {p['exc_iwm']:+.4f} (t {p['t_iwm']:+.2f})"
        )
    top = pd.DataFrame(results["V8_lazy_nonchangers(Q5)"]["monthly_3m"]).set_index("month")
    bottom = pd.DataFrame(results["lazy_Q1_changers"]["monthly_3m"]).set_index("month")
    spread = (top.port - bottom.port).dropna()
    mean, t = newey_west_t(spread.to_numpy())
    results["spread_Q5_minus_Q1"] = {"mean_month": mean, "t": t, "months": int(len(spread))}
    return results, frames


def save(paths: Paths, name: str, results: dict, frames: dict) -> None:
    (paths.root / f"{name}.json").write_text(json.dumps(results, default=str, indent=1))
    with open(paths.root / f"{name}_frames.pkl", "wb") as handle:
        pickle.dump(frames, handle)


def frozen_params(paths: Paths) -> dict[str, tuple]:
    if not paths.frozen.exists():
        raise RuntimeError(
            "parameters are not frozen yet: run the train split and freeze them first"
        )
    frozen = json.loads(paths.frozen.read_text())
    return {"stake": (frozen["stake"],), "dip": (frozen["dip"],)}
