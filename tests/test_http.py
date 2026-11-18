import httpx
import pytest

from radar.config import ConfigError, SecConfig, sec_user_agent
from radar.http import RateLimiter, SecClient, SecHttpError, cache_path_for
from tests.conftest import TEST_USER_AGENT

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001.txt"


def test_user_agent_is_sent_on_every_request(make_client, recorder):
    recorder.add(URL, "ok")
    make_client().get_text(URL)
    assert recorder.calls[0].headers["User-Agent"] == TEST_USER_AGENT


def test_missing_user_agent_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT")
    with pytest.raises(ConfigError, match="SEC_USER_AGENT"):
        sec_user_agent()
    with pytest.raises(ConfigError, match=r"\.env"):
        SecClient(tmp_path / "cache")


@pytest.mark.parametrize("value", ["nocontact", "name-without-at example", "a@b.com"])
def test_malformed_user_agent_is_rejected(monkeypatch, value):
    monkeypatch.setenv("SEC_USER_AGENT", value)
    with pytest.raises(ConfigError, match="format"):
        sec_user_agent()


def test_retries_with_growing_backoff_on_429_and_5xx(make_client, recorder):
    answers = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, text="finally")])
    recorder.add(URL, lambda request: next(answers))
    client = make_client()

    assert client.get_text(URL) == "finally"
    assert len(recorder.calls) == 3
    first, second = client.sleeps
    assert 1.0 <= first < 2.0 and 2.0 <= second < 3.0  # 1s, 2s (+ random jitter)


def test_honours_retry_after_header(make_client, recorder):
    answers = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    recorder.add(URL, lambda request: next(answers))
    client = make_client()
    client.get_bytes(URL)
    assert client.sleeps == [7.0]


def test_gives_up_after_max_retries(make_client, recorder):
    recorder.add(URL, httpx.Response(503))
    client = make_client(config=SecConfig(max_retries=2))
    with pytest.raises(SecHttpError, match="after 3 attempts"):
        client.get_bytes(URL)
    assert len(recorder.calls) == 3


def test_network_errors_are_retried(make_client, recorder):
    state = {"n": 0}

    def flaky(request):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("no network")
        return httpx.Response(200, text="back")

    recorder.add(URL, flaky)
    assert make_client().get_text(URL) == "back"


def test_client_errors_are_not_retried(make_client, recorder):
    recorder.add(URL, httpx.Response(404))
    with pytest.raises(SecHttpError) as info:
        make_client().get_bytes(URL)
    assert info.value.status_code == 404
    assert len(recorder.calls) == 1


def test_403_explains_the_usual_cause(make_client, recorder):
    recorder.add(URL, httpx.Response(403))
    with pytest.raises(SecHttpError, match="User-Agent"):
        make_client().get_bytes(URL)


def test_downloads_are_cached_on_disk(make_client, recorder, tmp_path):
    recorder.add(URL, "immutable content")
    client = make_client()
    assert client.get_text(URL) == "immutable content"
    assert client.get_text(URL) == "immutable content"
    assert len(recorder.calls) == 1
    cached = cache_path_for(tmp_path / "cache", URL)
    assert cached.read_text(encoding="utf-8") == "immutable content"
    assert cached.name == "0000000001-26-000001.txt"  # readable path, mirroring the URL


def test_max_age_zero_always_refetches_but_still_stores(make_client, recorder, tmp_path):
    feed = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4"
    bodies = iter(["first", "second"])
    recorder.add(feed, lambda request: httpx.Response(200, text=next(bodies)))
    client = make_client()
    assert client.get_text(feed, max_age=0) == "first"
    assert client.get_text(feed, max_age=0) == "second"
    assert cache_path_for(tmp_path / "cache", feed).read_text() == "second"


def test_query_strings_get_distinct_cache_files(tmp_path):
    a = cache_path_for(tmp_path, "https://www.sec.gov/cgi-bin/browse-edgar?type=4")
    b = cache_path_for(tmp_path, "https://www.sec.gov/cgi-bin/browse-edgar?type=SC+13D")
    assert a != b and a.parent == b.parent


def test_rate_limiter_spaces_requests():
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(8, clock=lambda: now[0], sleep=sleep)
    for _ in range(9):
        limiter.acquire()

    assert len(waits) == 8  # only the first one goes straight through
    assert all(w == pytest.approx(0.125) for w in waits)
    assert now[0] == pytest.approx(1.0)  # 9 requests take 1 second: 8 per second


def test_every_request_goes_through_the_limiter(make_client, recorder):
    acquired = []

    class Counting(RateLimiter):
        def acquire(self) -> None:
            acquired.append(1)

    answers = iter([httpx.Response(500), httpx.Response(200)])
    recorder.add(URL, lambda request: next(answers))
    make_client(limiter=Counting(8)).get_bytes(URL)
    assert len(acquired) == 2  # the retry also uses up quota


def test_fetch_many_returns_content_or_error_per_url(make_client, recorder):
    good = [f"https://www.sec.gov/Archives/edgar/data/1/{i}.txt" for i in range(12)]
    missing = "https://www.sec.gov/Archives/edgar/data/1/gone.txt"
    for i, url in enumerate(good):
        recorder.add(url, f"filing {i}")
    recorder.add(missing, httpx.Response(404))

    results = make_client().fetch_many([*good, missing, good[0]])

    assert list(results) == [*good, missing]  # no repeats, in the requested order
    assert [results[url] for url in good] == [f"filing {i}".encode() for i in range(12)]
    assert isinstance(results[missing], SecHttpError) and results[missing].status_code == 404
    assert len(recorder.calls) == 13
