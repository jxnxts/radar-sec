"""Builds the server from the settings: picks the engine and wires the sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import FastAPI

from radar.api.app import create_app
from radar.api.hub import Hub
from radar.api.live import LiveEngine
from radar.api.logos import LogoService
from radar.api.prices import BacktestHistory, PriceService, YahooPriceSource
from radar.api.replay import ReplayEngine
from radar.backtest.replay import latest_replay
from radar.config import Settings, sec_user_agent

# Default replay start: February 2020, just before the pandemic crash, when
# insider buying took off.
DEFAULT_REPLAY_START = date(2020, 2, 18)
PANEL_DIR = Path("web/dist")


@dataclass(frozen=True)
class ServerOptions:
    replay: bool = False
    interval: float = 60.0
    alerts: list[str] | None = None
    replay_start: date | None = None
    replay_days_per_minute: float = 2.0
    price_interval: float = 60.0
    prices: bool = True
    panel_dir: Path = PANEL_DIR


def build_app(settings: Settings, options: ServerOptions | None = None) -> FastAPI:
    options = options or ServerOptions()
    hub = Hub()
    if options.replay:
        path = latest_replay(settings.reports_dir)
        if path is None:
            raise RuntimeError(
                f"no replay file in {settings.reports_dir}/ "
                "(backtest-*-replay.jsonl.gz). Run `radar backtest` or `radar replay-build`."
            )
        engine: LiveEngine | ReplayEngine = ReplayEngine.from_file(
            path,
            hub,
            start=options.replay_start or DEFAULT_REPLAY_START,
            days_per_minute=options.replay_days_per_minute,
        )
    else:
        sec_user_agent()  # fail right away, with a clear message, if .env is not ready
        engine = LiveEngine(settings, hub, interval=options.interval, alerts=options.alerts)

    prices = None
    if options.prices:
        prices = PriceService(
            YahooPriceSource(),
            hub,
            cache_dir=settings.cache_dir,
            interval=options.price_interval,
            fallback=BacktestHistory(settings.cache_dir / "prices.duckdb"),
            tracked=engine.tracked_tickers,
        )
    app = create_app(
        engine=engine,
        hub=hub,
        prices=prices,
        logos=LogoService(settings.cache_dir),
        reports_dir=settings.reports_dir,
        static_dir=options.panel_dir,
    )
    app.state.serves_panel = (options.panel_dir / "index.html").exists()
    return app
