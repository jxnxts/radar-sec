"""Insider events for phase 2, built from the SEC Insider Transactions Data Sets.

- `build_tables`: trades (codes P, S, F), the price tape (P, S, F, D) and reporting owners.
- `base_filings`: the base event `insider_buy` (one original Form 4 with open-market purchases
  by an officer or director, ≥ US$ 50k) with the features the variants filter on.
- `csuite_events`: clusters of top executives (V5).

Every feature uses only filings made on or before the signal's filing date.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

from radar.roles import classify_title

MIN_VALUE = 50_000.0
CLUSTER_WINDOW_DAYS = 14
CLUSTER_MIN_VALUE = 100_000.0
COOLDOWN_DAYS = 30
FIRST_BUY_DAYS = 730

NOT_COMMON = (
    r"(?i)preferred|\bpfd\b|warrant|\bnotes?\b|\bbonds?\b|debenture|convertible|"
    r"\brights?\b|\boptions?\b"
)
ENTITY = re.compile(
    r"\b(?:L\.?P\.?|LLC|L\.L\.C\.|FUND|CAPITAL|PARTNERS|HOLDINGS?|MANAGEMENT|TRUST|INC\.?|"
    r"CORP\.?|CORPORATION|LTD\.?|ADVISORS?|INVESTMENTS?|GROUP|COMPANY|CO\.)\b",
    re.I,
)


def _reader(table: str, folders: list[Path]) -> str:
    files = ", ".join(f"'{folder / (table + '.tsv')}'" for folder in folders)
    return (
        f"read_csv([{files}], delim='\\t', header=true, all_varchar=true, quote='', "
        "escape='', strict_mode=false, null_padding=true, union_by_name=true)"
    )


def build_tables(folders: list[Path], out_dir: Path) -> dict[str, Path]:
    """Writes trades, tape and owners as Parquet files and returns their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: out_dir / f"{name}.parquet" for name in ("trades", "tape", "owners")}
    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE sub AS SELECT ACCESSION_NUMBER acc,
          CAST(try_strptime(FILING_DATE, '%d-%b-%Y') AS DATE) filing_date, DOCUMENT_TYPE doc,
          lpad(ltrim(ISSUERCIK, '0'), 10, '0') issuer_cik, coalesce(ISSUERNAME, '') issuer_name,
          coalesce(ISSUERTRADINGSYMBOL, '') symbol, coalesce(REMARKS, '') remarks
        FROM {_reader("SUBMISSION", folders)}
        QUALIFY row_number() OVER (PARTITION BY ACCESSION_NUMBER ORDER BY FILING_DATE) = 1""")
    con.execute(f"""COPY (
        SELECT s.acc, s.filing_date, s.issuer_cik, s.issuer_name, s.symbol,
          CAST(try_strptime(n.TRANS_DATE, '%d-%b-%Y') AS DATE) trans_date, n.TRANS_CODE code,
          coalesce(n.TRANS_ACQUIRED_DISP_CD, '') ad, try_cast(n.TRANS_SHARES AS DOUBLE) shares,
          try_cast(n.TRANS_PRICEPERSHARE AS DOUBLE) price,
          try_cast(n.SHRS_OWND_FOLWNG_TRANS AS DOUBLE) shares_after,
          coalesce(n.DIRECT_INDIRECT_OWNERSHIP, '') di, coalesce(n.SECURITY_TITLE, '') title
        FROM {_reader("NONDERIV_TRANS", folders)} n JOIN sub s ON s.acc = n.ACCESSION_NUMBER
        WHERE s.doc = '4' AND n.TRANS_CODE IN ('P', 'S', 'F')
      ) TO '{paths["trades"]}' (FORMAT parquet)""")
    con.execute(f"""COPY (
        SELECT s.issuer_cik, CAST(try_strptime(n.TRANS_DATE, '%d-%b-%Y') AS DATE) trans_date,
          s.filing_date, n.TRANS_CODE code, try_cast(n.TRANS_PRICEPERSHARE AS DOUBLE) price,
          try_cast(n.TRANS_SHARES AS DOUBLE) shares
        FROM {_reader("NONDERIV_TRANS", folders)} n JOIN sub s ON s.acc = n.ACCESSION_NUMBER
        WHERE s.doc = '4' AND n.TRANS_CODE IN ('P', 'S', 'F', 'D')
          AND try_cast(n.TRANS_PRICEPERSHARE AS DOUBLE) > 0
          AND try_cast(n.TRANS_SHARES AS DOUBLE) > 0
          AND NOT regexp_matches(coalesce(n.SECURITY_TITLE, ''),
              '(?i)preferred|pfd|warrant|note|bond|debenture|convertible|right|option|unit')
      ) TO '{paths["tape"]}' (FORMAT parquet)""")
    con.execute(f"""COPY (
        SELECT o.ACCESSION_NUMBER acc, lpad(ltrim(o.RPTOWNERCIK, '0'), 10, '0') owner_cik,
          coalesce(o.RPTOWNERNAME, '') owner_name, coalesce(o.RPTOWNER_RELATIONSHIP, '') rel,
          coalesce(o.RPTOWNER_TITLE, '') title, s.remarks
        FROM {_reader("REPORTINGOWNER", folders)} o JOIN sub s ON s.acc = o.ACCESSION_NUMBER
        WHERE s.doc = '4'
      ) TO '{paths["owners"]}' (FORMAT parquet)""")
    con.close()
    return paths


def _owners(path: Path) -> pd.DataFrame:
    owners = duckdb.sql(f"SELECT * FROM '{path}'").df()
    owners["is_od"] = owners.rel.str.contains("Director|Officer", case=False)
    owners["is_officer"] = owners.rel.str.contains("Officer", case=False)
    roles = [
        classify_title(t, r) if officer else (False, False)
        for t, r, officer in zip(owners.title, owners.remarks, owners.is_officer, strict=True)
    ]
    owners["is_ceo"] = [ceo for ceo, _ in roles]
    owners["is_cfo"] = [cfo for _, cfo in roles]
    owners["is_entity"] = owners.owner_name.str.contains(ENTITY.pattern, case=False, regex=True)
    return owners


def _purchases(trades: pd.DataFrame) -> pd.DataFrame:
    """Clean open-market purchases of common stock (the phase-1 rules)."""
    p = trades[(trades.code == "P") & (trades.ad != "D") & (trades.shares > 0) & (trades.price > 0)]
    p = p[~p.title.str.contains(NOT_COMMON, na=False, regex=True)]
    return p[p.trans_date.notna() & (p.trans_date <= p.filing_date)].copy()


def stake_increase(lines: pd.DataFrame) -> float:
    """Shares bought ÷ shares held before, from "shares owned following transaction".

    Direct holdings first, then indirect. A position that did not exist before is infinite.
    """
    for kind in ("D", "I", ""):
        part = lines[lines.di == kind] if kind else lines
        part = part[part.shares_after.notna()]
        if len(part):
            bought = part.shares.sum()
            before = part.shares_after.max() - bought
            return float("inf") if before <= 0 else float(bought / before)
    return float("nan")


def base_filings(
    trades_path: Path, owners_path: Path, *, since: str = "2019-11-01"
) -> pd.DataFrame:
    trades = duckdb.sql(f"SELECT * FROM '{trades_path}'").df()
    for column in ("filing_date", "trans_date"):
        trades[column] = pd.to_datetime(trades[column])
    owners = _owners(owners_path)
    owners_by_acc = {acc: group for acc, group in owners.groupby("acc", sort=False)}

    # (owner, issuer) histories, from P and S trades
    pairs = trades[trades.code.isin(["P", "S"]) & trades.trans_date.notna()].merge(
        owners[["acc", "owner_cik"]], on="acc"
    )
    months: dict[tuple, set] = defaultdict(set)
    years: dict[tuple, set] = defaultdict(set)
    for owner, issuer, day in zip(pairs.owner_cik, pairs.issuer_cik, pairs.trans_date, strict=True):
        months[(owner, issuer)].add((day.year, day.month))
        years[(owner, issuer)].add(day.year)
    p = _purchases(trades)
    bought = p.merge(owners[["acc", "owner_cik"]], on="acc")
    buys: dict[tuple, list] = defaultdict(list)
    for owner, issuer, day, filed, acc in zip(
        bought.owner_cik,
        bought.issuer_cik,
        bought.trans_date,
        bought.filing_date,
        bought.acc,
        strict=True,
    ):
        buys[(owner, issuer)].append((day, filed, acc))
    for history in buys.values():
        history.sort()

    p["value"] = p.shares * p.price
    grouped = p.groupby("acc", sort=False)
    filings = grouped.agg(
        filing_date=("filing_date", "first"),
        issuer_cik=("issuer_cik", "first"),
        issuer_name=("issuer_name", "first"),
        symbol=("symbol", "first"),
        value=("value", "sum"),
        shares=("shares", "sum"),
        first_trade=("trans_date", "min"),
        last_trade=("trans_date", "max"),
    ).reset_index()
    filings["avg_price"] = filings.value / filings.shares
    stakes = {acc: stake_increase(lines) for acc, lines in grouped}
    filings["stake_inc"] = filings.acc.map(stakes)
    filings = filings[(filings.value >= MIN_VALUE) & (filings.filing_date >= pd.Timestamp(since))]

    rows = []
    for r in filings.itertuples(index=False):
        own = owners_by_acc.get(r.acc)
        if own is None or not own.is_od.any():
            continue
        ciks = own.owner_cik.tolist()
        y, m = r.last_trade.year, r.last_trade.month
        routine = any(all((y - k, m) in months[(o, r.issuer_cik)] for k in (1, 2, 3)) for o in ciks)
        classified = all({y - 1, y - 2, y - 3} <= years[(o, r.issuer_cik)] for o in ciks)
        first = True
        for o in ciks:
            history = buys.get((o, r.issuer_cik), [])
            start = r.first_trade - timedelta(days=FIRST_BUY_DAYS)
            for day, filed, acc in history[bisect_left(history, (start,)) :]:
                if day >= r.first_trade:
                    break
                if acc != r.acc and filed <= r.filing_date:
                    first = False
                    break
        rows.append(
            {
                **r._asdict(),
                "routine": routine,
                "cmp_classified": classified,
                "opportunistic": classified and not routine,
                "first_buy": first,
                "is_ceo": bool(own.is_ceo.any()),
                "is_cfo": bool(own.is_cfo.any()),
                "owner_names": " / ".join(own.owner_name.tolist()[:3]),
                "owner_ciks": ",".join(ciks),
            }
        )
    return pd.DataFrame(rows)


def csuite_events(
    trades_path: Path, owners_path: Path, *, since: str = "2019-10-01"
) -> pd.DataFrame:
    """V5: ≥ 2 distinct non-entity officer/director buyers in 14 days including the CEO and the
    CFO, or ≥ 3 distinct officers; ≥ US$ 100k; one signal per issuer per 30 days."""
    trades = duckdb.sql(f"SELECT * FROM '{trades_path}'").df()
    for column in ("filing_date", "trans_date"):
        trades[column] = pd.to_datetime(trades[column])
    owners = _owners(owners_path)
    people = owners[owners.is_od & ~owners.is_entity]
    p = _purchases(trades)
    p = p[p.filing_date >= pd.Timestamp(since)].merge(
        people[["acc", "owner_cik", "is_ceo", "is_cfo", "is_officer"]], on="acc"
    )
    events = []
    for issuer, group in p.groupby("issuer_cik", sort=False):
        group = group.sort_values(["filing_date", "acc"])
        last_signal = None
        for day in sorted(group.filing_date.unique()):
            day = pd.Timestamp(day)
            if last_signal is not None and (day - last_signal).days < COOLDOWN_DAYS:
                continue
            start = day - timedelta(days=CLUSTER_WINDOW_DAYS)
            window = group[
                (group.filing_date >= start)
                & (group.filing_date <= day)
                & (group.trans_date >= start)
            ]
            if window.empty or not (window.filing_date == day).any():
                continue
            lines = window.drop_duplicates(["acc", "trans_date", "shares", "price", "shares_after"])
            total = float((lines.shares * lines.price).sum())
            who = window.groupby("owner_cik").agg(
                ceo=("is_ceo", "any"), cfo=("is_cfo", "any"), officer=("is_officer", "any")
            )
            officers = int(who.officer.sum())
            both = bool(who.ceo.any() and who.cfo.any() and len(who) >= 2)
            if total < CLUSTER_MIN_VALUE or not (both or officers >= 3):
                continue
            last_signal = day
            trigger = window[window.filing_date == day].iloc[0]
            events.append(
                {
                    "issuer_cik": issuer,
                    "issuer_name": trigger.issuer_name,
                    "symbol": trigger.symbol,
                    "filing_date": day,
                    "acc": trigger.acc,
                    "value": total,
                    "avg_price": total / float(lines.shares.sum()),
                    "last_trade": lines.trans_date.max(),
                    "n_insiders": len(who),
                    "ceo_and_cfo": both,
                    "n_officers": officers,
                }
            )
    return pd.DataFrame(events)


def cooldown(frame: pd.DataFrame, days: int = COOLDOWN_DAYS) -> pd.DataFrame:
    """Keeps one event per issuer per `days` days (the first one)."""
    frame = frame.sort_values(["cik", "filing_date"])
    keep, last = [], {}
    for r in frame.itertuples():
        previous = last.get(r.cik)
        if previous is not None and (r.filing_date - previous).days < days:
            keep.append(False)
            continue
        last[r.cik] = r.filing_date
        keep.append(True)
    return frame[keep]
