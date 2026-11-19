"""The dashboard's external sources behind their interfaces: prices, logos, sectors, report."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from radar.api.backtest_summary import load_summary, number, parse_report
from radar.api.hub import Hub
from radar.api.logos import LogoService, LogoSource, png_size, usable
from radar.api.prices import INDICES, BacktestHistory, PriceService, downsample
from radar.sectors import SECTORS, UNKNOWN, SectorLookup, sector_for_sic
from tests.api_helpers import FakePrices, png

REPORTS = Path(__file__).parent.parent / "reports"

# --------------------------------------------------------------------- prices


def test_price_service_tracks_indices_plus_recent_signal_tickers():
    source = FakePrices()
    service = PriceService(source, Hub(), tracked=lambda: ["MP", "SPY", "COUR"])

    tick = service.refresh()

    assert source.quote_calls == [[*INDICES, "MP", "COUR"]]  # without repeating SPY
    assert tick["state"] == "ok" and tick["delay_minutes"] == 15 and tick["source"] == "Test source"
    spy = tick["quotes"]["SPY"]
    assert spy["price"] == 100.0 and spy["change_pct"] == pytest.approx(100 / 98 - 1)
    assert spy["name"] == "S&P 500" and spy["spark"] == [98.0, 99.0, 100.0]


def test_price_failure_keeps_last_quotes_and_reports_the_error():
    source = FakePrices()
    service = PriceService(source, Hub())
    service.refresh()
    source.fail = True

    tick = service.refresh()

    assert tick["state"] == "error" and "source is down" in tick["error"]
    assert set(tick["quotes"]) == set(INDICES)  # the screen keeps the last value


def test_price_history_is_cached_for_closed_periods(tmp_path):
    source = FakePrices()
    service = PriceService(source, Hub(), cache_dir=tmp_path)

    first = service.history("ACME", date(2020, 1, 1), date(2020, 2, 1))
    again = service.history("ACME", date(2020, 1, 1), date(2020, 2, 1))

    assert first == again and len(source.history_calls) == 1
    assert first["kind"] == "ohlc" and len(first["bars"]) == 2


def test_price_history_falls_back_to_the_backtest_cache(tmp_path):
    import duckdb

    path = tmp_path / "prices.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE prices (ticker VARCHAR, day DATE, close DOUBLE, adj_close DOUBLE, split DOUBLE)"
    )
    con.execute("INSERT INTO prices VALUES ('ACME', DATE '2020-01-02', 10.5, 9.9, 0)")
    con.close()
    source = FakePrices()
    source.fail = True
    service = PriceService(source, Hub(), cache_dir=tmp_path, fallback=BacktestHistory(path))

    body = service.history("ACME", date(2020, 1, 1), date(2020, 2, 1))

    assert body["kind"] == "close" and body["source"] == "backtest cache"
    assert body["bars"] == [
        {"t": "2020-01-02", "o": 10.5, "h": 10.5, "l": 10.5, "c": 10.5, "v": None}
    ]

    empty = service.history("NONE", date(2020, 1, 1), date(2020, 2, 1))
    assert empty["bars"] == [] and "source is down" in empty["error"]
    assert not list(
        (tmp_path / "price-history").glob("NONE*")
    )  # a failure does not go to the cache


def test_downsample_keeps_first_and_last_points():
    values = [float(i) for i in range(400)]
    sample = downsample(values, 40)
    assert len(sample) == 40 and sample[0] == 0.0 and sample[-1] == 399.0
    assert downsample([1.0, 2.0], 40) == [1.0, 2.0]


# --------------------------------------------------------------------- logos


def logo_service(tmp_path, handler):
    sources = (
        LogoSource("principal", "https://logos.example/a/{ticker}.png"),
        LogoSource("reserva", "https://logos.example/b/{ticker}.png"),
    )
    return LogoService(tmp_path, sources=sources, transport=httpx.MockTransport(handler))


def test_logo_is_fetched_once_and_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=png(128, 128))

    service = logo_service(tmp_path, handler)

    assert service.get("mp") == png(128, 128)
    assert service.get("MP") == png(128, 128)
    assert len(calls) == 1 and (tmp_path / "logos" / "MP.png").exists()
    # The request only carries the ticker and a generic User-Agent: nothing identifying the user.
    assert calls[0].headers["user-agent"] == "radar-sec-dashboard/0.1"
    assert "@" not in str(calls[0].url) + calls[0].headers["user-agent"]


def test_logo_falls_back_to_second_source_and_rejects_tiny_images(tmp_path):
    def handler(request):
        if "/a/" in str(request.url):
            return httpx.Response(200, content=png(16, 16))  # tiny icon: useless
        return httpx.Response(200, content=png(96, 96))

    assert logo_service(tmp_path, handler).get("FUN") == png(96, 96)


def test_missing_logo_is_remembered_but_network_failures_are_not(tmp_path):
    calls = []

    def missing(request):
        calls.append(request)
        return httpx.Response(404)

    service = logo_service(tmp_path, missing)
    assert service.get("ZZZZ") is None and service.get("ZZZZ") is None
    assert len(calls) == 2  # two sources, once each

    def broken(request):
        calls.append(request)
        raise httpx.ConnectError("no network")

    service = logo_service(tmp_path, broken)
    assert service.get("AAPL") is None and service.get("AAPL") is None
    assert len(calls) == 6  # retried: a network failure does not become "does not exist"


def test_logo_rejects_bad_tickers_and_non_images(tmp_path):
    service = logo_service(tmp_path, lambda request: httpx.Response(200, content=b"<svg/>"))
    assert service.get("../../etc/passwd") is None
    assert service.get("AAPL") is None
    assert png_size(png(250, 120)) == (250, 120) and png_size(b"GIF89a") is None
    assert usable(png(48, 48)) and not usable(png(128, 30)) and not usable(b"")


# -------------------------------------------------------------------- sectors


@pytest.mark.parametrize(
    ("sic", "sector"),
    [
        ("2834", "Healthcare"),
        ("7372", "Technology"),
        ("6022", "Financials"),
        ("6798", "Real Estate"),
        ("1311", "Energy"),
        ("4911", "Utilities"),
        ("1040", "Materials"),
        ("3711", "Industrials"),
        ("5812", "Consumer"),
        ("4813", "Communication"),
        ("8742", "Services"),
        ("", UNKNOWN),
        (None, UNKNOWN),
        ("abc", UNKNOWN),
        ("9995", UNKNOWN),
    ],
)
def test_sector_for_sic(sic, sector):
    assert sector_for_sic(sic) == sector
    assert sector in SECTORS


def test_sector_lookup_keeps_only_the_sic_on_disk(make_client, recorder, tmp_path):
    url = "https://data.sec.gov/submissions/CIK0000001234.json"
    recorder.add(url, json.dumps({"sic": "2834", "name": "x" * 5000}))
    client = make_client()
    lookup = SectorLookup(client, flush_every=1)

    assert lookup.lookup("0000001234") == ("2834", "Healthcare")
    assert lookup.lookup("1234") == ("2834", "Healthcare")
    assert recorder.urls().count(url) == 1
    # The large SEC JSON is not cached; only the small file with the SIC.
    assert json.loads((tmp_path / "cache" / "sectors.json").read_text()) == {"1234": "2834"}
    assert not (tmp_path / "cache" / "data.sec.gov").exists()

    assert SectorLookup(client).lookup("1234") == ("2834", "Healthcare")  # another run: from disk
    assert recorder.urls().count(url) == 1
    assert lookup.lookup("999") is None  # no SEC answer: try again later
    assert lookup.get("999") == ("", UNKNOWN)


def test_sector_cache_moves_from_its_old_file_name(make_client, tmp_path):
    client = make_client()
    old = tmp_path / "cache" / "setores.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"1234": "7372"}))
    assert SectorLookup(client).lookup("1234") == ("7372", "Technology")
    assert not old.exists() and (tmp_path / "cache" / "sectors.json").exists()
    old.write_text(json.dumps({"1234": "1", "99": "1311"}))  # written again by an old process
    assert SectorLookup(client).get("99") == ("1311", "Energy")
    assert SectorLookup(client).get("1234") == ("7372", "Technology")  # the new file wins
    assert not old.exists()


# --------------------------------------------------------------------- report


def test_number_parses_the_report_formats():
    assert number("4,903") == 4903
    assert number("**-6.5%**") == pytest.approx(-0.065)
    assert number("+1,449.0%") == pytest.approx(14.49)
    assert number("4,903 (74%)") == 4903
    assert number("0.2") == 0.2 and number("-0.5") == -0.5 and number("$5.00") == 5.0
    assert number("n/a") is None and number("") is None


def test_number_parses_the_portuguese_report_formats():
    assert number("4.903", "pt-BR") == 4903
    assert number("**-6,5%**", "pt-BR") == pytest.approx(-0.065)
    assert number("+0,8%", "pt-BR") == pytest.approx(0.008)
    assert number("4.903 (74%)", "pt-BR") == 4903
    assert number("0,2", "pt-BR") == 0.2 and number("-0,5", "pt-BR") == -0.5
    assert number("n/d", "pt-BR") is None


def test_summary_of_the_reference_report_says_signals_lost_to_spy():
    summary = load_summary(REPORTS)

    assert summary["period"] == {"start": "2020-01-01", "end": "2025-12-31"}
    assert summary["beats_benchmark"] is False
    assert summary["report"] == "backtest-2026-11-18.md"
    assert summary["generated_at"] == "2026-11-18 00:03"
    assert set(summary["verdict"]) == set(summary["caveat"]) == {"en", "pt-BR"}
    assert summary["verdict"]["en"].startswith("Conclusion: the signals do NOT beat SPY.")
    assert summary["verdict"]["pt-BR"].startswith("Conclusão: os sinais NÃO batem o SPY.")
    assert summary["caveat"]["en"].startswith("Beware of survivorship bias")
    assert summary["caveat"]["pt-BR"].startswith("Atenção ao viés de sobrevivência")
    assert summary["rows"][0]["label"] == "Large CEO/CFO buy"
    rows = {(r["type"], r["horizon_months"]): r for r in summary["rows"]}
    assert len(rows) == 6
    cluster = rows[("cluster_buy", 6)]
    assert cluster["n"] == 4903 and cluster["excess_median"] == pytest.approx(-0.065)
    assert cluster["beats"] == pytest.approx(0.406) and cluster["t_stat"] == -0.5
    officer = rows[("big_officer_buy", 1)]
    assert officer["n"] == 1746 and officer["excess_mean"] == pytest.approx(-0.009)
    assert summary["max_t"] == 0.2
    assert summary["funnel"]["generated"] == 9018 and summary["funnel"]["measured"] == 6649
    assert summary["funnel"]["unmeasured_share"] == pytest.approx(0.2627, abs=1e-3)
    assert len(summary["by_year"]) == 12
    first = next(
        r for r in summary["by_year"] if r["type"] == "big_officer_buy" and r["year"] == 2020
    )
    assert first["excess_median_6m"] == pytest.approx(0.025)
    assert len(summary["rows_iwm"]) == 6 and len(summary["rows_liquid"]) == 6


def test_summary_without_report_is_none_and_partial_report_degrades(tmp_path):
    assert load_summary(tmp_path) is None
    partial = parse_report(
        "# Backtest radar-sec — 2021-01-01 to 2021-12-31\n\n## Verdict\n\nNone.\n"
    )
    assert partial["rows"] == [] and partial["verdict"] == {"en": "None."}
    assert partial["funnel"] == {} and partial["beats_benchmark"] is False
    assert partial["period"] == {"start": "2021-01-01", "end": "2021-12-31"}


def test_summary_falls_back_to_english_without_a_translated_report(tmp_path):
    (tmp_path / "backtest-2021-12-31.md").write_text(
        "# Backtest radar-sec — 2021-01-01 to 2021-12-31\n\n## Verdict\n\nNo.\n\n> Careful.\n"
    )
    summary = load_summary(tmp_path)
    assert summary["verdict"] == {"en": "No.", "pt-BR": "No."}
    assert summary["caveat"] == {"en": "Careful.", "pt-BR": "Careful."}
    (tmp_path / "backtest-2021-12-31.pt-BR.md").write_text(
        "# Backtest radar-sec — 2021-01-01 a 2021-12-31\n\n## Veredito\n\nNão.\n\n> Cuidado.\n"
    )
    summary = load_summary(tmp_path)
    assert summary["verdict"] == {"en": "No.", "pt-BR": "Não."}
    assert summary["caveat"]["pt-BR"] == "Cuidado."


def test_summary_carries_the_phase2_verdict():
    phase2 = load_summary(REPORTS)["phase2"]

    assert phase2["date"] == "2026-11-18" and phase2["passed"] == []
    assert {v["verdict"] for v in phase2["variants"]} == {"discard"}
    keys = [v["key"] for v in phase2["variants"]]
    assert "R2_big_officer_buy" in keys and "V8_lazy_nonchangers" in keys
    assert "V0_text_covered" not in keys  # a comparison set, not a candidate
    survivorship = phase2["survivorship"]
    assert survivorship["generated"] == 9018
    assert survivorship["measured_corrected"] > survivorship["measured_raw"]


def test_summary_without_phase2_or_with_a_broken_file(tmp_path):
    (tmp_path / "backtest-2021-12-31.md").write_text(
        "# Backtest radar-sec — 2021-01-01 to 2021-12-31\n\n## Verdict\n\nNo.\n"
    )
    assert load_summary(tmp_path)["phase2"] is None
    (tmp_path / "phase2-2021-12-31.json").write_text("{not json")
    assert load_summary(tmp_path)["phase2"] is None
