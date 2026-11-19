"""Backtest of the new signal sources, end to end: history → signals → prices → report.

Rules, periods and verdict criteria are the pre-registered ones in
research/new-signals-plan.md. No AI is used here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from radar import fmt
from radar.backtest.datasets import normalize_symbol, quarters_between
from radar.backtest.marketcap import SharesOutstanding
from radar.backtest.prices import PriceProvider, PriceStore
from radar.i18n import DEFAULT_LANG, LANGS, t
from radar.models import Signal

from . import evaluate as ev
from .eightk import rules as eightk_rules
from .eightk.history import load_filings
from .form144 import rules as form144_rules
from .form144.history import load_notices
from .registry import Registry
from .report import render, report_name
from .short import rules as short_rules
from .short.data import publication_date
from .short.history import FinraClient, build_cusip_map, load_fails, load_short_interest
from .specs import FORM144_PERIOD
from .thirteenf import rules as thirteenf_rules
from .thirteenf.history import dataset_links, load_history, zip_window

log = logging.getLogger(__name__)


@dataclass
class Collected:
    signals: list[Signal] = field(default_factory=list)
    funnel: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def collect(
    settings,
    client,
    start: date,
    end: date,
    registry: Registry,
    shares: SharesOutstanding,
    *,
    say: Callable[[str], None] = print,
    lang: str = DEFAULT_LANG,
) -> tuple[Collected, list]:
    out = Collected()
    cache = settings.cache_dir

    say(t("sources.cli.step.eightk", lang))
    filings, stats8k = load_filings(client, start - timedelta(days=95), end)
    eight = eightk_rules.detect(filings)
    for s in eight:
        s.ticker = registry.ticker_for(s.issuer_cik, s.ticker)
    eight = [s for s in eight if start <= s.signal_date <= end]
    out.signals += eight
    out.funnel["eightk"] = {
        "queries": stats8k.queries,
        "hits": stats8k.hits,
        "filings": len(filings),
        **stats8k.by_rule,
    }

    say(t("sources.cli.step.form144", lang))
    notices, stats144 = load_notices(
        client, FORM144_PERIOD[0] - timedelta(days=20), FORM144_PERIOD[1]
    )
    clusters = form144_rules.detect_clusters(notices)
    for s in clusters:
        s.ticker = registry.ticker_for(s.issuer_cik, s.ticker)
    clusters = [s for s in clusters if FORM144_PERIOD[0] <= s.signal_date <= FORM144_PERIOD[1]]
    out.signals += clusters
    out.funnel["form144"] = {
        "hits": stats144.hits,
        "notices": stats144.filings,
        "amendments": stats144.amendments,
        "unparsed": stats144.unparsed,
    }

    say(t("sources.cli.step.ftd", lang))
    cusips = build_cusip_map(cache)
    fails, ftd_files = load_fails(
        client,
        cache,
        start,
        end,
        registry.registrant,
        lambda cik, day: shares.as_of(cik, day),
        cusips,
    )
    out.signals += fails
    out.funnel["ftd"] = {"files": ftd_files, "cusips_mapped": len(cusips)}

    say(t("sources.cli.step.thirteenf", lang))

    def resolve(cusip: str, day: date):
        symbol = normalize_symbol(cusips.symbol(cusip))
        if not symbol:
            return None
        who = registry.registrant(symbol)
        return (symbol, who[0], who[2]) if who else (symbol, "", "")

    page = client.get_text(
        "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets", max_age=7 * 86_400
    )
    paths = []
    for link in dataset_links(page):
        window = zip_window(link)
        if window and window[1] >= date(2019, 10, 1) and window[0] <= end + timedelta(days=60):
            paths.append(client.download("https://www.sec.gov" + link))
    history = load_history(
        paths,
        resolve,
        first_period=thirteenf_rules.quarter_end(start - timedelta(days=60)),
        last_period=thirteenf_rules.quarter_end(end - timedelta(days=60)),
        progress=lambda name: say(f"    {name}"),
    )
    consensus = [s for s in history.consensus if start <= s.signal_date <= end]
    notable = [s for s in history.notable if start <= s.signal_date <= end]
    out.signals += consensus + notable
    out.funnel["thirteenf"] = {
        "reports_read": history.reports_read,
        "quarters": len(history.quarters),
        "active_filers_median": int(pd.Series([q.active_filers for q in history.quarters]).median())
        if history.quarters
        else 0,
        "unmapped_top": sum(q.unmapped for q in history.quarters),
    }

    say(t("sources.cli.step.short", lang))
    finra = FinraClient(cache)
    try:
        short = load_short_interest(finra, start, end, registry.registrant)
    finally:
        finra.close()
    out.signals += short.crowded
    out.funnel["short"] = {
        "settlement_dates": short.settlement_dates,
        "squeeze_candidates": len(short.squeeze_candidates),
    }
    return out, short.squeeze_candidates


def run(
    settings,
    client,
    start: date = date(2020, 1, 1),
    end: date = date(2025, 12, 31),
    *,
    provider: PriceProvider | None = None,
    today: date | None = None,
    langs: tuple[str, ...] = LANGS,
    say: Callable[[str], None] = print,
    lang: str = DEFAULT_LANG,
) -> dict[str, Path]:
    """Collect, measure and write `reports/new-signals-<date>.md` (+ `.pt-BR.md`)."""
    today = today or date.today()
    registry = Registry.load(client)
    shares = SharesOutstanding.load(client, quarters_between(start - timedelta(days=500), end))
    collected, squeeze_pool = collect(
        settings, client, start, end, registry, shares, say=say, lang=lang
    )

    tickers = {s.ticker for s in collected.signals if s.ticker}
    tickers |= {who[1] for _, who in squeeze_pool if who[1]}
    tickers |= set(ev.BENCHMARKS)
    say(t("sources.cli.step.prices", lang, n=fmt.number(len(tickers), lang=lang)))
    store = PriceStore(settings.cache_dir / "prices.duckdb", provider)
    try:
        bt = settings.backtest
        report = store.ensure(
            sorted(tickers),
            start - timedelta(days=40),
            min(today, end + timedelta(days=200)),
            fetch_end=today,
            batch_size=bt.price_batch_size,
            pause=bt.price_batch_size / bt.price_requests_per_second,
            progress=lambda done, total: (
                say(f"    {done:,}/{total:,}") if done % 500 == 0 else None
            ),
        )
        prices = store.load(sorted(tickers))
    finally:
        store.close()
    say(
        t(
            "sources.cli.prices_done",
            lang,
            cached=fmt.number(report.cached, lang=lang),
            downloaded=fmt.number(report.downloaded, lang=lang),
            no_data=fmt.number(report.no_data, lang=lang),
            failed=len(report.failed),
        )
    )

    squeezes = short_rules.squeezes(
        squeeze_pool,
        publication_date,
        lambda ticker, day: ev.momentum(prices.get(ticker), day, short_rules.SQUEEZE_SESSIONS),
    )
    squeezes = [s for s in squeezes if start <= s.signal_date <= end]
    collected.signals += squeezes

    frame = ev.signals_frame(collected.signals)
    measured = ev.measure_frame(frame, prices, shares_as_of=lambda cik, day: shares.as_of(cik, day))
    stamp = today.isoformat()
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    measured.to_csv(
        reports_dir / f"new-signals-{stamp}-signals.csv", index=False, float_format="%.6f"
    )
    paths: dict[str, Path] = {}
    generated = datetime.now()
    for lang in langs:
        path = reports_dir / report_name(stamp, lang)
        path.write_text(
            render(measured, collected.funnel, start, end, generated, lang), encoding="utf-8"
        )
        paths[lang] = path
    return paths
