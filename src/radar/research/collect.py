"""Downloads for phase 2. Everything is cached under `data/phase2/` and resumable.

SEC requests go through `SecClient` (User-Agent, rate limit, retries) at a modest rate, so
phase 2 never competes with the live monitor for the SEC's 10 requests per second.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from radar.backtest import datasets
from radar.backtest.datasets import normalize_symbol, quarters_between
from radar.backtest.marketcap import SharesOutstanding
from radar.backtest.prices import PriceStore
from radar.http import SecClient, SecHttpError
from radar.research.outcomes import ACQUISITION, OutcomeBook, compact_submissions
from radar.research.prices import PriceBook
from radar.research.tape import SecTape
from radar.research.text import html_to_text, risk_factors, tokens

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FLOAT_URL = (
    "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{year}Q{quarter}I.json"
)
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{doc}"
HISTORY_START = date(2016, 10, 1)  # 3 years of look-back before the first 2020 signal
PRICE_START = date(2019, 8, 1)
MIN_MARKET_CAP = 300e6
MIN_FLOAT_FOR_PRICES = 150e6
_CASH = re.compile(
    r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+(?:per\s+share\s+)?in\s+cash"
    r"|\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+per\s+share(?:\s+of\s+[A-Za-z ]{0,40}stock)?,?\s+in\s+cash",
    re.I,
)

Say = Callable[[str], None]


def current_tickers(client: SecClient) -> dict[str, str]:
    """CIK → current ticker (first listed = main share class), in Yahoo format."""
    data = json.loads(client.get_bytes(TICKERS_URL, max_age=7 * 86_400))
    out: dict[str, str] = {}
    for item in data.values():
        out.setdefault(str(item["cik_str"]).zfill(10), item["ticker"].upper().replace(".", "-"))
    return out


def ticker_for(current: dict[str, str], cik: str, symbol: str) -> str:
    return current.get(cik) or normalize_symbol(symbol)


def insider_quarters(client: SecClient, end: date) -> list[Path]:
    links = datasets.dataset_links(client)
    return [datasets.ensure_quarter(client, q, links) for q in quarters_between(HISTORY_START, end)]


def submissions(
    client: SecClient, ciks: list[str], folder: Path, say: Say, workers: int = 4
) -> None:
    """Filing history of each company (with the older pages when needed for 2018+)."""
    folder.mkdir(parents=True, exist_ok=True)

    def one(cik: str) -> None:
        path = folder / f"{cik}.json.gz"
        if path.exists():
            return
        try:
            payload = json.loads(client.get_bytes(SUBMISSIONS_URL.format(cik=cik), store=False))
        except SecHttpError as exc:
            path.write_bytes(gzip.compress(json.dumps({"error": str(exc)}).encode()))
            return
        pages = [payload["filings"]["recent"]]
        dates = pages[0].get("filingDate", [])
        if dates and min(dates) > "2018-01-01":
            for extra in payload["filings"].get("files", []):
                if extra.get("filingTo", "9999") < "2017-06-01":
                    continue
                try:
                    pages.append(
                        json.loads(
                            client.get_bytes(
                                "https://data.sec.gov/submissions/" + extra["name"], store=False
                            )
                        )
                    )
                except SecHttpError:
                    pass
        path.write_bytes(gzip.compress(json.dumps(compact_submissions(payload, pages)).encode()))

    pending = [c for c in ciks if not (folder / f"{c}.json.gz").exists()]
    say(f"submissions: {len(ciks) - len(pending):,} cached, {len(pending):,} to fetch")
    with ThreadPoolExecutor(workers) as pool:
        for done, _ in enumerate(pool.map(one, pending), 1):
            if done % 1000 == 0:
                say(f"  {done:,}/{len(pending):,}")


def public_float(client: SecClient, first_year: int, last_year: int) -> dict[str, float]:
    """Largest public float (10-K cover, XBRL frames) per CIK: a size filter without prices."""
    out: dict[str, float] = {}
    for year in range(first_year, last_year + 1):
        for quarter in range(1, 5):
            try:
                payload = json.loads(
                    client.get_bytes(
                        FLOAT_URL.format(year=year, quarter=quarter), max_age=30 * 86_400
                    )
                )
            except (SecHttpError, ValueError):
                continue
            for item in payload.get("data", []):
                cik = str(item.get("cik")).zfill(10)
                out[cik] = max(out.get(cik, 0.0), float(item.get("val") or 0))
    return out


def prices(
    store_path: Path, groups: list[tuple[str, set[str]]], provider, end: date, say: Say
) -> None:
    store = PriceStore(store_path, provider)
    try:
        for label, tickers in groups:

            def progress(done: int, total: int, label: str = label) -> None:
                if done % 1000 == 0 or done == total:
                    say(f"  {label}: {done:,}/{total:,}")

            report = store.ensure(
                sorted(tickers),
                PRICE_START,
                end,
                fetch_end=date.today(),
                batch_size=20,
                pause=6.0,
                progress=progress,
            )
            say(
                f"prices ({label}): {report.cached:,} cached, {report.downloaded:,} downloaded, "
                f"{report.no_data:,} without data, {len(report.failed):,} failed"
            )
    finally:
        store.close()


def tenk_filings(
    client: SecClient, current: dict[str, str], subs: Path, book: PriceBook, end: date
) -> pd.DataFrame:
    """Every 10-K of companies with a ticker and prices, with market value at the filing date."""
    shares = SharesOutstanding.load(client, quarters_between(date(2017, 10, 1), end))
    rows = []
    for cik, ticker in current.items():
        path = subs / f"{cik}.json.gz"
        series = book.get(ticker)
        if not path.exists() or series is None:
            continue
        payload = json.loads(gzip.decompress(path.read_bytes()))
        for page in payload.get("pages", []):
            for i, form in enumerate(page.get("form", [])):
                if form != "10-K":
                    continue
                filed = date.fromisoformat(page["filingDate"][i])
                if not (date(2018, 1, 1) <= filed <= end):
                    continue
                j = int(np.searchsorted(series.dates, np.datetime64(filed, "D"), side="right")) - 1
                fresh = j >= 0 and (np.datetime64(filed, "D") - series.dates[j]).astype(int) <= 7
                price = float(series.raw_close[j]) if fresh else None
                outstanding = shares.as_of(cik, filed)
                rows.append(
                    {
                        "cik": cik,
                        "ticker": ticker,
                        "filing_date": filed,
                        "acc": page["accessionNumber"][i],
                        "doc": page["primaryDocument"][i],
                        "price": price,
                        "shares": outstanding,
                        "mcap": price * outstanding if price and outstanding else None,
                    }
                )
    frame = pd.DataFrame(rows).drop_duplicates("acc").sort_values(["cik", "filing_date"])
    frame["prev_acc"] = frame.groupby("cik").acc.shift(1)
    frame["prev_date"] = frame.groupby("cik").filing_date.shift(1)
    frame["in_universe"] = (frame.mcap >= MIN_MARKET_CAP) & (frame.filing_date >= date(2019, 1, 1))
    needed = set(frame.loc[frame.in_universe, "acc"]) | set(
        frame.loc[frame.in_universe, "prev_acc"].dropna()
    )
    frame["download"] = frame.acc.isin(needed)
    return frame


def tenk_texts(
    client: SecClient, filings: pd.DataFrame, folder: Path, say: Say, workers: int = 4
) -> None:
    """Downloads each needed 10-K once and keeps only its word counts (gzip JSON)."""
    folder.mkdir(parents=True, exist_ok=True)

    def one(row) -> None:
        path = folder / f"{row.acc}.json.gz"
        if path.exists():
            return
        url = ARCHIVE_URL.format(cik=int(row.cik), folder=row.acc.replace("-", ""), doc=row.doc)
        try:
            raw = client.get_bytes(url, store=False)
        except SecHttpError as exc:
            path.write_bytes(gzip.compress(json.dumps({"error": str(exc)}).encode()))
            return
        text = html_to_text(raw)
        payload = {"tf": tokens(text), "rf": tokens(risk_factors(text)), "words": len(text.split())}
        path.write_bytes(gzip.compress(json.dumps(payload).encode()))

    todo = [
        r
        for r in filings[filings.download].itertuples(index=False)
        if not (folder / f"{r.acc}.json.gz").exists()
    ]
    say(f"10-K texts: {int(filings.download.sum()) - len(todo):,} cached, {len(todo):,} to fetch")
    with ThreadPoolExecutor(workers) as pool:
        for done, _ in enumerate(pool.map(one, todo), 1):
            if done % 1000 == 0:
                say(f"  {done:,}/{len(todo):,}")


def cash_price(text: str) -> float | None:
    """Most frequent "US$ X per share in cash" amount in a merger document."""
    values = [float(a or b) for a, b in _CASH.findall(text)]
    values = [v for v in values if 0.05 <= v <= 5000]
    return Counter(values).most_common(1)[0][0] if values else None


def deal_prices(
    client: SecClient,
    pairs: set[tuple[str, date]],
    book: OutcomeBook,
    tape: SecTape,
    path: Path,
    say: Say,
) -> dict[str, float | None]:
    """Cash price of acquisitions that have no Form 4 code-D price at the close."""
    known: dict[str, float | None] = json.loads(path.read_text()) if path.exists() else {}
    docs: dict[str, tuple[str, str]] = {}
    for cik, day in pairs:
        outcome = book.outcome(cik, day)
        if (
            outcome.kind == ACQUISITION
            and outcome.merger_doc
            and not tape.near(cik, outcome.terminal, before=15, after=5, codes="D")
        ):
            docs[outcome.merger_doc[0]] = (cik, outcome.merger_doc[1])
    pending = {acc: v for acc, v in docs.items() if acc not in known}
    say(f"merger documents: {len(docs) - len(pending):,} cached, {len(pending):,} to read")
    for acc, (cik, doc) in pending.items():
        url = ARCHIVE_URL.format(cik=int(cik), folder=acc.replace("-", ""), doc=doc)
        try:
            known[acc] = cash_price(html_to_text(client.get_bytes(url, store=False))[:400_000])
        except SecHttpError:
            known[acc] = None
    path.write_text(json.dumps(known))
    return known


def insider_issuers(trades: Path, owners: Path, since: str = "2019-11-01") -> list[tuple[str, str]]:
    return duckdb.sql(f"""SELECT DISTINCT t.issuer_cik, t.symbol FROM '{trades}' t
        JOIN '{owners}' o USING (acc)
        WHERE t.code = 'P' AND t.filing_date >= '{since}' AND t.shares * t.price >= 20000
          AND (o.rel ILIKE '%director%' OR o.rel ILIKE '%officer%')""").fetchall()
