"""The dashboard's FastAPI application: REST, WebSocket and background tasks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from radar import __version__
from radar.api import hub as events
from radar.api.backtest_summary import load_summary
from radar.api.hub import Hub
from radar.api.logos import LogoService
from radar.api.prices import PriceService
from radar.api.ranking import WINDOWS
from radar.signals import SIGNAL_TYPES

log = logging.getLogger(__name__)

STATUS_INTERVAL = 5.0
_SYMBOL = re.compile(r"^\^?[A-Z0-9]{1,6}(-[A-Z]{1,2})?$")


class Engine(Protocol):
    """What the server needs from an engine (LIVE or REPLAY)."""

    mode: str

    async def run(self) -> None: ...
    def close(self) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
    def status(self) -> dict[str, Any]: ...
    def list_signals(
        self, *, limit: int = ..., since: date | None = ..., signal_type: str | None = ...
    ) -> list[dict[str, Any]]: ...
    def list_filings(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def signal_detail(self, signal_id: str) -> dict[str, Any] | None: ...
    def company(self, cik: str) -> dict[str, Any] | None: ...
    def ranking(self, days: int) -> dict[str, Any]: ...
    def tracked_tickers(self) -> list[str]: ...


class ReplayControl(BaseModel):
    paused: bool | None = None
    speed: float | None = None
    seek: date | None = None


def create_app(
    *,
    engine: Engine,
    hub: Hub,
    prices: PriceService | None = None,
    logos: LogoService | None = None,
    reports_dir: Path = Path("reports"),
    static_dir: Path | None = None,
    background: bool = True,
) -> FastAPI:
    """Builds the server. `background=False` keeps collection stopped (for tests)."""
    started = time.monotonic()

    def status() -> dict[str, Any]:
        return {
            **engine.status(),
            "server_time": datetime.now(UTC).isoformat(timespec="seconds"),
            "uptime_s": int(time.monotonic() - started),
            "version": __version__,
            "ws": {"clients": hub.clients},
            "prices": prices.status() if prices else {"state": "off"},
        }

    def snapshot() -> dict[str, Any]:
        return {
            "mode": engine.mode,
            "status": status(),
            "quotes": prices.quotes if prices else {},
            **engine.snapshot(),
        }

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(STATUS_INTERVAL)
            hub.publish(events.SYSTEM_STATUS, status())

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.bind(asyncio.get_running_loop())
        tasks: list[asyncio.Task[None]] = []
        if background:
            tasks.append(asyncio.create_task(engine.run(), name="radar-engine"))
            tasks.append(asyncio.create_task(heartbeat(), name="radar-status"))
            if prices is not None:
                tasks.append(asyncio.create_task(prices.run(), name="radar-prices"))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            hub.bind(None)
            await run_in_threadpool(engine.close)
            if prices is not None:
                prices.close()
            if logos is not None:
                logos.close()

    app = FastAPI(title="radar-sec — dashboard", version=__version__, lifespan=lifespan)
    app.state.hub = hub
    app.state.engine = engine
    app.state.snapshot = snapshot

    # ------------------------------------------------------------------ REST

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, **status()}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return {"seq": hub.seq, "boot": hub.boot_id, "data": snapshot()}

    @app.get("/api/signals")
    def signals(
        limit: int = Query(60, ge=1, le=500),
        since: date | None = None,
        type: str | None = Query(None, description=f"One of: {', '.join(SIGNAL_TYPES)}"),
    ) -> list[dict[str, Any]]:
        if type is not None and type not in SIGNAL_TYPES:
            raise HTTPException(422, f"unknown type: {type}")
        return engine.list_signals(limit=limit, since=since, signal_type=type)

    @app.get("/api/signals/{signal_id}")
    def signal(signal_id: str) -> dict[str, Any]:
        detail = engine.signal_detail(signal_id)
        if detail is None:
            raise HTTPException(404, "signal not found")
        return detail

    @app.get("/api/filings")
    def filings(limit: int = Query(60, ge=1, le=300)) -> list[dict[str, Any]]:
        return engine.list_filings(limit)

    @app.get("/api/company/{cik}")
    def company(cik: str) -> dict[str, Any]:
        if not cik.isdigit():
            raise HTTPException(422, "invalid CIK")
        found = engine.company(cik.lstrip("0"))
        if found is None:
            raise HTTPException(404, "company without recorded signals or buys")
        return found

    @app.get("/api/ranking")
    def ranking(days: int = Query(7)) -> dict[str, Any]:
        if days not in WINDOWS:
            raise HTTPException(422, f"window must be one of {WINDOWS}")
        return engine.ranking(days)

    @app.get("/api/backtest")
    def backtest() -> dict[str, Any]:
        summary = load_summary(reports_dir)
        if summary is None:
            raise HTTPException(404, "no backtest report in reports/")
        return summary

    @app.get("/api/quotes")
    def quotes() -> dict[str, Any]:
        if prices is None:
            raise HTTPException(503, "quotes are off")
        return prices.tick()

    @app.get("/api/prices/{symbol}/history")
    def history(symbol: str, start: date, end: date) -> dict[str, Any]:
        if prices is None:
            raise HTTPException(503, "quotes are off")
        symbol = symbol.upper()
        if not _SYMBOL.match(symbol):
            raise HTTPException(422, "invalid ticker")
        if start >= end:
            raise HTTPException(422, "start must be before end")
        return prices.history(symbol, start, end)

    @app.get("/api/logo/{ticker}")
    def logo(ticker: str) -> Response:
        data = logos.get(ticker) if logos is not None else None
        if data is None:
            # The browser caches the 404 too: the dashboard shows the monogram without retrying.
            return Response(status_code=404, headers={"Cache-Control": "public, max-age=86400"})
        return Response(
            data,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/replay/control")
    def replay_control(body: ReplayControl) -> dict[str, Any]:
        control = getattr(engine, "control", None)
        if control is None:
            raise HTTPException(409, "the server is in LIVE mode")
        return control(paused=body.paused, speed=body.speed, seek=body.seek)

    # ------------------------------------------------------------- WebSocket

    @app.websocket("/ws")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        # Subscribe before building the snapshot: whatever is published meanwhile waits
        # in the queue, and the client drops by `seq` what the snapshot already had.
        subscription = hub.subscribe()
        seq = hub.seq
        try:
            data = await run_in_threadpool(snapshot)
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "seq": seq,
                    "boot": hub.boot_id,
                    "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                    "data": data,
                }
            )
            receiver = asyncio.create_task(_drain(websocket))
            try:
                while not subscription.lagging:
                    getter = asyncio.create_task(subscription.queue.get())
                    done, _ = await asyncio.wait(
                        {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if getter not in done:
                        getter.cancel()
                        break
                    await websocket.send_json(getter.result())
                else:
                    # Slow client: close so it reconnects and gets a fresh snapshot.
                    await websocket.close(code=1013, reason="client lagging")
            finally:
                receiver.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(subscription)

    # ------------------------------------------------------- static dashboard

    if static_dir is not None and (static_dir / "index.html").exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "ws")):
                raise HTTPException(404)
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


async def _drain(websocket: WebSocket) -> None:
    """Reads (and ignores) what the client sends; ends when it disconnects."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await websocket.receive_text()
