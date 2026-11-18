"""HTTP client for the SEC: mandatory User-Agent, rate limiting, retries and disk cache."""

from __future__ import annotations

import hashlib
import logging
import random
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from radar.config import SecConfig, sec_user_agent

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class SecHttpError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimiter:
    """Enforces a minimum interval between requests (thread-safe)."""

    def __init__(
        self,
        rate_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self.interval = 1.0 / rate_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + self.interval
        if wait > 0:
            self._sleep(wait)


_global_limiter: RateLimiter | None = None
_global_lock = threading.Lock()


def global_limiter(rate_per_second: float) -> RateLimiter:
    """Process-wide limiter: every SEC client shares the same quota."""
    global _global_limiter
    with _global_lock:
        if _global_limiter is None:
            _global_limiter = RateLimiter(rate_per_second)
        return _global_limiter


def cache_path_for(cache_dir: Path, url: str) -> Path:
    """Readable cache path for a URL (the query string becomes a hash)."""
    parts = urlsplit(url)
    segments = [re.sub(r"[^A-Za-z0-9._-]", "_", s) for s in parts.path.split("/") if s]
    if not segments:
        segments = ["_root"]
    if parts.query:
        digest = hashlib.sha256(parts.query.encode()).hexdigest()[:16]
        segments[-1] = f"{segments[-1]}__{digest}"
    return cache_dir.joinpath(parts.netloc.replace(":", "_"), *segments)


def decode(data: bytes, encoding: str = "utf-8") -> str:
    """Decodes the content; old filings sometimes come in Latin-1."""
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("latin-1")


class SecClient:
    """SEC access that follows the fair access rules.

    - always sends the User-Agent from `SEC_USER_AGENT`;
    - routes every request through the global limiter (~8/s);
    - retries with exponential backoff on 429/5xx and network failures;
    - stores everything it downloads in `cache_dir` and reuses it according to `max_age`.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        config: SecConfig | None = None,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config or SecConfig()
        self.user_agent = user_agent or sec_user_agent()
        self.cache_dir = cache_dir
        self._limiter = limiter or global_limiter(self.config.requests_per_second)
        self._sleep = sleep
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self.requests_made = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ cache

    def _fresh(self, path: Path, max_age: float | None) -> bool:
        if not path.exists():
            return False
        if max_age is None:
            return True
        return (time.time() - path.stat().st_mtime) < max_age

    @staticmethod
    def _store(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)

    # --------------------------------------------------------------- requests

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), 120.0)
        return min(60.0, 1.0 * (2**attempt)) + random.uniform(0, 0.5)

    def _request(self, url: str, retries: int | None = None) -> httpx.Response:
        last_error = "no response"
        max_retries = self.config.max_retries if retries is None else retries
        attempts = max_retries + 1
        for attempt in range(attempts):
            self._limiter.acquire()
            self.requests_made += 1
            response: httpx.Response | None = None
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = f"network failure ({exc.__class__.__name__}: {exc})"
            else:
                if response.status_code == 200:
                    return response
                if response.status_code not in RETRY_STATUS:
                    hint = ""
                    if response.status_code == 403:
                        hint = (
                            " — the SEC usually answers 403 when the User-Agent does not "
                            "identify you or when the request rate limit was exceeded"
                        )
                    raise SecHttpError(
                        f"HTTP {response.status_code} on {url}{hint}", response.status_code
                    )
                last_error = f"HTTP {response.status_code}"
            if attempt < attempts - 1:
                delay = self._backoff(attempt, response)
                log.warning(
                    "%s on %s; retrying in %.1fs (%d/%d)",
                    last_error,
                    url,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                self._sleep(delay)
        raise SecHttpError(f"{last_error} on {url} after {attempts} attempts")

    def get_bytes(
        self,
        url: str,
        *,
        max_age: float | None = None,
        retries: int | None = None,
        store: bool = True,
    ) -> bytes:
        """Downloads `url` (or reads it from the cache).

        `max_age=None` is for immutable content (filings, zips): the cache never
        expires. `max_age=0` always fetches again, but still writes the copy to disk.
        `retries` overrides the number of retries for this call only.
        `store=False` does not write the response: for callers that only use one
        field of a large file and store that field themselves.
        """
        path = cache_path_for(self.cache_dir, url)
        if self._fresh(path, max_age):
            return path.read_bytes()
        content = self._request(url, retries).content
        if store:
            self._store(path, content)
        return content

    def get_text(self, url: str, *, max_age: float | None = None, encoding: str = "utf-8") -> str:
        return decode(self.get_bytes(url, max_age=max_age), encoding)

    def fetch_many(
        self,
        urls: Iterable[str],
        *,
        max_age: float | None = None,
        retries: int | None = None,
        workers: int = 6,
    ) -> dict[str, bytes | SecHttpError]:
        """Downloads several URLs in parallel; the global limiter still applies to all of them.

        Returns the content or the error for each URL, so the caller can decide what
        to do with the ones that failed without repeating the retries.
        """
        unique = list(dict.fromkeys(urls))

        def fetch(url: str) -> bytes | SecHttpError:
            try:
                return self.get_bytes(url, max_age=max_age, retries=retries)
            except SecHttpError as exc:
                return exc

        if len(unique) <= 1:
            return {url: fetch(url) for url in unique}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(zip(unique, pool.map(fetch, unique), strict=True))

    def download(self, url: str, *, max_age: float | None = None) -> Path:
        """Like `get_bytes`, but returns the path of the cached file (for large zips)."""
        path = cache_path_for(self.cache_dir, url)
        if not self._fresh(path, max_age):
            self._store(path, self._request(url).content)
        return path
