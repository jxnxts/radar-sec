"""Short data in live mode: FINRA short interest (twice a month), SEC fails-to-deliver
(twice a month) and FINRA daily short volume (context only).

Live signals are dated the day the radar sees the data, which is never earlier than
the conservative dates the backtest uses.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from radar.http import SecHttpError

from ..base import SHORT, MarketEvent, PollResult
from .data import (
    FINRA_SHORT_VOLUME_URL,
    FTD_PAGE_URL,
    ftd_links,
    ftd_name,
    parse_ftd,
    parse_short_volume,
)
from .rules import crowded_shorts, persistent_fails, squeeze_candidates, squeezes

log = logging.getLogger(__name__)

CHECK_EVERY_S = 6 * 3600
SHORT_VOLUME_EVERY_S = 3600


class ShortSource:
    name = SHORT
    interval_s = 600.0

    def __init__(self, *, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=60)
        self._last: dict[str, datetime] = {}

    def _due(self, key: str, every: float) -> bool:
        now = datetime.now(UTC)
        last = self._last.get(key)
        if last is not None and (now - last).total_seconds() < every:
            return False
        self._last[key] = now
        return True

    def poll(self, ctx) -> PollResult:
        result = PollResult()
        for key, every, step in (
            ("short_interest", CHECK_EVERY_S, self._short_interest),
            ("fails", CHECK_EVERY_S, self._fails),
            ("short_volume", SHORT_VOLUME_EVERY_S, self._short_volume),
        ):
            if not self._due(key, every):
                continue
            try:
                part = step(ctx)
            except (httpx.HTTPError, SecHttpError, ValueError) as exc:
                log.warning("short data (%s) unavailable: %s", key, exc)
                self._last.pop(key, None)
                continue
            result.events += part.events
            result.signals += part.signals
        return result

    # ------------------------------------------------------------- FINRA SI

    def _short_interest(self, ctx) -> PollResult:
        result = PollResult()
        known = ctx.store.short_interest_dates()
        dates = [
            d
            for d in ctx.finra.settlement_dates()
            if d >= ctx.today - timedelta(days=45) and d.isoformat() not in known
        ]
        today = ctx.today

        def seen_today(_settlement):
            return today

        for settlement in dates:
            records = ctx.finra.short_interest(settlement, refresh=True)
            if not records:
                continue
            ctx.store.save_short_interest(records)
            signals = crowded_shorts(records, ctx.registrant, seen_today)
            signals += squeezes(
                squeeze_candidates(records, ctx.registrant), seen_today, ctx.momentum
            )
            result.signals += signals
            result.events.append(
                MarketEvent(
                    source=SHORT,
                    kind="short_interest_release",
                    key=f"si:{settlement.isoformat()}",
                    event_date=today,
                    title=(
                        f"FINRA short interest as of {settlement.isoformat()}: "
                        f"{len(records):,} symbols, {len(signals)} flagged"
                    ),
                    data={
                        "settlement_date": settlement.isoformat(),
                        "symbols": len(records),
                        "flagged": [s.ticker for s in signals],
                    },
                )
            )
        return result

    # ------------------------------------------------------------- SEC FTD

    def _fails(self, ctx) -> PollResult:
        result = PollResult()
        links = ftd_links(ctx.client.get_text(FTD_PAGE_URL, max_age=CHECK_EVERY_S))
        named = {ftd_name(*key): url for key, url in sorted(links.items())}
        names = list(named)
        done = set(ctx.store.get_state("ftd_files", []))
        if not done:
            # First run: only the newest file matters for the live monitor.
            names = names[-1:]
        for name in [n for n in names if n not in done]:
            content = ctx.client.get_bytes(named[name])
            fails = parse_ftd(content)
            ctx.store.save_fails(f for f in fails if ctx.registrant(f.symbol))
            signals = persistent_fails(
                fails, ctx.today, ctx.registrant, ctx.shares_outstanding, file_name=name
            )
            signals = [
                s
                for s in signals
                if not ctx.prior_signal_dates(s.type, s.issuer_cik)
                or (ctx.today - max(ctx.prior_signal_dates(s.type, s.issuer_cik))).days >= 30
            ]
            result.signals += signals
            result.events.append(
                MarketEvent(
                    source=SHORT,
                    kind="ftd_release",
                    key=f"ftd:{name}",
                    event_date=ctx.today,
                    title=f"SEC fails-to-deliver file {name}: {len(fails):,} rows, "
                    f"{len(signals)} flagged",
                    data={"file": name, "rows": len(fails), "flagged": [s.ticker for s in signals]},
                )
            )
            done.add(name)
        ctx.store.set_state("ftd_files", sorted(done))
        return result

    # ------------------------------------------------------ FINRA short volume

    def _short_volume(self, ctx) -> PollResult:
        """Daily short volume (published in the evening, US time). Context only."""
        result = PollResult()
        day = ctx.today
        for _ in range(5):
            if day.weekday() < 5 and not ctx.store.get_state(f"shvol:{day.isoformat()}"):
                response = self._http.get(FINRA_SHORT_VOLUME_URL.format(day=day.strftime("%Y%m%d")))
                if response.status_code == 200 and response.text.startswith("Date|"):
                    rows = [
                        r for r in parse_short_volume(response.text) if ctx.registrant(r.symbol)
                    ]
                    ctx.store.save_short_volume(rows)
                    ctx.store.set_state(f"shvol:{day.isoformat()}", len(rows))
                    break
            day -= timedelta(days=1)
        return result
