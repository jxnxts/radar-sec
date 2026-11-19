"""`radar phase2` steps: collect → run train → freeze → run test → report.

All intermediate data lives in `data/phase2/` (ignored by git); the report and its JSON
summary go to `reports/`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from radar.config import Settings
from radar.http import RateLimiter, SecClient
from radar.research import collect, features
from radar.research.outcomes import OutcomeBook
from radar.research.prices import PriceBook, provider_by_name
from radar.research.run import (
    GRID,
    SPLITS,
    Paths,
    build_variants,
    frozen_params,
    lazy_prices,
    load_engine,
    measure_variants,
    save,
    similarities,
)
from radar.research.tape import SecTape

log = logging.getLogger(__name__)

SEC_RATE = 4.0  # requests per second for phase-2 downloads (the monitor keeps the rest)
LAST_DAY = date(2025, 12, 31)


def paths_for(settings: Settings) -> Paths:
    root = settings.data_dir / "phase2"
    root.mkdir(parents=True, exist_ok=True)
    return Paths(root)


def research_client(settings: Settings) -> SecClient:
    config = replace(settings.sec, requests_per_second=SEC_RATE)
    return SecClient(settings.cache_dir, config=config, limiter=RateLimiter(SEC_RATE))


def phase1_price_store(settings: Settings) -> Path:
    return settings.cache_dir / "prices.duckdb"


def collect_all(
    settings: Settings, client: SecClient, *, provider: str = "yahoo-chart", texts: bool = True
) -> None:
    paths = paths_for(settings)
    say = log.info
    say("insider datasets 2016Q4–2025Q4")
    folders = collect.insider_quarters(client, LAST_DAY)
    built = features.build_tables(folders, paths.root)
    say("base insider filings and c-suite clusters")
    features.base_filings(built["trades"], built["owners"]).to_pickle(paths.base)
    features.csuite_events(built["trades"], built["owners"]).to_pickle(paths.csuite)

    current = collect.current_tickers(client)
    issuers = collect.insider_issuers(built["trades"], built["owners"])
    ciks = sorted({cik for cik, _ in issuers} | set(current))
    collect.submissions(client, ciks, paths.subs, say)

    floats = collect.public_float(client, 2018, LAST_DAY.year)
    first = {"SPY", "IWM", "^IRX"} | {
        t for c, s in issuers if (t := collect.ticker_for(current, c, s))
    }
    second = {
        t for c, t in current.items() if floats.get(c, 0) >= collect.MIN_FLOAT_FOR_PRICES
    } - first
    collect.prices(
        paths.prices,
        [("insider issuers", first), ("large companies", second)],
        provider_by_name(provider),
        date.today(),
        say,
    )

    book = PriceBook([paths.prices, phase1_price_store(settings)])
    if texts:
        filings = collect.tenk_filings(client, current, paths.subs, book, LAST_DAY)
        filings.to_pickle(paths.tenk)
        collect.tenk_texts(client, filings, paths.text, say)

    base = pd.read_pickle(paths.base)
    clusters = pd.read_pickle(paths.csuite)
    pairs = set(zip(base.issuer_cik, pd.to_datetime(base.filing_date).dt.date, strict=True))
    pairs |= set(
        zip(clusters.issuer_cik, pd.to_datetime(clusters.filing_date).dt.date, strict=True)
    )
    collect.deal_prices(
        client, pairs, OutcomeBook(paths.subs), SecTape.from_parquet(paths.tape), paths.deals, say
    )


def run_split(settings: Settings, client: SecClient, split: str) -> dict:
    if split not in SPLITS:
        raise ValueError(f"unknown split '{split}' (train, test)")
    paths = paths_for(settings)
    params = GRID if split == "train" else frozen_params(paths)
    engine, raw, rf_daily = load_engine(paths, [phase1_price_store(settings)])
    current = collect.current_tickers(client)
    if paths.tenk.exists():
        similarities(paths)  # V9 filters on the latest 10-K quintile
    variants = build_variants(paths, settings, client, current, engine.prices, split, params)
    log.info("measuring %d variants (%s)", len(variants), split)
    results, frames = measure_variants(variants, engine, raw, rf_daily, split, log.info)
    save(paths, split, results, frames)
    if (paths.tenk).exists():
        lazy, lazy_frames = lazy_prices(paths, engine, rf_daily, split, log.info)
        save(paths, f"lazy_{split}", lazy, lazy_frames)
    return results


def freeze(settings: Settings, stake: float, dip: float) -> Path:
    """Records the train-chosen parameters; the test split refuses to run without them."""
    paths = paths_for(settings)
    if not (paths.root / "train.json").exists():
        raise RuntimeError("run the train split before freezing parameters")
    if stake not in GRID["stake"] or dip not in GRID["dip"]:
        raise ValueError("parameters must come from the pre-registered grid")
    paths.frozen.write_text(json.dumps({"stake": stake, "dip": dip}))
    return paths.frozen
