from datetime import date

import pytest

from radar.feed import feed_url, fetch_current, group_entries, parse_feed
from tests.conftest import FIXTURES


def test_parse_feed_real_form4():
    entries = parse_feed((FIXTURES / "feed_form4.atom.xml").read_bytes())
    assert len(entries) == 40
    first = entries[0]
    assert first.accession == "0001444157-26-000031"
    assert first.form == "4"
    assert first.name == "Rothenstein David M"
    assert first.cik == "1444157"
    assert first.role == "Reporting"
    assert first.filed_date == date(2026, 11, 17)
    assert first.index_url.endswith("0001444157-26-000031-index.htm")


def test_group_entries_keeps_one_per_filing_and_prefers_issuer():
    refs = group_entries(parse_feed((FIXTURES / "feed_form4.atom.xml").read_bytes()))
    assert len(refs) == 20
    assert len({r.accession for r in refs}) == 20
    ciena = next(r for r in refs if r.accession == "0001444157-26-000031")
    assert ciena.company == "CIENA CORP"
    assert ciena.cik == "936395"
    assert ciena.filers == ("Rothenstein David M",)
    assert ciena.txt_url == (
        "https://www.sec.gov/Archives/edgar/data/936395/000144415726000031/0001444157-26-000031.txt"
    )


def test_parse_feed_real_13d_distinguishes_amendments():
    refs = group_entries(parse_feed((FIXTURES / "feed_13d.atom.xml").read_bytes()))
    forms = {r.form for r in refs}
    assert forms == {"SCHEDULE 13D", "SCHEDULE 13D/A"}
    atlas = next(r for r in refs if r.accession == "0001104659-26-129242")
    assert atlas.form == "SCHEDULE 13D/A"
    assert atlas.company == "Atlas Energy Solutions Inc."  # the subject company, not the filer


def test_feed_url_rejects_counts_the_sec_does_not_accept():
    assert "count=100" in feed_url("4")
    assert "type=SCHEDULE+13D" in feed_url("SCHEDULE 13D")
    with pytest.raises(ValueError):
        feed_url("4", count=5)


def _feed(accessions: list[str]) -> str:
    entries = "".join(
        f"""<entry><title>4 - ACME CORP (0000001234) (Issuer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1234/{a.replace("-", "")}/{a}-index.htm"/>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-11-17 &lt;b&gt;AccNo:&lt;/b&gt; {a}</summary>
<updated>2026-11-17T20:45:36-05:00</updated>
<category scheme="https://www.sec.gov/" label="form type" term="4"/>
<id>urn:tag:sec.gov,2008:accession-number={a}</id></entry>"""
        for a in accessions
    )
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'


def test_fetch_current_pages_until_it_reaches_a_known_filing(make_client, recorder):
    page1 = [f"0000001234-26-{i:06d}" for i in range(10)]
    page2 = [f"0000001234-26-{i:06d}" for i in range(10, 20)]
    recorder.add(feed_url("4", start=0, count=10), _feed(page1))
    recorder.add(feed_url("4", start=10, count=10), _feed(page2))
    recorder.add(feed_url("4", start=20, count=10), _feed([]))

    known = {page2[3]}
    refs = fetch_current(make_client(), "4", is_known=known.__contains__, count=10, max_pages=5)

    assert len(refs) == 20
    assert len(recorder.calls) == 2  # stopped at the page that had a known filing


def test_fetch_current_stops_on_short_page(make_client, recorder):
    recorder.add(feed_url("4", start=0, count=10), _feed(["0000001234-26-000001"]))
    refs = fetch_current(make_client(), "4", count=10, max_pages=5)
    assert [r.accession for r in refs] == ["0000001234-26-000001"]
    assert len(recorder.calls) == 1
