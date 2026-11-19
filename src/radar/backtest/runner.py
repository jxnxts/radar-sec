"""End-to-end backtest: datasets → signals → prices → returns → report."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from rich.console import Console

from radar import legacy
from radar.backtest import datasets
from radar.backtest.datasets import LoadStats, Quarter
from radar.backtest.marketcap import SharesOutstanding
from radar.backtest.prices import PriceProvider, PriceSeries, PriceStore
from radar.backtest.replay import REPLAY_SUFFIX, build_records, write_replay
from radar.backtest.report import (
    ReportContext,
    build_verdict,
    quarter_label,
    render_report,
    report_name,
)
from radar.backtest.returns import NO_TICKER, OK, benchmark_return, measure
from radar.config import Settings
from radar.funds import FUND_EXCLUDED_TYPES, FundCheck, FundClassifier, split_funds
from radar.http import SecClient
from radar.i18n import DEFAULT_LANG, LANGS, t
from radar.models import PurchaseFiling, Signal
from radar.sectors import SectorLookup
from radar.signals import CLUSTER_BUY, detect_big_officer_buys, detect_cluster_buys
from radar.tickers import TickerMap

log = logging.getLogger(__name__)

SIGNALS_SUFFIX = "-signals.csv"
LEGACY_SIGNALS_SUFFIX = "-sinais.csv"  # name used by the first version

# Where the ticker used for prices came from.
SEC_CURRENT = "sec_current"
FORM4 = "form4"


@dataclass
class BacktestOutcome:
    report_path: Path
    csv_path: Path
    verdict: str
    signals: pd.DataFrame
    replay_path: Path | None = None
    report_paths: dict[str, Path] = field(default_factory=dict)  # by language


def generate_signals(
    filings: list[PurchaseFiling], settings: Settings, start: date, end: date
) -> list[Signal]:
    """Applies the monitor's rules to history and keeps the signals in the period."""
    signals = detect_cluster_buys(filings, settings.signals) + detect_big_officer_buys(
        filings, settings.signals
    )
    return sorted(
        (s for s in signals if start <= s.signal_date <= end),
        key=lambda s: (s.signal_date, s.type, s.issuer_cik),
    )


def fund_classifier(settings: Settings, sectors: SectorLookup) -> FundClassifier:
    """The live monitor's fund check, backed by the cached SEC registry lookups."""
    return FundClassifier(settings.signals, sectors.profile)


def count_by_type(signals: list[Signal]) -> dict[str, int]:
    counts = dict.fromkeys(sorted(FUND_EXCLUDED_TYPES), 0)
    for signal in signals:
        counts[signal.type] = counts.get(signal.type, 0) + 1
    return counts


def drop_fund_rows(frame: pd.DataFrame, is_fund: FundCheck) -> tuple[pd.DataFrame, dict[str, int]]:
    """Drops the rows of a measured signals CSV whose issuer is a fund (older CSVs had them)."""
    mask = [
        kind in FUND_EXCLUDED_TYPES and is_fund(str(cik or ""), str(issuer or ""))
        for kind, cik, issuer in zip(frame["type"], frame["cik"], frame["issuer"], strict=True)
    ]
    dropped = frame[mask]
    counts = dict.fromkeys(sorted(FUND_EXCLUDED_TYPES), 0)
    for kind, n in dropped.groupby("type").size().items():
        counts[str(kind)] = int(n)
    return frame[[not m for m in mask]].reset_index(drop=True), counts


def resolve_ticker(signal: Signal, current: dict[str, str]) -> tuple[str, str]:
    """Ticker to fetch prices for: the current one in the SEC registry, else the Form 4's."""
    if ticker := current.get(signal.issuer_cik, ""):
        return ticker.upper().replace(".", "-"), SEC_CURRENT
    if ticker := datasets.normalize_symbol(signal.ticker):
        return ticker, FORM4
    return "", ""


def signals_frame(signals: list[Signal], current_tickers: dict[str, str]) -> pd.DataFrame:
    rows = []
    for signal in signals:
        details = signal.details
        ticker, source = resolve_ticker(signal, current_tickers)
        rows.append(
            {
                "type": signal.type,
                "signal_date": signal.signal_date,
                "year": signal.signal_date.year,
                "cohort": signal.signal_date.strftime("%Y-%m"),
                "cik": signal.issuer_cik,
                "issuer": signal.issuer_name,
                "ticker": ticker,
                "ticker_source": source,
                "ticker_form4": signal.ticker,
                "score": signal.score,
                "total_value": details.get("total_value"),
                "n_insiders": details.get("n_insiders", 1),
                "n_officer_director": details.get("n_officer_director", 1),
                "avg_buy_price": details.get("avg_price"),
                "last_buy": date.fromisoformat(details["last_buy"]),
                "accession": signal.trigger_accession,
                "explanation": signal.explanation,
            }
        )
    return pd.DataFrame(rows)


def measure_signals(
    frame: pd.DataFrame,
    prices: dict[str, PriceSeries],
    settings: Settings,
) -> pd.DataFrame:
    """Adds status, entry and returns (gross, net, indices and excess) to each signal."""
    bt = settings.backtest
    benchmarks = [bt.benchmark, *bt.extra_benchmarks]
    calendar = prices[bt.benchmark].dates
    records: list[dict] = []
    for row in frame.itertuples(index=False):
        record: dict = {"status": NO_TICKER}
        if row.ticker:
            result = measure(
                prices.get(row.ticker),
                calendar,
                row.signal_date,
                bt.horizons_months,
                tolerance_days=bt.price_tolerance_days,
                trade_date=row.last_buy,
                reported_price=row.avg_buy_price,
                ratio_bounds=(bt.price_check_min_ratio, bt.price_check_max_ratio),
                jump_ratio=bt.price_jump_ratio,
                jump_below=bt.price_jump_below,
            )
            record = {
                "status": result.status,
                "entry_date": result.entry_date,
                "entry_price": result.entry_price,
                "market_price_ratio": result.price_ratio,
                "suspect_jump": result.jump,
            }
            for months, gross in result.returns.items():
                exit_day = result.exit_dates[months]
                record[f"exit_date_{months}m"] = exit_day
                record[f"gross_{months}m"] = gross
                record[f"ret_{months}m"] = gross - bt.cost_roundtrip
                for bench in benchmarks:
                    key = bench.lower()
                    index_return = benchmark_return(prices[bench], result.entry_date, exit_day)
                    record[f"{key}_{months}m"] = index_return
                    if index_return is not None:
                        record[f"excess_{key}_{months}m"] = gross - bt.cost_roundtrip - index_return
        records.append(record)

    measured = pd.DataFrame(records, index=frame.index)
    # Makes sure every column exists even when no signal reached a given horizon.
    for months in bt.horizons_months:
        for column in (f"exit_date_{months}m", f"gross_{months}m", f"ret_{months}m"):
            if column not in measured:
                measured[column] = None
        for bench in benchmarks:
            for column in (f"{bench.lower()}_{months}m", f"excess_{bench.lower()}_{months}m"):
                if column not in measured:
                    measured[column] = float("nan")
    for column in ("entry_date", "entry_price", "market_price_ratio", "suspect_jump"):
        if column not in measured:
            measured[column] = None
    return pd.concat([frame, measured], axis=1)


def add_market_cap(frame: pd.DataFrame, shares: SharesOutstanding) -> pd.DataFrame:
    outstanding = [shares.as_of(row.cik, row.signal_date) for row in frame.itertuples(index=False)]
    frame = frame.copy()
    frame["shares_outstanding"] = pd.Series(outstanding, index=frame.index, dtype="float64")
    frame["market_cap"] = frame["shares_outstanding"] * frame["avg_buy_price"]
    return frame


# ------------------------------------------------------------------ signals CSV


def write_signals_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.6f")


def read_signals_csv(path: Path) -> pd.DataFrame:
    """Reads a signals CSV, upgrading one written by the first (Portuguese) version."""
    frame = pd.read_csv(
        path, dtype={"cik": str, "ticker": str}, keep_default_na=False, na_values=[""]
    )
    if legacy.is_legacy_csv(list(frame.columns)):
        frame = frame.rename(columns=legacy.csv_column)
        frame["status"] = frame["status"].map(legacy.outcome_status)
        frame["ticker_source"] = frame["ticker_source"].replace(legacy.TICKER_SOURCE)
    frame["ticker"] = frame["ticker"].fillna("")
    return frame


def signals_csv_stamp(path: Path) -> str:
    """The date stamp of `backtest-<stamp>-signals.csv` (or of a legacy file name)."""
    name = path.name.removeprefix("backtest-")
    for suffix in (SIGNALS_SUFFIX, LEGACY_SIGNALS_SUFFIX):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return path.stem


def latest_signals_csv(reports_dir: Path) -> Path | None:
    found = sorted(reports_dir.glob(f"backtest-*{SIGNALS_SUFFIX}"))
    found = found or sorted(reports_dir.glob(f"backtest-*{LEGACY_SIGNALS_SUFFIX}"))
    return found[-1] if found else None


# --------------------------------------------------------------------- reports


def write_reports(
    context: ReportContext,
    reports_dir: Path,
    stamp: str,
    langs: tuple[str, ...] = LANGS,
) -> dict[str, Path]:
    """Writes the report in each language: `backtest-<stamp>.md` (English) and
    `backtest-<stamp>.pt-BR.md`. Returns the paths by language."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for lang in langs:
        path = reports_dir / report_name(stamp, lang)
        path.write_text(render_report(context, lang), encoding="utf-8")
        paths[lang] = path
    return paths


def plain_verdict(measured: pd.DataFrame, settings: Settings, lang: str = DEFAULT_LANG) -> str:
    bt = settings.backtest
    ok = measured[measured["status"] == OK]
    lines = build_verdict(ok, bt.horizons_months, bt.benchmark.lower(), lang)
    return "\n".join(lines).replace("**", "")


def _load_history(
    settings: Settings, client: SecClient, start: date, end: date
) -> tuple[date, list[Quarter], list[PurchaseFiling], LoadStats]:
    """Reads the purchase filings from the cached SEC datasets (downloading what is missing)."""
    sig = settings.signals
    # One extra quarter at the start "warms up" the window and cooldown of the first signal.
    first_day = datasets.warmup_start(start, sig.cluster_window_days + sig.cooldown_days)
    quarters = datasets.quarters_between(first_day, end)
    links = datasets.dataset_links(client)
    folders = [datasets.ensure_quarter(client, quarter, links) for quarter in quarters]
    filings, load = datasets.load_purchase_filings(folders, first_day=first_day, last_day=end)
    return first_day, quarters, filings, load


def run_backtest(
    settings: Settings,
    client: SecClient,
    start: date,
    end: date,
    *,
    console: Console | None = None,
    provider: PriceProvider | None = None,
    today: date | None = None,
    with_sectors: bool = True,
    langs: tuple[str, ...] = LANGS,
) -> BacktestOutcome:
    console = console or Console()
    today = today or date.today()
    bt = settings.backtest
    lang = settings.lang

    def say(key: str, **values: object) -> None:
        console.print(t(f"backtest.{key}", lang, **values), highlight=False)

    sig = settings.signals
    first_day = datasets.warmup_start(start, sig.cluster_window_days + sig.cooldown_days)
    quarters = datasets.quarters_between(first_day, end)
    say(
        "step.datasets",
        first=quarter_label(quarters[0], lang),
        last=quarter_label(quarters[-1], lang),
        n=len(quarters),
    )
    first_day, quarters, filings, load = _load_history(settings, client, start, end)
    say("loaded", form4=f"{load.form4_filings:,}", valid=f"{load.purchase_filings:,}")

    say("step.rules")
    sectors = SectorLookup(client)
    signals, funds = split_funds(
        generate_signals(filings, settings, start, end), fund_classifier(settings, sectors)
    )
    sectors.flush()
    excluded_funds = count_by_type(funds)
    say("excluded_funds", n=f"{len(funds):,}")
    frame = signals_frame(signals, TickerMap(client)._load())
    if frame.empty:
        raise RuntimeError("no signal generated in the period: check the dates and thresholds")
    counts = frame.groupby("type").size().to_dict()
    console.print("    " + ", ".join(f"{k}: {v:,}" for k, v in counts.items()))

    longest = max(bt.horizons_months)
    price_start = first_day - timedelta(days=10)
    price_end = min(
        today, (pd.Timestamp(end) + pd.DateOffset(months=longest)).date() + timedelta(days=20)
    )
    benchmarks = [bt.benchmark, *bt.extra_benchmarks]
    tickers = sorted({t for t in frame["ticker"] if t} | set(benchmarks))
    say("step.prices", n=f"{len(tickers):,}", start=price_start.isoformat())
    store = PriceStore(settings.cache_dir / "prices.duckdb", provider)
    try:
        last_shown = [-1]

        def progress(done: int, total: int) -> None:
            step = done * 10 // total if total else 10
            if step != last_shown[0]:
                last_shown[0] = step
                say("prices.progress", done=f"{done:,}", total=f"{total:,}")

        fetch = store.ensure(
            tickers,
            price_start,
            price_end,
            fetch_end=today,
            batch_size=bt.price_batch_size,
            pause=bt.price_batch_size / bt.price_requests_per_second,
            progress=progress,
        )
        prices = store.load(tickers)
    finally:
        store.close()
    say(
        "prices.done",
        cached=f"{fetch.cached:,}",
        downloaded=f"{fetch.downloaded:,}",
        no_data=f"{fetch.no_data:,}",
        failed=f"{len(fetch.failed):,}",
    )
    missing = [b for b in benchmarks if b not in prices]
    if missing:
        raise RuntimeError(f"no prices for the benchmark index: {', '.join(missing)}")

    say("step.returns")
    measured = measure_signals(frame, prices, settings)
    cap_quarters = datasets.quarters_between(first_day - timedelta(days=400), end)
    measured = add_market_cap(measured, SharesOutstanding.load(client, cap_quarters))
    ok = int((measured["status"] == OK).sum())
    say("measured", ok=f"{ok:,}", total=f"{len(measured):,}")

    say("step.report")
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.isoformat()
    csv_path = settings.reports_dir / f"backtest-{stamp}{SIGNALS_SUFFIX}"
    write_signals_csv(measured, csv_path)

    context = ReportContext(
        start=start,
        end=end,
        settings=settings,
        load=load,
        quarters=quarters,
        signals=measured,
        price_failures=len(fetch.failed),
        generated_at=datetime.now(),
        csv_name=csv_path.name,
        excluded_funds=excluded_funds,
    )
    report_paths = write_reports(context, settings.reports_dir, stamp, langs)

    # The dashboard plays these signals back in REPLAY mode. The sector costs one SEC
    # request per company the first time (then it comes from the cache).
    replay_path = settings.reports_dir / f"backtest-{stamp}{REPLAY_SUFFIX}"
    if with_sectors:
        say("sectors")
    records = build_records(
        signals,
        measured,
        filings,
        horizons=bt.horizons_months,
        sector_of=sectors.get if with_sectors else None,
    )
    sectors.flush()
    write_replay(replay_path, records)

    main_report = report_paths.get(lang) or next(iter(report_paths.values()))
    return BacktestOutcome(
        main_report,
        csv_path,
        plain_verdict(measured, settings, lang),
        measured,
        replay_path,
        report_paths,
    )


def rerender_reports(
    settings: Settings,
    client: SecClient,
    start: date,
    end: date,
    *,
    csv_path: Path,
    langs: tuple[str, ...] = LANGS,
    generated_at: datetime | None = None,
    console: Console | None = None,
) -> tuple[Path, dict[str, Path]]:
    """Writes the reports again from an already measured signals CSV, without prices.

    The datasets come from the local cache (they are only needed for the funnel
    numbers). A CSV from the first version is converted to the current columns and
    saved as `backtest-<stamp>-signals.csv`, with English explanations. Returns
    the CSV used and the report paths.
    """
    console = console or Console()
    stamp = signals_csv_stamp(csv_path)
    measured = read_signals_csv(csv_path)
    _, quarters, filings, load = _load_history(settings, client, start, end)
    sectors = SectorLookup(client)
    is_fund = fund_classifier(settings, sectors)

    target = settings.reports_dir / f"backtest-{stamp}{SIGNALS_SUFFIX}"
    if csv_path.resolve() != target.resolve() or "explanation" not in measured:
        signals = generate_signals(filings, settings, start, end)
        english = {(s.type, s.trigger_accession): s.explanation for s in signals}
        keys = zip(measured["type"], measured["accession"], strict=True)
        measured["explanation"] = [english.get(key, "") for key in keys]
        settings.reports_dir.mkdir(parents=True, exist_ok=True)
        write_signals_csv(measured, target)
        # The CSV's time is when the signals were measured: keep it on the converted copy.
        source = csv_path.stat()
        os.utime(target, (source.st_atime, source.st_mtime))
        console.print(t("backtest.csv_converted", settings.lang, path=target), highlight=False)
        measured = read_signals_csv(target)

    # A CSV written before the fund exclusion still has their signals: drop them here
    # too, so the report matches what the rules produce now.
    measured, excluded_funds = drop_fund_rows(measured, is_fund)
    sectors.flush()
    if generated_at is None:
        generated_at = datetime.fromtimestamp(csv_path.stat().st_mtime)
    context = ReportContext(
        start=start,
        end=end,
        settings=settings,
        load=load,
        quarters=quarters,
        signals=measured,
        generated_at=generated_at,
        csv_name=target.name,
        excluded_funds=excluded_funds,
    )
    return target, write_reports(context, settings.reports_dir, stamp, langs)


def rebuild_replay(
    settings: Settings,
    client: SecClient,
    start: date,
    end: date,
    *,
    csv_path: Path,
    console: Console | None = None,
    with_sectors: bool = True,
) -> Path:
    """Rebuilds only the replay file, from the dataset cache and an already measured CSV.

    For whoever already ran the backtest and does not want to download prices again.
    """
    console = console or Console()
    lang = settings.lang
    _, _, filings, _ = _load_history(settings, client, start, end)
    sectors = SectorLookup(client)
    signals, _ = split_funds(
        generate_signals(filings, settings, start, end), fund_classifier(settings, sectors)
    )
    measured = read_signals_csv(csv_path)
    console.print(
        t("backtest.replay_source", lang, n=f"{len(signals):,}", csv=csv_path.name),
        highlight=False,
    )
    if with_sectors:
        console.print(t("backtest.replay_sectors", lang), highlight=False)
    records = build_records(
        signals,
        measured,
        filings,
        horizons=settings.backtest.horizons_months,
        sector_of=sectors.get if with_sectors else None,
    )
    sectors.flush()
    path = settings.reports_dir / f"backtest-{signals_csv_stamp(csv_path)}{REPLAY_SUFFIX}"
    write_replay(path, records)
    return path


__all__ = [
    "BacktestOutcome",
    "CLUSTER_BUY",
    "generate_signals",
    "latest_signals_csv",
    "read_signals_csv",
    "rebuild_replay",
    "rerender_reports",
    "run_backtest",
]
