"""Full monitor cycle, offline: feed → real filings → signals → alerts."""

import json
from dataclasses import replace
from datetime import date, datetime

import pytest

from radar.config import AIConfig, SecConfig, SignalConfig
from radar.db import Database
from radar.feed import feed_url
from radar.summary import Summarizer
from radar.watch import SUBMISSIONS_URL, Watcher, parse_since
from tests.conftest import read_fixture

MP_CFO = ("0001831686-26-000014", "4", "MP Materials Corp. / DE", "1801368", "Issuer")
BOLT = ("0001104659-26-129252", "4", "Bolt Biotherapeutics, Inc.", "1641281", "Issuer")
GILEAD = ("0001782135-26-000037", "4", "GILEAD SCIENCES, INC.", "882095", "Issuer")
NEW_13D = ("0001104659-26-129222", "SCHEDULE 13D", "Perfect Moment Ltd.", "1849221", "Subject")
AMENDED_13D = (
    "0001104659-26-129242",
    "SCHEDULE 13D/A",
    "Atlas Energy Solutions Inc.",
    "1984060",
    "Subject",
)
TODAY = date(2026, 11, 17)


def index_url(accession: str, cik: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
        f"{accession}-index.htm"
    )


def atom(filings) -> str:
    """A feed in EDGAR's format, with only the filings we have fixtures for."""
    entries = "".join(
        f"""<entry><title>{form} - {name.replace("&", "&amp;")} ({int(cik):010d}) ({role})</title>
<link rel="alternate" type="text/html" href="{index_url(accession, cik)}"/>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-11-17 &lt;b&gt;AccNo:&lt;/b&gt; {accession}</summary>
<updated>2026-11-17T20:45:36-05:00</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={accession}</id></entry>"""
        for accession, form, name, cik, role in filings
    )
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'


class Collector:
    name = "coletor"

    def __init__(self):
        self.signals = []

    def send(self, signal):
        self.signals.append(signal)


@pytest.fixture
def world(settings, recorder, make_client):
    """A fake SEC: the three feeds and the .txt files of the real filings."""
    form4 = [MP_CFO, BOLT, GILEAD]
    thirteen_d = [NEW_13D, AMENDED_13D]
    recorder.add(feed_url("4"), atom(form4))
    recorder.add(feed_url("SCHEDULE 13D", count=40), atom(thirteen_d))
    for accession, _, _, cik, _ in form4 + thirteen_d:
        recorder.add(
            index_url(accession, cik).replace("-index.htm", ".txt"),
            read_fixture(f"{accession}.txt"),
        )
    recorder.add(
        "https://www.sec.gov/files/company_tickers.json",
        json.dumps({"0": {"cik_str": 1849221, "ticker": "PMNT", "title": "Perfect Moment"}}),
    )

    settings = replace(
        settings,
        sec=SecConfig(backfill_issuer=False),
        signals=SignalConfig(officer_min_value=50_000),  # the CFO's real purchase was $91K
    )
    db = Database(":memory:")
    collector = Collector()
    ai_calls = []

    def fake_ai(prompt, **kwargs):
        ai_calls.append(prompt)
        return "AI summary."

    def build(custom=settings):
        return Watcher(
            custom,
            db,
            make_client(config=custom.sec),
            [collector],
            Summarizer(db, AIConfig(), generate=fake_ai),
            today=TODAY,
        )

    return type(
        "World",
        (),
        {
            "settings": settings,
            "db": db,
            "collector": collector,
            "ai_calls": ai_calls,
            "build": staticmethod(build),
            "recorder": recorder,
        },
    )


def test_first_cycle_stores_parses_and_alerts(world):
    result = world.build().run_once()

    assert result.new_filings == 5 and result.processed == 5 and result.errors == 0
    assert world.db.count_filings() == 5
    assert world.db.pending_filings() == []

    by_type = {s.type: s for s in result.signals}
    assert set(by_type) == {"big_officer_buy", "activist_13d"}

    officer = by_type["big_officer_buy"]
    assert officer.ticker == "MP" and officer.details["role"] == "CFO"
    assert officer.details["total_value"] == pytest.approx(91_577.22)
    assert officer.signal_date == date(2026, 11, 17)

    activist = by_type["activist_13d"]
    assert activist.issuer_name == "Perfect Moment Ltd."
    assert activist.ticker == "PMNT"  # the 13D has no ticker; it comes from the SEC registry
    assert activist.details["percent"] == 9.9

    assert [s.type for s in world.collector.signals] == [s.type for s in result.signals]
    assert all(s.summary == "AI summary." and s.summary_source == "ai" for s in result.signals)
    assert len(world.ai_calls) == 2  # AI only for fired signals, never per filing
    stored = world.db.list_signals()
    assert len(stored) == 2 and all(s.summary == "AI summary." for s in stored)
    assert all(s.summary_source == "ai" for s in stored)
    assert all("on the open market" in s.explanation or "13D" in s.explanation for s in stored)


def test_amendments_and_non_purchases_do_not_signal(world):
    result = world.build().run_once()
    issuers = {s.issuer_name for s in result.signals}
    assert "Atlas Energy Solutions Inc." not in issuers  # 13D/A
    assert "GILEAD SCIENCES, INC." not in issuers  # exercise and sale
    assert "Bolt Biotherapeutics, Inc." not in issuers  # a single insider, and not a CEO/CFO


def test_second_cycle_finds_nothing_new(world):
    world.build().run_once()
    alerts_before = len(world.collector.signals)
    downloads_before = len(world.recorder.calls)

    result = world.build().run_once()

    assert result.new_filings == 0 and result.processed == 0 and result.signals == []
    assert world.db.count_filings() == 5
    assert len(world.collector.signals) == alerts_before  # no repeated alert
    assert len(world.ai_calls) == 2
    # Only the two feeds were queried again; no filing was downloaded again.
    assert len(world.recorder.calls) - downloads_before == 2


def test_default_thresholds_ignore_the_small_cfo_purchase(world):
    result = world.build(replace(world.settings, signals=SignalConfig())).run_once()
    assert [s.type for s in result.signals] == ["activist_13d"]


def test_unparseable_filing_is_recorded_and_does_not_stop_the_cycle(world):
    broken_url = index_url(GILEAD[0], GILEAD[3]).replace("-index.htm", ".txt")
    world.recorder.add(
        broken_url,
        "<SEC-DOCUMENT><DOCUMENT><TYPE>4<TEXT><XML><ownershipDocument>"
        "<issuer></XML></TEXT></DOCUMENT>",
    )
    result = world.build().run_once()
    assert result.errors == 1 and result.processed == 4
    row = world.db.conn.execute(
        "SELECT status, error FROM filings WHERE accession = ?", (GILEAD[0],)
    ).fetchone()
    assert row["status"] == "error" and "XML" in row["error"]
    assert len(result.signals) == 2


def test_transient_download_failure_is_retried_next_cycle(world, make_client):
    import httpx

    url = index_url(MP_CFO[0], MP_CFO[3]).replace("-index.htm", ".txt")
    original = world.recorder.routes[url]
    world.recorder.add(url, httpx.Response(503))
    first = world.build().run_once()
    assert first.errors == 1
    assert [r.accession for r in world.db.pending_filings()] == [MP_CFO[0]]

    world.recorder.add(url, original)
    second = world.build().run_once()
    assert second.processed == 1
    assert [s.type for s in second.signals] == ["big_officer_buy"]


def test_issuer_backfill_completes_the_cluster_window(world):
    """The monitor just started and sees a buy; the earlier one, by another insider, comes from history."""
    earlier = "0009999999-26-000001"
    earlier_txt = (
        read_fixture(f"{MP_CFO[0]}.txt")
        .replace(MP_CFO[0], earlier)
        .replace("<rptOwnerCik>0001831686</rptOwnerCik>", "<rptOwnerCik>0007777777</rptOwnerCik>")
        .replace("Corbett Ryan", "Outra Pessoa")
        .replace("Chief Financial Officer", "Chief Executive Officer")
        .replace("FILED AS OF DATE:\t\t20261117", "FILED AS OF DATE:\t\t20261112")
        .replace("<value>2026-11-17</value>", "<value>2026-11-11</value>")
    )
    world.recorder.add(
        SUBMISSIONS_URL.format(cik=1801368),
        json.dumps(
            {
                "filings": {
                    "recent": {
                        "accessionNumber": [MP_CFO[0], earlier, "0009999999-25-000009"],
                        "form": ["4", "4", "4"],
                        "filingDate": [
                            "2026-11-17",
                            "2026-11-12",
                            "2025-01-10",
                        ],  # the last one is too old
                    }
                }
            }
        ),
    )
    world.recorder.add(
        f"https://www.sec.gov/Archives/edgar/data/1801368/{earlier.replace('-', '')}/{earlier}.txt",
        earlier_txt,
    )
    settings = replace(world.settings, sec=SecConfig(backfill_issuer=True), signals=SignalConfig())

    result = world.build(settings).run_once()

    assert result.backfilled == 1
    cluster = next(s for s in result.signals if s.type == "cluster_buy")
    assert cluster.details["n_insiders"] == 2
    assert cluster.details["total_value"] == pytest.approx(2 * 91_577.22)
    assert cluster.signal_date == date(2026, 11, 17)  # day the second insider filed


def test_old_reconstructed_signals_are_stored_without_alert(world):
    stale = replace(world.settings)
    watcher = Watcher(
        stale,
        world.db,
        world.build().client,
        [world.collector],
        Summarizer(world.db, AIConfig(enabled=False)),
        today=date(2027, 3, 1),
    )
    result = watcher.run_once()
    assert result.signals == [] and result.stored_only == 2
    assert world.collector.signals == []
    assert len(world.db.list_signals()) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7d", date(2026, 11, 10)),
        ("24h", date(2026, 11, 16)),
        ("2w", date(2026, 11, 3)),
        ("1m", date(2026, 10, 18)),
        ("2026-01-31", date(2026, 1, 31)),
    ],
)
def test_parse_since(text, expected):
    assert parse_since(text, now=datetime(2026, 11, 17, 12, 0)) == expected


def test_parse_since_rejects_nonsense():
    with pytest.raises(ValueError, match="invalid period"):
        parse_since("semana passada")


def test_a_feed_that_is_down_does_not_stop_the_others(world):
    import httpx

    world.recorder.add(feed_url("SCHEDULE 13D", count=40), httpx.Response(503))
    result = world.build().run_once()

    assert result.errors == 1  # the 13D feed failed...
    assert result.new_filings == 3 and result.processed == 3  # ...and the Form 4s went on
    feed_calls = [u for u in world.recorder.urls() if "SCHEDULE" in u]
    assert len(feed_calls) == 2  # a single retry; the next cycle handles the rest


def test_legacy_13d_feed_can_be_enabled_in_config(world):
    world.recorder.add(feed_url("SC 13D", count=40), atom([]))
    settings = replace(
        world.settings,
        sec=SecConfig(backfill_issuer=False, feed_forms=("4", "SC 13D", "SCHEDULE 13D")),
    )
    result = world.build(settings).run_once()
    assert result.new_filings == 5 and result.errors == 0
    assert any("type=SC+13D" in url for url in world.recorder.urls())
