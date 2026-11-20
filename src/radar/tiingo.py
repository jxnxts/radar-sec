"""Tiingo REST API (paid key in TIINGO_API_KEY): IEX quotes and end-of-day prices.

- the key goes only in the `Authorization: Token ...` header: never in a URL, a log
  line, an exception message or the disk cache (nothing here writes to disk);
- one process-wide request budget per hour (shared by the dashboard quotes and the
  forward-test snapshot) plus a minimum spacing between requests; when the budget is
  spent, calls fail fast with `TiingoBudgetError` and the callers fall back to Yahoo;
- a 429 pauses every call for its `Retry-After` (or a growing pause); 401/403 are
  reported as `TiingoAuthError` so callers can stop asking.

Checked with a paid key on 2026-11-19: `/iex/?tickers=...` (batched) and
`/tiingo/daily/<ticker>/prices` answer 200; `/tiingo/news` answers 403 on that plan and
the all-tickers `/tiingo/daily/prices` snapshot is limited to the Power plan.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from radar.http import RateLimiter

BASE_URL = "https://api.tiingo.com"
BACKOFF_START_S = 60.0
BACKOFF_MAX_S = 3600.0


class TiingoError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TiingoAuthError(TiingoError):
    """401/403: the key is wrong or the plan does not include this endpoint."""


class TiingoBudgetError(TiingoError):
    """The hourly request budget is spent, or Tiingo asked us to slow down (429)."""


class RequestBudget:
    """At most `per_hour` requests in any sliding hour (thread-safe)."""

    def __init__(self, per_hour: int, *, clock: Callable[[], float] = time.monotonic):
        self.per_hour = max(1, per_hour)
        self._clock = clock
        self._times: deque[float] = deque()
        self._lock = threading.Lock()
        self.blocked_until = 0.0
        self._failures = 0

    def _trim(self, now: float) -> None:
        while self._times and now - self._times[0] >= 3600.0:
            self._times.popleft()

    def take(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self.blocked_until:
                raise TiingoBudgetError(
                    f"Tiingo paused for {self.blocked_until - now:.0f}s after a 429"
                )
            self._trim(now)
            if len(self._times) >= self.per_hour:
                raise TiingoBudgetError(f"Tiingo budget of {self.per_hour} requests/hour spent")
            self._times.append(now)

    def used(self) -> int:
        with self._lock:
            self._trim(self._clock())
            return len(self._times)

    def pause(self, retry_after: str = "") -> float:
        with self._lock:
            self._failures += 1
            pause = min(BACKOFF_MAX_S, BACKOFF_START_S * 2 ** (self._failures - 1))
            if retry_after.isdigit():
                pause = min(BACKOFF_MAX_S, max(pause, float(retry_after)))
            self.blocked_until = self._clock() + pause
            return pause

    def ok(self) -> None:
        self._failures = 0


_budget: RequestBudget | None = None
_budget_lock = threading.Lock()


def shared_budget(per_hour: int) -> RequestBudget:
    """The process-wide budget (the first caller sets its size)."""
    global _budget
    with _budget_lock:
        if _budget is None:
            _budget = RequestBudget(per_hour)
        return _budget


def tiingo_symbol(symbol: str) -> str | None:
    """Tiingo ticker for a Yahoo-style symbol ("BRK-B" → "brk-b"); None for indices."""
    symbol = (symbol or "").strip()
    if not symbol or symbol.startswith("^"):
        return None
    return symbol.replace(".", "-").lower()


class TiingoClient:
    def __init__(
        self,
        api_key: str,
        *,
        requests_per_hour: int = 500,
        requests_per_second: float = 2.0,
        timeout: float = 20.0,
        budget: RequestBudget | None = None,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ):
        if not api_key:
            raise ValueError("Tiingo needs TIINGO_API_KEY")
        self._client = httpx.Client(
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=timeout,
            transport=transport,
        )
        self.budget = budget or shared_budget(requests_per_hour)
        self._limiter = limiter or RateLimiter(requests_per_second)
        self.requests_made = 0

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """JSON answer of `path`. Errors never carry the key (it is only in a header)."""
        url = f"{BASE_URL}{path}"
        if params:
            url += f"?{urlencode(params)}"
        self.budget.take()
        self._limiter.acquire()
        self.requests_made += 1
        try:
            response = self._client.get(url)
        except httpx.TransportError as exc:
            raise TiingoError(f"Tiingo unreachable ({exc.__class__.__name__})") from None
        status = response.status_code
        if status == 429:
            pause = self.budget.pause(response.headers.get("Retry-After", ""))
            raise TiingoBudgetError(f"Tiingo HTTP 429; pausing {pause:.0f}s", status)
        detail = ""
        if status != 200:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = " ".join(str(payload.get("detail") or "").split())[:160]
            except ValueError:
                pass
            message = f"Tiingo HTTP {status} on {path}" + (f": {detail}" if detail else "")
            if status in (401, 403):
                raise TiingoAuthError(message, status)
            raise TiingoError(message, status)
        self.budget.ok()
        try:
            payload = response.json()
        except ValueError:
            raise TiingoError(f"Tiingo answered non-JSON on {path}", status) from None
        # Some limits come back as 200 with {"detail": "..."} instead of data.
        if isinstance(payload, dict) and "detail" in payload:
            raise TiingoError(f"Tiingo: {str(payload['detail'])[:160]}", status)
        return payload

    def iex(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Top-of-book and last price of several tickers in one request."""
        if not tickers:
            return []
        payload = self.get("/iex/", {"tickers": ",".join(tickers)})
        return payload if isinstance(payload, list) else []

    def iex_intraday(self, ticker: str, day: date, freq: str = "5min") -> list[dict[str, Any]]:
        payload = self.get(
            f"/iex/{ticker}/prices",
            {"startDate": day.isoformat(), "resampleFreq": freq, "columns": "close"},
        )
        return payload if isinstance(payload, list) else []

    def daily(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        """End-of-day prices (raw and adjusted, with split factors) of one ticker."""
        payload = self.get(
            f"/tiingo/daily/{ticker}/prices",
            {"startDate": start.isoformat(), "endDate": end.isoformat()},
        )
        return payload if isinstance(payload, list) else []
