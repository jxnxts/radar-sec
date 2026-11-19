"""Operational SQLite database: filings seen, extracted data, signals and AI usage.

The schema version lives in `PRAGMA user_version`. Opening an older database
migrates it in place (see `_migrate`), inside a single transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from radar import legacy
from radar.liquidity import Liquidity
from radar.models import (
    FilingRef,
    Form4,
    Purchase,
    PurchaseFiling,
    Schedule13D,
    Signal,
)
from radar.parsers.form4 import NO_TICKER_PLACEHOLDERS
from radar.roles import classify_title

SCHEMA_VERSION = 3

# filings.status
NEW = "new"
PROCESSED = "processed"
SKIPPED = "skipped"
ERROR = "error"

FILINGS_TABLE = """
CREATE TABLE IF NOT EXISTS filings (
    accession     TEXT PRIMARY KEY,
    form          TEXT NOT NULL,
    cik           TEXT NOT NULL,
    company       TEXT NOT NULL,
    filed_date    TEXT NOT NULL,
    accepted_at   TEXT,
    url           TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new',   -- new | processed | skipped | error
    error         TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filings_status ON filings(status);
CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings(cik, filed_date);
"""

AI_SUMMARIES_TABLE = """
-- AI summaries, so the same filing/signal is never summarized twice in a language.
CREATE TABLE IF NOT EXISTS ai_summaries (
    accession   TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    lang        TEXT NOT NULL,
    model       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (accession, signal_type, lang)
);
"""

SCHEMA = (
    FILINGS_TABLE
    + AI_SUMMARIES_TABLE
    + """

CREATE TABLE IF NOT EXISTS form4 (
    accession        TEXT PRIMARY KEY REFERENCES filings(accession),
    document_type    TEXT NOT NULL,
    issuer_cik       TEXT NOT NULL,
    issuer_name      TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    period_of_report TEXT,
    filed_date       TEXT NOT NULL,
    remarks          TEXT
);
CREATE INDEX IF NOT EXISTS idx_form4_issuer ON form4(issuer_cik, filed_date);

CREATE TABLE IF NOT EXISTS form4_owners (
    accession            TEXT NOT NULL REFERENCES form4(accession),
    position             INTEGER NOT NULL,
    owner_cik            TEXT NOT NULL,
    owner_name           TEXT NOT NULL,
    is_director          INTEGER NOT NULL,
    is_officer           INTEGER NOT NULL,
    is_ten_percent_owner INTEGER NOT NULL,
    is_other             INTEGER NOT NULL,
    officer_title        TEXT,
    PRIMARY KEY (accession, position)
);

CREATE TABLE IF NOT EXISTS form4_transactions (
    accession         TEXT NOT NULL REFERENCES form4(accession),
    position          INTEGER NOT NULL,
    security_title    TEXT,
    trans_date        TEXT,
    code              TEXT NOT NULL,
    shares            REAL,
    price             REAL,
    acquired_disposed TEXT,
    shares_after      REAL,
    ownership         TEXT,
    PRIMARY KEY (accession, position)
);
CREATE INDEX IF NOT EXISTS idx_form4_tx_code ON form4_transactions(code);

CREATE TABLE IF NOT EXISTS sc13d (
    accession      TEXT PRIMARY KEY REFERENCES filings(accession),
    form           TEXT NOT NULL,
    is_amendment   INTEGER NOT NULL,
    issuer_cik     TEXT,
    issuer_name    TEXT,
    cusip          TEXT,
    event_date     TEXT,
    max_percent    REAL,
    source_format  TEXT NOT NULL,
    purpose        TEXT
);

CREATE TABLE IF NOT EXISTS sc13d_reporters (
    accession TEXT NOT NULL REFERENCES sc13d(accession),
    position  INTEGER NOT NULL,
    name      TEXT,
    cik       TEXT,
    shares    REAL,
    percent   REAL,
    PRIMARY KEY (accession, position)
);

CREATE TABLE IF NOT EXISTS signals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    type              TEXT NOT NULL,
    dedupe_key        TEXT NOT NULL UNIQUE,
    issuer_cik        TEXT,
    issuer_name       TEXT,
    ticker            TEXT,
    signal_date       TEXT NOT NULL,
    score             REAL NOT NULL,
    explanation       TEXT NOT NULL,
    summary           TEXT,
    summary_source    TEXT,
    trigger_accession TEXT NOT NULL,
    details           TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    alerted_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_issuer ON signals(type, issuer_cik, signal_date);

-- One row per AI call, to enforce the hourly cap.
CREATE TABLE IF NOT EXISTS ai_calls (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at TEXT NOT NULL,
    ok        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_calls_at ON ai_calls(called_at);

-- Sector of each issuer (SIC code from the SEC registry), for the dashboard ranking,
-- and whether it files the reports of a registered fund (NULL = not looked up).
CREATE TABLE IF NOT EXISTS issuers (
    cik                TEXT PRIMARY KEY,
    sic                TEXT,
    sector             TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    investment_company INTEGER
);

-- Latest price and market value of each signal's company (see radar.liquidity).
CREATE TABLE IF NOT EXISTS signal_liquidity (
    signal_id     INTEGER PRIMARY KEY REFERENCES signals(id),
    symbol        TEXT NOT NULL,
    price         REAL,
    price_as_of   TEXT,
    shares        REAL,
    shares_as_of  TEXT,
    market_value  REAL,
    liquid        INTEGER NOT NULL,
    updated_at    TEXT NOT NULL
);
"""
)

# Form 4 transaction codes that are neither an open-market buy nor a sale.
_CODE_KINDS = {
    "A": "grant",
    "M": "exercise",
    "F": "tax",
    "G": "gift",
    "D": "return_to_issuer",
    "C": "conversion",
    "J": "other",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _owner_role(owner: sqlite3.Row) -> str:
    """Role of a Form 4 filer, from the most specific to the most generic."""
    if owner["is_officer"]:
        return owner["officer_title"] or "Officer"
    if owner["is_director"]:
        return "Director"
    if owner["is_ten_percent_owner"]:
        return "10% owner"
    return "Other"


class Database:
    def __init__(self, path: Path | str, *, check_same_thread: bool = True):
        self.path = Path(path) if path != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` serves the API, which reads from several threads behind a lock.
        self.conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path is not None:
            self.conn.execute("PRAGMA journal_mode = WAL")
            # In WAL mode, NORMAL does not corrupt the database and avoids one fsync per
            # write (on macOS each fsync costs tens of milliseconds).
            self.conn.execute("PRAGMA synchronous = NORMAL")
        self._prepare()

    def _prepare(self) -> None:
        """Creates the schema, or migrates an older database to the current version."""
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        existing = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'filings'"
        ).fetchone()
        if existing and version < SCHEMA_VERSION:
            migrate(self.conn, version)
        self.conn.executescript(SCHEMA)
        if version < SCHEMA_VERSION:
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- filings

    def has_filing(self, accession: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM filings WHERE accession = ?", (accession,))
        return row.fetchone() is not None

    def add_filing(self, ref: FilingRef) -> bool:
        """Stores a filing seen in the feed. Returns False if it already existed (no dupes)."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO filings
               (accession, form, cik, company, filed_date, accepted_at, url, status,
                first_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ref.accession,
                ref.form,
                ref.cik,
                ref.company,
                ref.filed_date.isoformat(),
                ref.accepted_at.isoformat() if ref.accepted_at else None,
                ref.url,
                NEW,
                _now(),
            ),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def pending_filings(self) -> list[FilingRef]:
        rows = self.conn.execute(
            "SELECT * FROM filings WHERE status = ? ORDER BY filed_date, accession", (NEW,)
        ).fetchall()
        return [self._ref(row) for row in rows]

    @staticmethod
    def _ref(row: sqlite3.Row) -> FilingRef:
        accepted = row["accepted_at"]
        return FilingRef(
            accession=row["accession"],
            form=row["form"],
            cik=row["cik"],
            company=row["company"],
            filed_date=date.fromisoformat(row["filed_date"]),
            url=row["url"],
            accepted_at=datetime.fromisoformat(accepted) if accepted else None,
        )

    def mark_filing(self, accession: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE filings SET status = ?, error = ? WHERE accession = ?",
            (status, error, accession),
        )
        self.conn.commit()

    def count_filings(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]

    def count_pending(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM filings WHERE status = ?", (NEW,)).fetchone()
        return row[0]

    def first_seen(self) -> datetime | None:
        """When the monitor stored its first filing (start of the database coverage)."""
        row = self.conn.execute("SELECT MIN(first_seen_at) FROM filings").fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def recent_filings(self, limit: int = 60) -> list[dict]:
        """The latest filings already handled, summarized for the dashboard tape."""
        rows = self.conn.execute(
            """SELECT accession FROM filings WHERE status <> ?
               ORDER BY COALESCE(accepted_at, filed_date) DESC, accession DESC LIMIT ?""",
            (NEW, limit),
        ).fetchall()
        return [brief for r in rows if (brief := self.filing_brief(r["accession"]))]

    def filing_brief(self, accession: str) -> dict | None:
        """A filing in a few words: who, what and how much."""
        row = self.conn.execute(
            "SELECT * FROM filings WHERE accession = ?", (accession,)
        ).fetchone()
        if row is None:
            return None
        brief = {
            "accession": row["accession"],
            "form": row["form"],
            "cik": row["cik"],
            "company": row["company"],
            "ticker": "",
            "filed_date": row["filed_date"],
            "accepted_at": row["accepted_at"],
            "url": row["url"],
            "status": row["status"],
            "kind": "other",
            "who": "",
            "role": "",
            "value": None,
            "percent": None,
        }
        form4 = self.conn.execute(
            "SELECT * FROM form4 WHERE accession = ?", (accession,)
        ).fetchone()
        if form4 is not None:
            brief["company"] = form4["issuer_name"] or brief["company"]
            brief["ticker"] = form4["ticker"] or ""
            brief["cik"] = form4["issuer_cik"] or brief["cik"]
            owner = self.conn.execute(
                "SELECT * FROM form4_owners WHERE accession = ? ORDER BY position LIMIT 1",
                (accession,),
            ).fetchone()
            if owner is not None:
                brief["who"] = owner["owner_name"]
                brief["role"] = _owner_role(owner)
            totals = {
                r["code"]: (r["n"], r["value"])
                for r in self.conn.execute(
                    """SELECT code, COUNT(*) AS n, SUM(COALESCE(shares, 0) * COALESCE(price, 0))
                              AS value
                       FROM form4_transactions WHERE accession = ? GROUP BY code""",
                    (accession,),
                )
            }
            if "P" in totals:
                brief["kind"], brief["value"] = "buy", totals["P"][1]
            elif "S" in totals:
                brief["kind"], brief["value"] = "sale", totals["S"][1]
            elif totals:
                code = max(totals, key=lambda c: totals[c][0])
                brief["kind"] = _CODE_KINDS.get(code, "other")
            return brief
        sc13d = self.conn.execute(
            "SELECT * FROM sc13d WHERE accession = ?", (accession,)
        ).fetchone()
        if sc13d is not None:
            brief["company"] = sc13d["issuer_name"] or brief["company"]
            brief["cik"] = sc13d["issuer_cik"] or brief["cik"]
            brief["kind"] = "amended_13d" if sc13d["is_amendment"] else "new_13d"
            brief["percent"] = sc13d["max_percent"]
            lead = self.conn.execute(
                """SELECT name FROM sc13d_reporters WHERE accession = ?
                   ORDER BY percent IS NULL, percent DESC, position LIMIT 1""",
                (accession,),
            ).fetchone()
            brief["who"] = (lead["name"] if lead else "") or ""
            brief["role"] = "13D filer"
        return brief

    # ----------------------------------------------------------------- form 4

    def save_form4(self, accession: str, filed_date: date, doc: Form4) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO form4
                   (accession, document_type, issuer_cik, issuer_name, ticker,
                    period_of_report, filed_date, remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    accession,
                    doc.document_type,
                    doc.issuer_cik,
                    doc.issuer_name,
                    doc.issuer_ticker,
                    doc.period_of_report.isoformat() if doc.period_of_report else None,
                    filed_date.isoformat(),
                    doc.remarks,
                ),
            )
            self.conn.execute("DELETE FROM form4_owners WHERE accession = ?", (accession,))
            self.conn.execute("DELETE FROM form4_transactions WHERE accession = ?", (accession,))
            self.conn.executemany(
                "INSERT INTO form4_owners VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        accession,
                        i,
                        o.cik,
                        o.name,
                        o.is_director,
                        o.is_officer,
                        o.is_ten_percent_owner,
                        o.is_other,
                        o.officer_title,
                    )
                    for i, o in enumerate(doc.owners)
                ],
            )
            self.conn.executemany(
                "INSERT INTO form4_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        accession,
                        i,
                        t.security_title,
                        t.date.isoformat() if t.date else None,
                        t.code,
                        t.shares,
                        t.price,
                        t.acquired_disposed,
                        t.shares_after,
                        t.ownership,
                    )
                    for i, t in enumerate(doc.transactions)
                ],
            )

    def has_form4(self, accession: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM form4 WHERE accession = ?", (accession,))
        return row.fetchone() is not None

    def purchase_filings(self, issuer_cik: str) -> list[PurchaseFiling]:
        """The issuer's original Form 4s (not amendments) with P buys, ready for the rules."""
        filings = self.conn.execute(
            """SELECT * FROM form4
               WHERE issuer_cik = ? AND document_type = '4'
               ORDER BY filed_date, accession""",
            (issuer_cik,),
        ).fetchall()
        result: list[PurchaseFiling] = []
        for row in filings:
            txs = self.conn.execute(
                """SELECT trans_date, shares, price, shares_after FROM form4_transactions
                   WHERE accession = ? AND code = 'P' AND COALESCE(acquired_disposed, 'A') <> 'D'
                     AND shares > 0 AND price > 0 AND trans_date IS NOT NULL
                   ORDER BY position""",
                (row["accession"],),
            ).fetchall()
            if not txs:
                continue
            owners = self.conn.execute(
                "SELECT * FROM form4_owners WHERE accession = ? ORDER BY position",
                (row["accession"],),
            ).fetchall()
            is_ceo = is_cfo = is_od = False
            title = ""
            for owner in owners:
                is_od |= bool(owner["is_director"] or owner["is_officer"])
                if owner["is_officer"]:
                    ceo, cfo = classify_title(owner["officer_title"], row["remarks"])
                    is_ceo |= ceo
                    is_cfo |= cfo
                    title = title or (owner["officer_title"] or "")
            after = [t["shares_after"] for t in txs if t["shares_after"] is not None]
            result.append(
                PurchaseFiling(
                    accession=row["accession"],
                    issuer_cik=row["issuer_cik"],
                    issuer_name=row["issuer_name"],
                    ticker=row["ticker"],
                    filing_date=date.fromisoformat(row["filed_date"]),
                    owner_ciks=frozenset(o["owner_cik"] for o in owners),
                    owner_names=tuple(o["owner_name"] for o in owners),
                    is_ceo=is_ceo,
                    is_cfo=is_cfo,
                    is_officer_or_director=is_od,
                    officer_title=title,
                    purchases=tuple(
                        Purchase(
                            date.fromisoformat(t["trans_date"]),
                            t["shares"],
                            t["price"],
                            t["shares_after"],
                        )
                        for t in txs
                    ),
                    shares_after=max(after) if after else None,
                )
            )
        return result

    def form4_context(self, accession: str) -> dict:
        """Form 4 data in a simple shape, to build the summary prompt."""
        row = self.conn.execute("SELECT * FROM form4 WHERE accession = ?", (accession,)).fetchone()
        if row is None:
            return {}
        owners = self.conn.execute(
            "SELECT owner_name, officer_title, is_director, is_officer, is_ten_percent_owner "
            "FROM form4_owners WHERE accession = ? ORDER BY position",
            (accession,),
        ).fetchall()
        txs = self.conn.execute(
            "SELECT trans_date, code, shares, price, acquired_disposed, shares_after "
            "FROM form4_transactions WHERE accession = ? ORDER BY position",
            (accession,),
        ).fetchall()
        return {
            "issuer": row["issuer_name"],
            "ticker": row["ticker"],
            "remarks": row["remarks"] or "",
            "owners": [dict(o) for o in owners],
            "transactions": [dict(t) for t in txs],
        }

    def issuer_purchases(self, issuer_cik: str, limit: int = 200) -> list[dict]:
        """The issuer's open-market buys (code P), newest first."""
        rows = self.conn.execute(
            """SELECT t.accession, t.trans_date, t.shares, t.price, f.filed_date
               FROM form4_transactions t JOIN form4 f ON f.accession = t.accession
               WHERE f.issuer_cik = ? AND f.document_type = '4' AND t.code = 'P'
                 AND COALESCE(t.acquired_disposed, 'A') <> 'D' AND t.shares > 0 AND t.price > 0
                 AND t.trans_date IS NOT NULL
               ORDER BY t.trans_date DESC, t.accession, t.position LIMIT ?""",
            (issuer_cik, limit),
        ).fetchall()
        owners: dict[str, tuple[str, str]] = {}
        out: list[dict] = []
        for row in rows:
            accession = row["accession"]
            if accession not in owners:
                people = self.conn.execute(
                    "SELECT * FROM form4_owners WHERE accession = ? ORDER BY position",
                    (accession,),
                ).fetchall()
                owners[accession] = (
                    " / ".join(p["owner_name"] for p in people[:3]),
                    _owner_role(people[0]) if people else "",
                )
            name, role = owners[accession]
            out.append(
                {
                    "date": row["trans_date"],
                    "filed_date": row["filed_date"],
                    "name": name,
                    "role": role,
                    "shares": row["shares"],
                    "price": row["price"],
                    "value": row["shares"] * row["price"],
                    "accession": accession,
                }
            )
        return out

    def purchase_totals(self, since: date) -> list[dict]:
        """Open-market buys per issuer since `since` (filing date).

        The same transaction reported in two Form 4s (affiliates filing separately)
        counts only once.
        """
        rows = self.conn.execute(
            """WITH buys AS (
                   SELECT DISTINCT f.issuer_cik, t.trans_date, t.shares, t.price, t.shares_after
                   FROM form4_transactions t JOIN form4 f ON f.accession = t.accession
                   WHERE f.document_type = '4' AND t.code = 'P'
                     AND COALESCE(t.acquired_disposed, 'A') <> 'D'
                     AND t.shares > 0 AND t.price > 0 AND f.filed_date >= ?
               ),
               info AS (
                   SELECT f.issuer_cik, MAX(f.issuer_name) AS name, MAX(f.ticker) AS ticker,
                          MAX(f.filed_date) AS last_date,
                          COUNT(DISTINCT f.accession) AS filings,
                          COUNT(DISTINCT o.owner_cik) AS insiders
                   FROM form4 f
                   JOIN form4_owners o ON o.accession = f.accession
                   WHERE f.document_type = '4' AND f.filed_date >= ? AND EXISTS (
                       SELECT 1 FROM form4_transactions t
                       WHERE t.accession = f.accession AND t.code = 'P'
                         AND COALESCE(t.acquired_disposed, 'A') <> 'D'
                         AND t.shares > 0 AND t.price > 0)
                   GROUP BY f.issuer_cik
               )
               SELECT info.*, s.sector,
                      (SELECT SUM(b.shares * b.price) FROM buys b
                       WHERE b.issuer_cik = info.issuer_cik) AS value
               FROM info LEFT JOIN issuers s ON s.cik = info.issuer_cik
               ORDER BY value DESC""",
            (since.isoformat(), since.isoformat()),
        ).fetchall()
        return [
            {
                "cik": r["issuer_cik"],
                "name": r["name"],
                "ticker": r["ticker"] or "",
                "sector": r["sector"] or "",
                "value": r["value"] or 0.0,
                "insiders": r["insiders"],
                "filings": r["filings"],
                "last_date": r["last_date"],
            }
            for r in rows
        ]

    # ---------------------------------------------------------------- sectors

    def sector_of(self, cik: str) -> str | None:
        row = self.conn.execute("SELECT sector FROM issuers WHERE cik = ?", (cik,)).fetchone()
        return row["sector"] if row else None

    def set_sector(
        self, cik: str, sic: str, sector: str, investment_company: bool | None = None
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO issuers (cik, sic, sector, updated_at, investment_company)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                cik,
                sic,
                sector,
                _now(),
                None if investment_company is None else int(investment_company),
            ),
        )
        self.conn.commit()

    def issuer_profile(self, cik: str) -> tuple[str, bool | None] | None:
        """(sic, investment_company) as stored, or None if the issuer was never looked up."""
        row = self.conn.execute(
            "SELECT sic, investment_company FROM issuers WHERE cik = ?", (cik,)
        ).fetchone()
        if row is None:
            return None
        flag = row["investment_company"]
        return row["sic"] or "", None if flag is None else bool(flag)

    def issuer_profiles(self) -> dict[str, tuple[str, bool | None]]:
        """Every stored (sic, investment_company), by CIK."""
        rows = self.conn.execute("SELECT cik, sic, investment_company FROM issuers").fetchall()
        return {
            r["cik"]: (
                r["sic"] or "",
                None if r["investment_company"] is None else bool(r["investment_company"]),
            )
            for r in rows
        }

    def issuers_without_sector(self, since: date, limit: int = 40) -> list[str]:
        """Issuers with a recent buy (or signal) whose sector has not been looked up yet,
        or that have no SIC and were never checked for fund filings."""
        rows = self.conn.execute(
            """SELECT DISTINCT cik FROM (
                   SELECT f.issuer_cik AS cik FROM form4 f
                   JOIN form4_transactions t ON t.accession = f.accession
                   WHERE t.code = 'P' AND f.filed_date >= ?
                   UNION
                   SELECT issuer_cik AS cik FROM signals WHERE signal_date >= ?
               )
               WHERE cik <> '' AND cik IS NOT NULL
                 AND cik NOT IN (
                     SELECT cik FROM issuers
                     WHERE investment_company IS NOT NULL
                        OR COALESCE(TRIM(sic), '') NOT IN ('', '0000')
                 )
               LIMIT ?""",
            (since.isoformat(), since.isoformat(), limit),
        ).fetchall()
        return [r["cik"] for r in rows]

    # -------------------------------------------------------------------- 13D

    def save_13d(self, accession: str, doc: Schedule13D) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO sc13d
                   (accession, form, is_amendment, issuer_cik, issuer_name, cusip,
                    event_date, max_percent, source_format, purpose)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    accession,
                    doc.form,
                    doc.is_amendment,
                    doc.issuer_cik,
                    doc.issuer_name,
                    doc.cusip,
                    doc.event_date.isoformat() if doc.event_date else None,
                    doc.max_percent,
                    doc.source_format,
                    doc.purpose,
                ),
            )
            self.conn.execute("DELETE FROM sc13d_reporters WHERE accession = ?", (accession,))
            self.conn.executemany(
                "INSERT INTO sc13d_reporters VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (accession, i, r.name, r.cik, r.shares, r.percent)
                    for i, r in enumerate(doc.reporters)
                ],
            )

    # ---------------------------------------------------------------- signals

    def add_signal(self, signal: Signal) -> bool:
        """Stores the signal. Returns False if another one with the same key already existed."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO signals
               (type, dedupe_key, issuer_cik, issuer_name, ticker, signal_date, score,
                explanation, summary, summary_source, trigger_accession, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.type,
                signal.dedupe_key,
                signal.issuer_cik,
                signal.issuer_name,
                signal.ticker,
                signal.signal_date.isoformat(),
                signal.score,
                signal.explanation,
                signal.summary,
                signal.summary_source,
                signal.trigger_accession,
                json.dumps(signal.details, ensure_ascii=False),
                _now(),
            ),
        )
        self.conn.commit()
        if cursor.rowcount == 1:
            signal.id = cursor.lastrowid
            return True
        return False

    def set_summary(
        self, signal: Signal, summary: str | None = None, source: str | None = None
    ) -> None:
        """Stores the summary column (by default, the one the signal carries)."""
        self.conn.execute(
            "UPDATE signals SET summary = ?, summary_source = ? WHERE dedupe_key = ?",
            (
                signal.summary if summary is None else summary,
                signal.summary_source if source is None else source,
                signal.dedupe_key,
            ),
        )
        self.conn.commit()

    def mark_alerted(self, signal: Signal) -> None:
        self.conn.execute(
            "UPDATE signals SET alerted_at = ? WHERE dedupe_key = ?", (_now(), signal.dedupe_key)
        )
        self.conn.commit()

    def prior_signal_dates(self, signal_type: str, issuer_cik: str) -> list[date]:
        rows = self.conn.execute(
            "SELECT signal_date FROM signals WHERE type = ? AND issuer_cik = ?",
            (signal_type, issuer_cik),
        ).fetchall()
        return [date.fromisoformat(r["signal_date"]) for r in rows]

    def has_signal(self, dedupe_key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM signals WHERE dedupe_key = ?", (dedupe_key,))
        return row.fetchone() is not None

    def get_signal(self, signal_id: int) -> Signal | None:
        row = self.conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return self._signal(row) if row else None

    def count_signals(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    def issuer_signals(self, issuer_cik: str) -> list[Signal]:
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE issuer_cik = ? ORDER BY signal_date DESC, id DESC",
            (issuer_cik,),
        ).fetchall()
        return [self._signal(row) for row in rows]

    def list_signals(
        self,
        *,
        since: date | None = None,
        signal_type: str | None = None,
        limit: int | None = None,
    ) -> list[Signal]:
        query = "SELECT * FROM signals WHERE 1 = 1"
        params: list[object] = []
        if since is not None:
            query += " AND signal_date >= ?"
            params.append(since.isoformat())
        if signal_type:
            query += " AND type = ?"
            params.append(signal_type)
        query += " ORDER BY signal_date DESC, score DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [self._signal(row) for row in self.conn.execute(query, params).fetchall()]

    @staticmethod
    def _signal(row: sqlite3.Row) -> Signal:
        return Signal(
            id=row["id"],
            type=row["type"],
            dedupe_key=row["dedupe_key"],
            issuer_cik=row["issuer_cik"] or "",
            issuer_name=row["issuer_name"] or "",
            ticker=row["ticker"] or "",
            signal_date=date.fromisoformat(row["signal_date"]),
            score=row["score"],
            explanation=row["explanation"],
            summary=row["summary"] or "",
            summary_source=row["summary_source"] or "",
            trigger_accession=row["trigger_accession"],
            details=json.loads(row["details"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -------------------------------------------------------------- liquidity

    def set_liquidity(self, signal_id: int, liquidity: Liquidity) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO signal_liquidity
               (signal_id, symbol, price, price_as_of, shares, shares_as_of, market_value,
                liquid, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                liquidity.symbol,
                liquidity.price,
                liquidity.price_as_of,
                liquidity.shares,
                liquidity.shares_as_of,
                liquidity.market_value,
                int(liquidity.liquid),
                _now(),
            ),
        )
        self.conn.commit()

    def signal_liquidity(self, signal_ids: Iterable[int]) -> dict[int, dict]:
        """Stored price and market value by signal id (signals without a row are left out)."""
        ids = [i for i in signal_ids if i is not None]
        out: dict[int, dict] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ", ".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT * FROM signal_liquidity WHERE signal_id IN ({marks})", chunk
            ).fetchall()
            out.update({r["signal_id"]: dict(r) for r in rows})
        return out

    def signals_needing_liquidity(
        self,
        since: date,
        stale_before: datetime,
        *,
        first_types: Iterable[str] = (),
        limit: int = 150,
    ) -> list[Signal]:
        """Recent signals with a ticker and no (or a stale) price/market value, the
        `first_types` first, newest first."""
        first = list(first_types) or [""]
        marks = ", ".join("?" for _ in first)
        rows = self.conn.execute(
            f"""SELECT s.* FROM signals s
                LEFT JOIN signal_liquidity l ON l.signal_id = s.id
                WHERE s.signal_date >= ? AND COALESCE(s.ticker, '') <> ''
                  AND (l.signal_id IS NULL OR l.updated_at < ?)
                ORDER BY CASE WHEN s.type IN ({marks}) THEN 0 ELSE 1 END,
                         s.signal_date DESC, s.id DESC
                LIMIT ?""",
            (
                since.isoformat(),
                stale_before.astimezone(UTC).isoformat(timespec="seconds"),
                *first,
                limit,
            ),
        ).fetchall()
        return [self._signal(row) for row in rows]

    # --------------------------------------------------------------------- AI

    def cached_ai_summary(self, accession: str, signal_type: str, lang: str = "en") -> str | None:
        row = self.conn.execute(
            "SELECT summary FROM ai_summaries WHERE accession = ? AND signal_type = ? AND lang = ?",
            (accession, signal_type, lang),
        ).fetchone()
        return row["summary"] if row else None

    def cached_ai_summaries(self, accession: str, signal_type: str) -> dict[str, str]:
        """Every cached AI summary of a signal, by language."""
        rows = self.conn.execute(
            "SELECT lang, summary FROM ai_summaries WHERE accession = ? AND signal_type = ?",
            (accession, signal_type),
        ).fetchall()
        return {r["lang"]: r["summary"] for r in rows}

    def store_ai_summary(
        self, accession: str, signal_type: str, model: str, text: str, lang: str = "en"
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO ai_summaries
               (accession, signal_type, lang, model, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (accession, signal_type, lang, model, text, _now()),
        )
        self.conn.commit()

    def record_ai_call(self, ok: bool) -> None:
        self.conn.execute("INSERT INTO ai_calls (called_at, ok) VALUES (?, ?)", (_now(), ok))
        self.conn.commit()

    def ai_calls_last_hour(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=1)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM ai_calls WHERE called_at > ?",
            (cutoff.isoformat(timespec="seconds"),),
        ).fetchone()
        return row[0]

    def issuers_with_purchases(self, accessions: Iterable[str]) -> list[str]:
        """Issuers that had a P buy in any of the given filings."""
        accs = list(accessions)
        if not accs:
            return []
        marks = ",".join("?" * len(accs))
        rows = self.conn.execute(
            f"""SELECT DISTINCT f.issuer_cik FROM form4 f
                JOIN form4_transactions t ON t.accession = f.accession
                WHERE t.code = 'P' AND f.accession IN ({marks})""",
            accs,
        ).fetchall()
        return [r["issuer_cik"] for r in rows]


# ------------------------------------------------------------------ migrations


def migrate(conn: sqlite3.Connection, version: int) -> None:
    """Brings a database at `version` up to `SCHEMA_VERSION`, all or nothing."""
    conn.commit()
    isolation = conn.isolation_level
    conn.isolation_level = None  # explicit BEGIN/COMMIT below
    # Rebuilding a referenced table needs the foreign keys off (outside a transaction).
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if version < 1:
                _migrate_v1(conn)
            if version < 2:
                _migrate_v2(conn)
            if version < 3:
                _migrate_v3(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = isolation


def _value_case(column: str, mapping: dict[str, str]) -> str:
    """SQL `CASE` that maps old values of `column` to new ones (others unchanged)."""
    whens = " ".join(f"WHEN {_quote(old)} THEN {_quote(new)}" for old, new in mapping.items())
    return f"CASE {column} {whens} ELSE {column} END"


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2: placeholder tickers typed by filers ("NONE", "N/A", ...) become empty."""
    placeholders = ", ".join(_quote(p) for p in sorted(NO_TICKER_PLACEHOLDERS))
    for table in ("form4", "signals"):
        conn.execute(
            f"UPDATE {table} SET ticker = '' WHERE UPPER(TRIM(ticker)) IN ({placeholders})"
        )


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v2 → v3: issuers learn whether they file as a registered fund (NULL until checked)."""
    if not _has_table(conn, "issuers"):
        return
    columns = [r[1] for r in conn.execute("PRAGMA table_info(issuers)")]
    if "investment_company" not in columns:
        conn.execute("ALTER TABLE issuers ADD COLUMN investment_company INTEGER")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v0 (Portuguese codes) → v1 (English codes and keys, AI summaries per language)."""
    # filings: English status codes, and the column default changes, so rebuild it the
    # way SQLite recommends: new table, copy, drop the old one, rename the new one. (Renaming
    # the old table first would make the tables referencing it follow the new name.)
    conn.execute(FILINGS_TABLE.split(";")[0].replace("filings (", "filings_v1 (", 1))
    conn.execute(
        f"""INSERT INTO filings_v1
            SELECT accession, form, cik, company, filed_date, accepted_at, url,
                   {_value_case("status", legacy.FILING_STATUS)}, error, first_seen_at
            FROM filings"""
    )
    conn.execute("DROP TABLE filings")
    conn.execute("ALTER TABLE filings_v1 RENAME TO filings")
    for statement in FILINGS_TABLE.split(";")[1:]:
        if statement.strip():
            conn.execute(statement)

    # ai_summaries: one row per language; what exists was written in Portuguese.
    has_ai = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ai_summaries'"
    ).fetchone()
    columns = [r[1] for r in conn.execute("PRAGMA table_info(ai_summaries)")] if has_ai else []
    if has_ai and "lang" not in columns:
        conn.execute("ALTER TABLE ai_summaries RENAME TO ai_summaries_v0")
        conn.execute(AI_SUMMARIES_TABLE)
        conn.execute(
            """INSERT INTO ai_summaries (accession, signal_type, lang, model, summary, created_at)
               SELECT accession, signal_type, 'pt-BR', model, summary, created_at
               FROM ai_summaries_v0"""
        )
        conn.execute("DROP TABLE ai_summaries_v0")

    if _has_table(conn, "sc13d"):
        conn.execute(
            f"UPDATE sc13d SET source_format = {_value_case('source_format', legacy.SOURCE_FORMAT)}"
        )
    if _has_table(conn, "issuers"):
        conn.execute(f"UPDATE issuers SET sector = {_value_case('sector', legacy.SECTORS)}")
    if _has_table(conn, "signals"):
        _migrate_signals_v1(conn)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _migrate_signals_v1(conn: sqlite3.Connection) -> None:
    """English details keys, explanation and summary for every stored signal.

    The explanation and template summaries are rendered again in English. An AI
    summary keeps living in `ai_summaries` (as pt-BR); the English column gets a
    cached English AI summary when there is one, otherwise the English template.
    """
    from radar.signals import explain
    from radar.summary import template_summary

    rows = conn.execute(
        "SELECT id, type, issuer_cik, issuer_name, ticker, signal_date, score, summary,"
        " summary_source, trigger_accession, details FROM signals"
    ).fetchall()
    for row in rows:
        (sid, kind, cik, name, ticker, day, score, summary, source, accession, raw) = row
        details = legacy.upgrade_details(kind, json.loads(raw))
        signal = Signal(
            type=kind,
            dedupe_key="",
            issuer_cik=cik or "",
            issuer_name=name or "",
            ticker=ticker or "",
            signal_date=date.fromisoformat(day),
            score=score,
            explanation="",
            trigger_accession=accession,
            details=details,
        )
        explanation = explain(signal, "en")
        source = legacy.SUMMARY_SOURCE.get(source, source)
        if source:
            cached = conn.execute(
                "SELECT summary FROM ai_summaries"
                " WHERE accession = ? AND signal_type = ? AND lang = 'en'",
                (accession, kind),
            ).fetchone()
            if cached:
                summary, source = cached[0], "ai"
            else:
                summary, source = template_summary(signal, "en"), "template"
        conn.execute(
            "UPDATE signals SET details = ?, explanation = ?, summary = ?, summary_source = ?"
            " WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), explanation, summary, source, sid),
        )
