"""End-to-end backtest, offline: simulated SEC and Yahoo, real 2023Q1 data."""

import io
import json
import zipfile
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest
from rich.console import Console

from radar.backtest import datasets
from radar.backtest.prices import PriceStore
from radar.backtest.runner import run_backtest
from radar.config import BacktestConfig
from tests.conftest import FIXTURES

SLICE = FIXTURES / "insider_2023q1"
BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
START, END, TODAY = date(2023, 1, 1), date(2023, 3, 31), date(2024, 1, 31)

# (first-day price, daily change). The indices rise; the stocks fall.
MARKET = {
    "SPY": (380.0, 0.0010),
    "IWM": (175.0, 0.0005),
    "INTC": (29.0, -0.0010),
    "CBNK": (19.5, -0.0015),
    "MTDR": (55.0, -0.0010),
    # CTM (Castellum) is left out: simulates a ticker without prices on Yahoo.
}


class FakeYahoo:
    def __init__(self, market=MARKET):
        self.market = market
        self.requests: list[list[str]] = []

    def fetch(self, tickers, start, end):
        self.requests.append(list(tickers))
        days = pd.bdate_range(start, end)
        data, errors = {}, {}
        for ticker in tickers:
            if ticker not in self.market:
                errors[ticker] = "possibly delisted; no timezone found"
                continue
            first, daily = self.market[ticker]
            prices = first * (1 + daily) ** np.arange(len(days))
            data[ticker] = pd.DataFrame(
                {"close": prices, "adj_close": prices, "split": 0.0}, index=days
            )
        return data, errors


def archive(tables: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, content in tables.items():
            bundle.writestr(f"{name}.tsv", content)
    return buffer.getvalue()


@pytest.fixture
def sec(recorder, make_client):
    real = {t: (SLICE / f"{t}.tsv").read_bytes() for t in datasets.TABLES}
    headers_only = {t: content.split(b"\n", 1)[0] + b"\n" for t, content in real.items()}
    recorder.add(
        datasets.DATASETS_PAGE,
        '<a href="/files/structureddata/data/insider-transactions-data-sets/2022q4_form345.zip">x</a>'
        '<a href="/files/structureddata/data/insider-transactions-data-sets/2023q1_form345.zip">y</a>',
    )
    recorder.add(f"{BASE}/2022q4_form345.zip", archive(headers_only))
    recorder.add(f"{BASE}/2023q1_form345.zip", archive(real))
    recorder.add(
        "https://www.sec.gov/files/company_tickers.json",
        json.dumps(
            {
                "0": {"cik_str": 50863, "ticker": "INTC", "title": "INTEL CORP"},
                "1": {"cik_str": 1520006, "ticker": "MTDR", "title": "Matador Resources Co"},
            }
        ),
    )
    recorder.add(
        "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/*",
        json.dumps({"data": [{"cik": 50863, "end": "2022-10-21", "val": 4_127_000_000}]}),
    )
    return make_client()


@pytest.fixture
def outcome(settings, sec):
    provider = FakeYahoo()
    result = run_backtest(
        settings,
        sec,
        START,
        END,
        console=Console(quiet=True),
        provider=provider,
        today=TODAY,
    )
    result.provider = provider
    return result


def test_backtest_writes_reports_in_both_languages_and_csv(outcome, settings):
    assert outcome.report_path == settings.reports_dir / "backtest-2024-01-31.md"
    assert outcome.report_paths == {
        "en": settings.reports_dir / "backtest-2024-01-31.md",
        "pt-BR": settings.reports_dir / "backtest-2024-01-31.pt-BR.md",
    }
    assert outcome.csv_path == settings.reports_dir / "backtest-2024-01-31-signals.csv"
    report = outcome.report_path.read_text(encoding="utf-8")
    for section in (
        "# Backtest radar-sec — 2023-01-01 to 2023-03-31",
        "## Verdict",
        "## Data funnel",
        "## Results by signal and horizon",
        "## Against IWM",
        "## Liquidity filters",
        "## Breakdown by year",
        "## Extremes",
        "## Limitations",
        "Survivorship bias",
    ):
        assert section in report
    report_pt = outcome.report_paths["pt-BR"].read_text(encoding="utf-8")
    for section in (
        "# Backtest radar-sec — 2023-01-01 a 2023-03-31",
        "## Veredito",
        "## Funil dos dados",
        "## Resultado por sinal e prazo",
        "## Contra o IWM",
        "## Filtros de liquidez",
        "## Quebra por ano",
        "## Extremos",
        "## Limitações",
        "Viés de sobrevivência",
    ):
        assert section in report_pt
    table = pd.read_csv(outcome.csv_path)
    assert len(table) == len(outcome.signals) == 5
    assert {
        "type",
        "signal_date",
        "ticker",
        "status",
        "ret_1m",
        "excess_spy_3m",
        "excess_iwm_6m",
        "market_cap",
        "explanation",
    } <= set(table.columns)
    assert table["explanation"].str.contains("on the open market").all()


def test_each_signal_is_classified(outcome):
    status = {(r.type, r.ticker): r.status for r in outcome.signals.itertuples()}
    assert status == {
        ("big_officer_buy", "INTC"): "ok",
        ("cluster_buy", "INTC"): "ok",
        ("cluster_buy", "CBNK"): "ok",
        ("cluster_buy", "MTDR"): "ok",
        ("cluster_buy", "CTM"): "no_prices",  # counted as discarded in the report
    }
    sources = dict(zip(outcome.signals["ticker"], outcome.signals["ticker_source"], strict=False))
    assert sources["INTC"] == "sec_current" and sources["CBNK"] == "form4"


def test_entry_cost_and_excess_are_computed_as_documented(outcome):
    row = outcome.signals.query("type == 'big_officer_buy' and ticker == 'INTC'").iloc[0]
    assert row.signal_date == date(2023, 2, 2)
    assert row.entry_date == date(2023, 2, 3)  # session after the filing
    assert row.exit_date_1m == date(2023, 3, 3)
    assert row.exit_date_3m == date(2023, 5, 3)
    assert row.exit_date_6m == date(2023, 8, 3)

    for months in (1, 3, 6):
        sessions = len(pd.bdate_range(row.entry_date, row[f"exit_date_{months}m"])) - 1
        gross = (1 - 0.0010) ** sessions - 1
        spy = (1 + 0.0010) ** sessions - 1
        assert row[f"gross_{months}m"] == pytest.approx(gross)
        assert row[f"ret_{months}m"] == pytest.approx(gross - 0.002)  # 0.2% cost
        assert row[f"spy_{months}m"] == pytest.approx(spy)
        assert row[f"excess_spy_{months}m"] == pytest.approx(gross - 0.002 - spy)
        assert row[f"excess_iwm_{months}m"] == pytest.approx(
            gross - 0.002 - ((1.0005) ** sessions - 1)
        )


def test_market_cap_uses_point_in_time_shares(outcome):
    intel = outcome.signals.query("ticker == 'INTC'").iloc[0]
    assert intel.shares_outstanding == 4_127_000_000
    assert intel.market_cap == pytest.approx(4_127_000_000 * intel.avg_buy_price)
    others = outcome.signals.query("ticker != 'INTC'")
    assert others["market_cap"].isna().all()  # no data: left out of the filter


def test_report_says_plainly_when_the_signals_lose_to_the_index(outcome):
    report = outcome.report_path.read_text(encoding="utf-8")
    assert "the signals do NOT beat SPY" in report
    assert "do NOT beat SPY" in outcome.verdict
    assert "with statistical significance" not in report
    report_pt = outcome.report_paths["pt-BR"].read_text(encoding="utf-8")
    assert "os sinais NÃO batem o SPY" in report_pt


def test_report_counts_what_was_discarded(outcome):
    report = outcome.report_path.read_text(encoding="utf-8")
    assert "1 of 5 signals (20%) were discarded without being measured" in report
    assert "1 for a ticker without prices" in report
    report_pt = outcome.report_paths["pt-BR"].read_text(encoding="utf-8")
    assert "1 de 5 sinais (20%) foram descartados sem medir" in report_pt


def test_report_celebrates_only_with_evidence(settings, sec):
    # Same scenario with the stocks rising strongly: positive mean and median, but only
    # two months of signals. The report cannot declare victory with so little.
    winners = {**MARKET, "INTC": (29.0, 0.004), "CBNK": (15.0, 0.004), "MTDR": (40.0, 0.004)}
    result = run_backtest(
        settings,
        sec,
        START,
        END,
        console=Console(quiet=True),
        provider=FakeYahoo(winners),
        today=TODAY,
    )
    assert "do NOT beat" not in result.verdict
    assert "there is no solid evidence" in result.verdict
    assert "without statistical significance" in result.verdict


def test_second_run_uses_the_price_cache(settings, sec, outcome):
    again = FakeYahoo()
    run_backtest(
        settings, sec, START, END, console=Console(quiet=True), provider=again, today=TODAY
    )
    assert again.requests == []
    assert sorted(t for batch in outcome.provider.requests for t in batch) == [
        "CBNK",
        "CTM",
        "INTC",
        "IWM",
        "MTDR",
        "SPY",
    ]


def test_cost_is_configurable(settings, sec):
    free = replace(settings, backtest=BacktestConfig(cost_roundtrip=0.0))
    result = run_backtest(
        free, sec, START, END, console=Console(quiet=True), provider=FakeYahoo(), today=TODAY
    )
    row = result.signals.query("status == 'ok'").iloc[0]
    assert row.ret_1m == pytest.approx(row.gross_1m)


# ----------------------------------------------------------------- price cache


class Flaky:
    """A Yahoo that rate-limits the first calls."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def fetch(self, tickers, start, end):
        self.calls += 1
        if self.calls <= self.failures:
            return {}, {t: "Too Many Requests. Rate limited. Try after a while." for t in tickers}
        return FakeYahoo().fetch(tickers, start, end)


def test_rate_limited_tickers_wait_and_retry_instead_of_becoming_missing(tmp_path):
    waits: list[float] = []
    store = PriceStore(tmp_path / "p.duckdb", Flaky(failures=2))
    report = store.ensure(
        ["SPY", "CTM"], date(2023, 1, 2), date(2023, 6, 30), sleep=waits.append, pause=0
    )
    assert report.downloaded == 1 and report.no_data == 1 and report.failed == []
    assert [w for w in waits if w] == [60.0, 120.0]  # growing wait before retrying
    assert set(store.load(["SPY", "CTM"])) == {"SPY"}
    store.close()


def test_persistent_rate_limit_is_reported_not_cached_as_missing(tmp_path):
    store = PriceStore(tmp_path / "p.duckdb", Flaky(failures=99))
    report = store.ensure(
        ["SPY"], date(2023, 1, 2), date(2023, 6, 30), sleep=lambda s: None, retries=2
    )
    assert report.failed == ["SPY"] and report.no_data == 0
    # Since it was not stored as "no data", the next run tries again.
    retry = store.ensure(
        ["SPY"], date(2023, 1, 2), date(2023, 6, 30), sleep=lambda s: None, retries=0
    )
    assert retry.cached == 0
    store.close()


def test_cache_is_reused_only_when_it_covers_the_period(tmp_path):
    provider = FakeYahoo()
    store = PriceStore(tmp_path / "p.duckdb", provider)
    store.ensure(["SPY"], date(2023, 1, 2), date(2023, 6, 30), sleep=lambda s: None)
    store.ensure(["SPY"], date(2023, 2, 1), date(2023, 5, 31), sleep=lambda s: None)
    assert len(provider.requests) == 1
    store.ensure(["SPY"], date(2023, 1, 2), date(2023, 12, 29), sleep=lambda s: None)
    assert len(provider.requests) == 2  # period larger than the stored one: download again
    store.close()


# ------------------------------------------------------------ report re-render


def test_reports_can_be_rendered_again_from_the_csv(outcome, settings, sec):
    from radar.backtest.runner import rerender_reports

    written = {
        lang: path.read_text(encoding="utf-8") for lang, path in outcome.report_paths.items()
    }
    for path in outcome.report_paths.values():
        path.unlink()
    used, paths = rerender_reports(
        settings, sec, START, END, csv_path=outcome.csv_path, console=Console(quiet=True)
    )
    assert used == outcome.csv_path
    for lang, path in paths.items():
        again = path.read_text(encoding="utf-8")
        # Only the "generated on" line may differ (it comes from the CSV time).
        assert again.splitlines()[3:] == written[lang].splitlines()[3:]


def test_a_csv_from_the_first_version_is_converted(outcome, settings, sec):
    from radar import legacy
    from radar.backtest.runner import read_signals_csv, rerender_reports

    old_names = {new: old for old, new in legacy.CSV_COLUMNS.items()}
    table = pd.read_csv(outcome.csv_path)

    def old_column(name: str) -> str:
        if name in old_names:
            return old_names[name]
        for old, new in (("data_saida_", "exit_date_"), ("bruto_", "gross_"), ("exc_", "excess_")):
            if name.startswith(new):
                return old + name.removeprefix(new)
        return name

    old_status = {new: old for old, new in legacy.OUTCOME_STATUS.items()}
    table["status"] = table["status"].map(lambda s: old_status.get(s, s))
    table["ticker_source"] = table["ticker_source"].replace({"sec_current": "sec_atual"})
    table["explanation"] = "texto antigo"
    legacy_csv = settings.reports_dir / "backtest-2024-01-31-sinais.csv"
    table.rename(columns=old_column).to_csv(legacy_csv, index=False, float_format="%.6f")
    outcome.csv_path.unlink()

    upgraded = read_signals_csv(legacy_csv)
    assert set(upgraded["status"]) == {"ok", "no_prices"}
    used, paths = rerender_reports(
        settings,
        sec,
        START,
        END,
        csv_path=legacy_csv,
        langs=("pt-BR",),
        console=Console(quiet=True),
    )
    assert used == outcome.csv_path and set(paths) == {"pt-BR"}
    converted = pd.read_csv(used)
    assert "type" in converted and "tipo" not in converted
    assert converted["explanation"].str.contains("on the open market").all()
    assert "1 de 5 sinais (20%) foram descartados" in paths["pt-BR"].read_text(encoding="utf-8")


def test_backtest_drops_insider_buys_of_funds_and_says_so(settings, sec, recorder):
    # Matador registered as a closed-end investment office (SIC 6726) in the fake registry.
    recorder.add(
        "https://data.sec.gov/submissions/CIK0001520006.json",
        json.dumps({"sic": "6726", "filings": {"recent": {"form": ["10-Q"]}}}),
    )
    result = run_backtest(
        settings, sec, START, END, console=Console(quiet=True), provider=FakeYahoo(), today=TODAY
    )
    assert "MTDR" not in set(result.signals["ticker"])
    assert len(result.signals) == 4
    report = result.report_path.read_text(encoding="utf-8")
    assert (
        "| Insider buy signals dropped: issuer is a fund or similar vehicle "
        "(big_officer_buy: 0, cluster_buy: 1) | 1 |" in report
    )
    report_pt = result.report_paths["pt-BR"].read_text(encoding="utf-8")
    assert "emissor é um fundo ou veículo similar (big_officer_buy: 0, cluster_buy: 1) | 1 |" in (
        report_pt
    )


def test_rerendering_an_old_csv_drops_the_funds_it_still_has(outcome, settings, sec, recorder):
    from radar.backtest.runner import rerender_reports

    recorder.add(
        "https://data.sec.gov/submissions/CIK0001520006.json",
        json.dumps({"sic": "", "filings": {"recent": {"form": ["NPORT-P"]}}}),
    )
    _, paths = rerender_reports(
        settings, sec, START, END, csv_path=outcome.csv_path, console=Console(quiet=True)
    )
    report = paths["en"].read_text(encoding="utf-8")
    assert "(big_officer_buy: 0, cluster_buy: 1) | 1 |" in report
    assert "MTDR" not in report
