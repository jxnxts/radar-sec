"""HTTP for the news hosts: polite, conditional and without the SEC limiter.

- one minimum interval per host (GDELT asks for at most one request every 5 s);
- `If-None-Match` / `If-Modified-Since` on feeds that send an ETag or Last-Modified,
  so an unchanged feed costs a 304 instead of the whole file;
- no retries inside a poll: a host that answers 403/429/5xx is left alone for a
  growing pause (or its `Retry-After`) and the next poll tries again;
- `robots=True` (the RSS wires) reads the host's robots.txt first and refuses a URL it
  disallows for our User-Agent (RFC 9309: a missing robots.txt allows everything; a
  server error on it means "not now");
- nothing is written to disk: answers can carry an API key in the request.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from radar.http import RateLimiter

BACKOFF_STATUS = frozenset({403, 429, 500, 502, 503, 504})
BACKOFF_START_S = 60.0
BACKOFF_MAX_S = 3600.0
ROBOTS_MAX_AGE_S = 86_400.0


class NewsHttpError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class NewsClient:
    def __init__(
        self,
        *,
        user_agent: str,
        min_host_interval: float = 5.0,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._interval = max(min_host_interval, 0.001)
        self._clock = clock
        self._sleep = sleep
        self._limiters: dict[str, RateLimiter] = {}
        self._validators: dict[str, dict[str, str]] = {}
        self._blocked_until: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._robots: dict[str, tuple[float, RobotFileParser]] = {}
        self.user_agent = user_agent
        self.requests_made = 0

    def close(self) -> None:
        self._client.close()

    def _limiter(self, host: str) -> RateLimiter:
        if host not in self._limiters:
            self._limiters[host] = RateLimiter(
                1.0 / self._interval, clock=self._clock, sleep=self._sleep
            )
        return self._limiters[host]

    def blocked_for(self, url: str) -> float:
        """Seconds the host of `url` is still being left alone (0 when it may be asked)."""
        host = urlsplit(url).netloc.lower()
        return max(0.0, self._blocked_until.get(host, 0.0) - self._clock())

    def _back_off(self, host: str, response: httpx.Response | None) -> float:
        failures = self._failures.get(host, 0) + 1
        self._failures[host] = failures
        pause = min(BACKOFF_MAX_S, BACKOFF_START_S * 2 ** (failures - 1))
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                pause = min(BACKOFF_MAX_S, max(pause, float(retry_after)))
        self._blocked_until[host] = self._clock() + pause
        return pause

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        cached = self._robots.get(host)
        if cached is not None and self._clock() - cached[0] < ROBOTS_MAX_AGE_S:
            return cached[1]
        parser = RobotFileParser()
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        self._limiter(host).acquire()
        self.requests_made += 1
        try:
            response = self._client.get(robots_url)
        except httpx.TransportError as exc:
            raise NewsHttpError(f"robots.txt of {host} unreachable; trying later") from exc
        if response.status_code >= 500:
            raise NewsHttpError(
                f"robots.txt of {host}: HTTP {response.status_code}; trying later",
                response.status_code,
            )
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
        else:  # 4xx: no usable robots.txt, everything is allowed (RFC 9309)
            parser.parse([])
        self._robots[host] = (self._clock(), parser)
        return parser

    def allowed(self, url: str) -> bool:
        """Whether the host's robots.txt lets our User-Agent fetch `url`."""
        return self._robots_for(url).can_fetch(self.user_agent, url)

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        conditional: bool = True,
        robots: bool = False,
    ) -> bytes | None:
        """The body of `url`, or None when the server says it did not change (304)."""
        host = urlsplit(url).netloc.lower()
        wait = self.blocked_for(url)
        if wait > 0:
            raise NewsHttpError(f"{host} is paused for {wait:.0f}s after an error")
        if robots and not self.allowed(url):
            raise NewsHttpError(f"robots.txt of {host} disallows {urlsplit(url).path}")
        send = dict(headers or {})
        if conditional:
            send.update(self._validators.get(url, {}))
        self._limiter(host).acquire()
        self.requests_made += 1
        try:
            response = self._client.get(url, headers=send)
        except httpx.TransportError as exc:
            pause = self._back_off(host, None)
            raise NewsHttpError(
                f"network failure on {host} ({exc.__class__.__name__}); pausing {pause:.0f}s"
            ) from exc
        if response.status_code == 304:
            self._failures.pop(host, None)
            return None
        if response.status_code != 200:
            pause = (
                self._back_off(host, response) if response.status_code in BACKOFF_STATUS else 0.0
            )
            suffix = f"; pausing {pause:.0f}s" if pause else ""
            raise NewsHttpError(
                f"HTTP {response.status_code} on {host}{suffix}", response.status_code
            )
        self._failures.pop(host, None)
        if conditional:
            validators = {}
            if etag := response.headers.get("ETag"):
                validators["If-None-Match"] = etag
            if modified := response.headers.get("Last-Modified"):
                validators["If-Modified-Since"] = modified
            if validators:
                self._validators[url] = validators
        return response.content
