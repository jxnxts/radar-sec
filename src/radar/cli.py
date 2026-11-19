"""Command line: `radar watch`, `radar signals`, `radar backtest`, `radar serve`..."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from radar.config import ConfigError, Settings, load_settings
from radar.i18n import LANGS, normalize_lang, signal_label, t
from radar.signals import SIGNAL_TYPES as INSIDER_TYPES
from radar.sources.runner import build_runner
from radar.sources.specs import SPECS as SOURCE_SPECS

# Every type the radar stores: the insider rules plus the extra sources.
SIGNAL_TYPES = (*INSIDER_TYPES, *SOURCE_SPECS)

app = typer.Typer(
    help="radar-sec: monitors EDGAR filings, detects insider buying signals and measures them.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _setup(verbose: bool, config: Path | None, lang: str | None = None) -> Settings:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "yfinance", "peewee", "urllib3", "claude_agent_sdk"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        _fail(str(exc))
    if lang is not None:
        settings = replace(settings, lang=_lang(lang))
    return settings


def _lang(value: str) -> str:
    try:
        return normalize_lang(value)
    except ValueError as exc:
        _fail(str(exc))
        raise  # unreachable: _fail exits


def _fail(message: str) -> None:
    err_console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=2)


def _say(settings: Settings, key: str, **values: object) -> None:
    console.print(t(f"cli.{key}", settings.lang, **values), highlight=False)


def _dates(start: str, end: str) -> tuple[date, date]:
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        _fail("dates must be in the YYYY-MM-DD format.")
    if start_date >= end_date:
        _fail("--start must be before --end.")
    return start_date, end_date


ConfigOption = Annotated[
    Path | None, typer.Option("--config", help="Configuration file (default: radar.toml).")
]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-v", help="Show more details.")]
LangOption = Annotated[
    str | None,
    typer.Option("--lang", help=f"Output language ({', '.join(LANGS)}); overrides the config."),
]


@app.command()
def watch(
    once: Annotated[bool, typer.Option("--once", help="Run one cycle and exit.")] = False,
    interval: Annotated[
        int | None,
        typer.Option("--interval", min=10, help="Seconds between cycles (continuous loop)."),
    ] = None,
    alert: Annotated[
        list[str] | None,
        typer.Option("--alert", help="Alert channel (console, macos, telegram). Repeatable."),
    ] = None,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Template summaries only.")] = False,
    lang: LangOption = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Fetches new filings from the SEC, generates signals and sends alerts."""
    from radar.alerts import build_alerters
    from radar.db import Database
    from radar.http import SecClient
    from radar.summary import Summarizer
    from radar.watch import Watcher

    if once and interval is not None:
        _fail("use --once or --interval, not both.")
    settings = _setup(verbose, config, lang)
    if no_ai:
        settings = replace(settings, ai=replace(settings.ai, enabled=False))

    try:
        client = SecClient(settings.cache_dir, config=settings.sec)
    except ConfigError as exc:
        _fail(str(exc))

    with client, Database(settings.db_path) as db:
        watcher = Watcher(
            settings,
            db,
            client,
            build_alerters(alert, lang=settings.lang),
            Summarizer(db, settings.ai, lang=settings.lang),
            sources=build_runner(settings, db, client),
        )
        if once or interval is None:
            _cycle(watcher, settings)
            return
        _say(settings, "watching", interval=interval)
        try:
            while True:
                started = time.monotonic()
                try:
                    _cycle(watcher, settings)
                except Exception:  # a bad cycle does not bring the monitor down
                    logging.getLogger(__name__).exception("cycle failed; moving on to the next")
                time.sleep(max(1.0, interval - (time.monotonic() - started)))
        except KeyboardInterrupt:
            _say(settings, "stopped")


def _cycle(watcher, settings: Settings) -> None:
    lang = settings.lang
    result = watcher.run_once()
    stamp = datetime.now().strftime("%H:%M:%S")
    extras = []
    if result.backfilled:
        extras.append(t("cli.cycle.backfilled", lang, n=result.backfilled))
    if result.errors:
        extras.append(t("cli.cycle.errors", lang, n=result.errors))
    if result.stored_only:
        extras.append(t("cli.cycle.stored_only", lang, n=result.stored_only))
    if result.source_events:
        extras.append(t("cli.cycle.source_events", lang, n=result.source_events))
    suffix = f" ({'; '.join(extras)})" if extras else ""
    line = t(
        "cli.cycle",
        lang,
        new=result.new_filings,
        seen=result.seen,
        processed=result.processed,
        suffix=suffix,
    )
    console.print(f"[dim]{stamp}[/dim] {line}", highlight=False)
    if result.signals:
        _say(settings, "new_signals", n=len(result.signals))
    else:
        _say(settings, "no_new_signals")


@app.command()
def signals(
    since: Annotated[
        str, typer.Option("--since", help="Period: 7d, 24h, 2w, 3m or a date (YYYY-MM-DD).")
    ] = "7d",
    type_: Annotated[
        str | None, typer.Option("--type", help=f"Filter by type: {', '.join(SIGNAL_TYPES)}.")
    ] = None,
    full: Annotated[
        bool, typer.Option("--full", help="Show the full explanation and summary.")
    ] = False,
    lang: LangOption = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Lists the stored signals."""
    from radar.db import Database
    from radar.signals import explain
    from radar.summary import localized_summaries
    from radar.watch import parse_since

    settings = _setup(verbose, config, lang)
    lang = settings.lang
    try:
        cutoff = parse_since(since)
    except ValueError as exc:
        _fail(str(exc))
    if type_ and type_ not in SIGNAL_TYPES:
        _fail(f"unknown type: {type_}. Use one of: {', '.join(SIGNAL_TYPES)}.")
    if not settings.db_path.exists():
        _say(settings, "no_db")
        return

    with Database(settings.db_path) as db:
        rows = db.list_signals(since=cutoff, signal_type=type_)
        cached = (
            {s.dedupe_key: db.cached_ai_summaries(s.trigger_accession, s.type) for s in rows}
            if full
            else {}
        )
    if not rows:
        _say(settings, "none_since", date=cutoff.isoformat())
        return

    if full:
        for s in rows:
            console.rule(f"{s.signal_date.isoformat()} · {signal_label(s.type, lang)}")
            console.print(
                f"[bold]{s.issuer_name}[/bold] {s.ticker} · score {s.score:.0f}", highlight=False
            )
            console.print(explain(s, lang), highlight=False)
            if s.summary_source:
                texts, sources = localized_summaries(s, cached.get(s.dedupe_key))
                source = t(f"summary.source.{sources[lang]}", lang)
                console.print(
                    f"\n{texts[lang]}\n[dim]{t('cli.summary_source', lang, source=source)}[/dim]",
                    highlight=False,
                )
        return

    console.print(
        f"[bold]{t('cli.count_since', lang, n=len(rows), date=cutoff.isoformat())}[/bold]\n"
    )
    for s in rows:
        console.print(
            f"[bold]{s.signal_date.isoformat()}[/bold]  {s.type:<16} "
            f"[cyan]{s.ticker or '—':<6}[/cyan] score {s.score:>3.0f}  {s.issuer_name}",
            highlight=False,
        )
        console.print(f"    {explain(s, lang)}\n", highlight=False, style="dim")


@app.command()
def backtest(
    start: Annotated[str, typer.Option("--start", help="Start (YYYY-MM-DD).")] = "2020-01-01",
    end: Annotated[str, typer.Option("--end", help="End (YYYY-MM-DD).")] = "2025-12-31",
    output: Annotated[
        Path | None, typer.Option("--output", help="Reports folder (default: reports/).")
    ] = None,
    lang: Annotated[
        str,
        typer.Option(
            "--lang",
            help="Language of the console output and of the verdict shown at the end. "
            "The report is always written in every language (.md and .pt-BR.md).",
        ),
    ] = "en",
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Replays the rules over SEC history and measures the return against SPY."""
    from radar.backtest.runner import run_backtest
    from radar.http import SecClient

    settings = _setup(verbose, config, lang)
    start_date, end_date = _dates(start, end)
    if output is not None:
        settings = replace(settings, reports_dir=output)

    try:
        client = SecClient(settings.cache_dir, config=settings.sec)
    except ConfigError as exc:
        _fail(str(exc))

    try:
        with client:
            outcome = run_backtest(settings, client, start_date, end_date, console=console)
    except RuntimeError as exc:
        _fail(str(exc))
    console.print()
    for report_lang, path in outcome.report_paths.items():
        _say(settings, "report_path", lang=report_lang, path=path)
    _say(settings, "csv_path", path=outcome.csv_path)
    _say(settings, "replay_path", path=outcome.replay_path)
    console.print(f"\n{outcome.verdict}", highlight=False)


@app.command("backtest-sources")
def backtest_sources(
    start: Annotated[str, typer.Option("--start", help="Start (YYYY-MM-DD).")] = "2020-01-01",
    end: Annotated[str, typer.Option("--end", help="End (YYYY-MM-DD).")] = "2025-12-31",
    output: Annotated[
        Path | None, typer.Option("--output", help="Reports folder (default: reports/).")
    ] = None,
    lang: LangOption = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Backtests the extra sources (Form 144, 13F, 8-K, short data) with the pre-registered
    rules of research/new-signals-plan.md; writes reports/new-signals-<date>.md (+ .pt-BR.md)."""
    from radar.http import SecClient
    from radar.sources.backtest import run as run_sources

    settings = _setup(verbose, config, lang)
    start_date, end_date = _dates(start, end)
    if output is not None:
        settings = replace(settings, reports_dir=output)
    try:
        client = SecClient(settings.cache_dir, config=settings.sec)
    except ConfigError as exc:
        _fail(str(exc))
    with client:
        paths = run_sources(
            settings,
            client,
            start_date,
            end_date,
            lang=settings.lang,
            say=lambda message: console.print(message, highlight=False),
        )
    for report_lang, path in paths.items():
        _say(settings, "report_path", lang=report_lang, path=path)


@app.command()
def report(
    csv: Annotated[
        Path | None,
        typer.Option("--csv", help="Backtest signals CSV (default: the latest in reports/)."),
    ] = None,
    start: Annotated[str, typer.Option("--start", help="Start (YYYY-MM-DD).")] = "2020-01-01",
    end: Annotated[str, typer.Option("--end", help="End (YYYY-MM-DD).")] = "2025-12-31",
    lang: Annotated[
        str, typer.Option("--lang", help=f"Report language: {', '.join(LANGS)} or all.")
    ] = "all",
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Writes the backtest reports again from an existing signals CSV (no price downloads).

    The SEC datasets come from the local cache. A CSV from the first version
    (Portuguese columns) is converted to `backtest-<date>-signals.csv`.
    """
    from radar.backtest.runner import latest_signals_csv, rerender_reports
    from radar.http import SecClient

    settings = _setup(verbose, config)
    langs = LANGS if lang == "all" else (_lang(lang),)
    start_date, end_date = _dates(start, end)
    csv = csv or latest_signals_csv(settings.reports_dir)
    if csv is None:
        _fail("no signals CSV in reports/: run `radar backtest` first.")
    try:
        client = SecClient(settings.cache_dir, config=settings.sec)
    except ConfigError as exc:
        _fail(str(exc))
    try:
        with client:
            used, paths = rerender_reports(
                settings, client, start_date, end_date, csv_path=csv, langs=langs, console=console
            )
    except RuntimeError as exc:
        _fail(str(exc))
    for report_lang, path in paths.items():
        _say(settings, "report_path", lang=report_lang, path=path)
    _say(settings, "csv_path", path=used)


@app.command()
def serve(
    replay: Annotated[
        bool,
        typer.Option("--replay", help="Play back the historical backtest signals (demo)."),
    ] = False,
    host: Annotated[str, typer.Option("--host", help="Listen address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Server port.")] = 8000,
    interval: Annotated[
        int, typer.Option("--interval", min=10, help="LIVE: seconds between collection cycles.")
    ] = 60,
    alert: Annotated[
        list[str] | None,
        typer.Option("--alert", help="LIVE: alert channel besides the dashboard. Repeatable."),
    ] = None,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Template summaries only.")] = False,
    replay_start: Annotated[
        str | None,
        typer.Option("--replay-start", help="REPLAY: start date (YYYY-MM-DD)."),
    ] = None,
    replay_speed: Annotated[
        float,
        typer.Option("--replay-speed", min=0.1, help="REPLAY: simulated days per minute."),
    ] = 2.0,
    price_interval: Annotated[
        int, typer.Option("--price-interval", min=15, help="Seconds between price queries.")
    ] = 60,
    no_prices: Annotated[bool, typer.Option("--no-prices", help="Do not fetch quotes.")] = False,
    lang: LangOption = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Starts the dashboard: API, WebSocket and collection (or replay) in the background."""
    import uvicorn

    from radar.api.server import ServerOptions, build_app

    settings = _setup(verbose, config, lang)
    if no_ai:
        settings = replace(settings, ai=replace(settings.ai, enabled=False))
    start_date: date | None = None
    if replay_start:
        try:
            start_date = date.fromisoformat(replay_start)
        except ValueError:
            _fail("--replay-start must be in the YYYY-MM-DD format.")
    options = ServerOptions(
        replay=replay,
        interval=interval,
        alerts=alert,
        replay_start=start_date,
        replay_days_per_minute=replay_speed,
        price_interval=price_interval,
        prices=not no_prices,
    )
    try:
        application = build_app(settings, options)
    except (ConfigError, RuntimeError) as exc:
        _fail(str(exc))

    mode = t("cli.mode.replay" if replay else "cli.mode.live", settings.lang)
    _say(settings, "serve.title", mode=mode)
    _say(settings, "serve.api", host=host, port=port)
    if application.state.serves_panel:
        _say(settings, "serve.panel", host=host, port=port)
    else:
        _say(settings, "serve.panel_dev")
    uvicorn.run(application, host=host, port=port, log_level="warning")


@app.command("replay-build")
def replay_build(
    start: Annotated[str, typer.Option("--start", help="Start (YYYY-MM-DD).")] = "2020-01-01",
    end: Annotated[str, typer.Option("--end", help="End (YYYY-MM-DD).")] = "2025-12-31",
    csv: Annotated[
        Path | None,
        typer.Option("--csv", help="Backtest signals CSV (default: the latest one)."),
    ] = None,
    no_sectors: Annotated[
        bool, typer.Option("--no-sectors", help="Do not look up company sectors at the SEC.")
    ] = False,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Rebuilds the dashboard replay file from a backtest that already ran."""
    from radar.backtest.runner import latest_signals_csv, rebuild_replay
    from radar.http import SecClient

    settings = _setup(verbose, config)
    start_date, end_date = _dates(start, end)
    csv = csv or latest_signals_csv(settings.reports_dir)
    if csv is None:
        _fail("no signals CSV in reports/: run `radar backtest` first.")
    try:
        client = SecClient(settings.cache_dir, config=settings.sec)
    except ConfigError as exc:
        _fail(str(exc))
    try:
        with client:
            path = rebuild_replay(
                settings,
                client,
                start_date,
                end_date,
                csv_path=csv,
                console=console,
                with_sectors=not no_sectors,
            )
    except RuntimeError as exc:
        _fail(str(exc))
    _say(settings, "replay_path", path=path)


if __name__ == "__main__":
    app()


# ------------------------------------------------------------------- phase 2 research

phase2_app = typer.Typer(
    help="Phase 2 research: survivorship correction, selective insider variants, 10-K text "
    "change and calendar portfolios (see research/phase2-plan.md).",
    no_args_is_help=True,
)
app.add_typer(phase2_app, name="phase2")


def _research_client(settings: Settings):
    from radar.research.pipeline import research_client

    try:
        return research_client(settings)
    except ConfigError as exc:
        _fail(str(exc))
        raise  # unreachable: _fail exits


@phase2_app.command("collect")
def phase2_collect(
    provider: Annotated[
        str, typer.Option("--prices", help="Price source: yahoo-chart, yahoo or tiingo.")
    ] = "yahoo-chart",
    no_text: Annotated[bool, typer.Option("--no-text", help="Skip the 10-K downloads.")] = False,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Downloads everything phase 2 needs (SEC datasets and filings, prices). Resumable."""
    from radar.research.pipeline import collect_all

    settings = _setup(verbose, config)
    with _research_client(settings) as client:
        collect_all(settings, client, provider=provider, texts=not no_text)
    _say(settings, "phase2.collected", path=settings.data_dir / "phase2")


@phase2_app.command("run")
def phase2_run(
    split: Annotated[str, typer.Option("--split", help="train (2020–2022) or test (2023–2025).")],
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Measures every pre-registered variant on one split."""
    from radar.research.pipeline import run_split

    settings = _setup(verbose, config)
    with _research_client(settings) as client:
        try:
            run_split(settings, client, split)
        except (RuntimeError, ValueError) as exc:
            _fail(str(exc))
    _say(settings, "phase2.ran", split=split, path=settings.data_dir / "phase2")


@phase2_app.command("freeze")
def phase2_freeze(
    stake: Annotated[float, typer.Option("--stake", help="Stake increase chosen on train.")],
    dip: Annotated[float, typer.Option("--dip", help="Drawdown chosen on train.")],
    config: ConfigOption = None,
) -> None:
    """Records the parameters chosen on train. The test split needs them."""
    from radar.research.pipeline import freeze

    settings = _setup(False, config)
    try:
        path = freeze(settings, stake, dip)
    except (RuntimeError, ValueError) as exc:
        _fail(str(exc))
    _say(settings, "phase2.frozen", path=path)


@phase2_app.command("report")
def phase2_report(
    config: ConfigOption = None,
) -> None:
    """Writes reports/phase2-<date>.md (and .pt-BR.md) and the dashboard summary JSON."""
    from radar.research.report import write_reports

    settings = _setup(False, config)
    try:
        written = write_reports(settings)
    except RuntimeError as exc:
        _fail(str(exc))
    for path in written:
        _say(settings, "phase2.report", path=path)
