"""SQLite tables of the extra sources, created by numbered migrations.

They live in the same database file as the rest of the radar but are created and
read only by this package, so the base schema stays untouched. Signals of the new
types go to the existing `signals` table.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .base import MarketEvent

MIGRATIONS: list[str] = [
    # 1: events, Form 144, 13F, short data and per-source state
    """
    CREATE TABLE IF NOT EXISTS market_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source      TEXT NOT NULL,
        kind        TEXT NOT NULL,
        key         TEXT NOT NULL,
        event_date  TEXT NOT NULL,
        issuer_cik  TEXT,
        issuer_name TEXT,
        ticker      TEXT,
        title       TEXT NOT NULL,
        data        TEXT NOT NULL,
        url         TEXT,
        seen_at     TEXT NOT NULL,
        UNIQUE (source, key)
    );
    CREATE INDEX IF NOT EXISTS idx_market_events_date ON market_events(event_date);
    CREATE INDEX IF NOT EXISTS idx_market_events_issuer ON market_events(issuer_cik, event_date);
    CREATE INDEX IF NOT EXISTS idx_market_events_ticker ON market_events(ticker, event_date);

    CREATE TABLE IF NOT EXISTS form144_notices (
        accession         TEXT PRIMARY KEY,
        issuer_cik        TEXT NOT NULL,
        issuer_name       TEXT,
        ticker            TEXT,
        seller_cik        TEXT NOT NULL,
        seller_name       TEXT,
        relationships     TEXT,
        filing_date       TEXT NOT NULL,
        market_value      REAL,
        units             REAL,
        units_outstanding REAL,
        approx_sale_date  TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_form144_issuer ON form144_notices(issuer_cik, filing_date);

    CREATE TABLE IF NOT EXISTS thirteenf_reports (
        accession   TEXT PRIMARY KEY,
        cik         TEXT NOT NULL,
        manager     TEXT,
        period      TEXT NOT NULL,
        filing_date TEXT NOT NULL,
        positions   INTEGER NOT NULL,
        total_value REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_13f_reports ON thirteenf_reports(cik, period);
    CREATE TABLE IF NOT EXISTS thirteenf_positions (
        accession TEXT NOT NULL,
        cusip     TEXT NOT NULL,
        shares    REAL NOT NULL,
        value     REAL NOT NULL,
        name      TEXT,
        PRIMARY KEY (accession, cusip)
    );
    CREATE INDEX IF NOT EXISTS idx_13f_positions_cusip ON thirteenf_positions(cusip);

    CREATE TABLE IF NOT EXISTS short_interest (
        symbol          TEXT NOT NULL,
        settlement_date TEXT NOT NULL,
        short_shares    REAL NOT NULL,
        previous_shares REAL,
        days_to_cover   REAL,
        avg_volume      REAL,
        market          TEXT,
        name            TEXT,
        PRIMARY KEY (symbol, settlement_date)
    );
    CREATE TABLE IF NOT EXISTS short_volume (
        symbol       TEXT NOT NULL,
        day          TEXT NOT NULL,
        short_volume REAL NOT NULL,
        total_volume REAL NOT NULL,
        PRIMARY KEY (symbol, day)
    );
    CREATE TABLE IF NOT EXISTS fails_to_deliver (
        symbol          TEXT NOT NULL,
        settlement_date TEXT NOT NULL,
        cusip           TEXT,
        quantity        REAL NOT NULL,
        price           REAL,
        PRIMARY KEY (symbol, settlement_date)
    );

    CREATE TABLE IF NOT EXISTS source_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # 2: news items (all of them, matched or not; the matched ones are also events)
    """
    CREATE TABLE IF NOT EXISTS news_items (
        key           TEXT PRIMARY KEY,
        feed          TEXT NOT NULL,
        url           TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        title         TEXT NOT NULL,
        title_hash    TEXT NOT NULL,
        summary       TEXT,
        published_at  TEXT,
        published_raw TEXT,
        seen_at       TEXT NOT NULL,
        tickers       TEXT NOT NULL,
        ciks          TEXT NOT NULL,
        matches       TEXT NOT NULL,
        tags          TEXT NOT NULL,
        score         TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_news_url ON news_items(canonical_url);
    CREATE INDEX IF NOT EXISTS idx_news_title ON news_items(title_hash);
    CREATE INDEX IF NOT EXISTS idx_news_seen ON news_items(seen_at);
    """,
]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the schema version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS source_migrations (version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL)"
    )
    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM source_migrations").fetchone()[0]
    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        conn.executescript(script)
        conn.execute("INSERT INTO source_migrations VALUES (?, ?)", (version, _now()))
        conn.commit()
    return len(MIGRATIONS)


class SourceStore:
    """Read/write access to the source tables over an existing SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        migrate(conn)

    # ------------------------------------------------------------------ state

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM source_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_state(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO source_state VALUES (?, ?, ?)", (key, json.dumps(value), _now())
        )
        self.conn.commit()

    # ----------------------------------------------------------------- events

    def add_event(self, event: MarketEvent) -> int | None:
        """Store an event; returns its id, or None when it was already known."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO market_events
               (source, kind, key, event_date, issuer_cik, issuer_name, ticker, title, data,
                url, seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.source,
                event.kind,
                event.key,
                event.event_date.isoformat(),
                event.issuer_cik,
                event.issuer_name,
                event.ticker,
                event.title,
                json.dumps(event.data, default=str),
                event.url,
                (event.seen_at or datetime.now(UTC)).isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid if cursor.rowcount == 1 else None

    def has_event(self, source: str, key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM market_events WHERE source = ? AND key = ?", (source, key)
        ).fetchone()
        return row is not None

    @staticmethod
    def event_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source": row["source"],
            "kind": row["kind"],
            "key": row["key"],
            "date": row["event_date"],
            "cik": row["issuer_cik"] or "",
            "company": row["issuer_name"] or "",
            "ticker": row["ticker"] or "",
            "title": row["title"],
            "data": json.loads(row["data"] or "{}"),
            "url": row["url"],
            "seen_at": row["seen_at"],
        }

    def recent_events(
        self, *, limit: int = 60, source: str | None = None, since: date | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM market_events WHERE 1 = 1"
        args: list[Any] = []
        if source:
            sql += " AND source = ?"
            args.append(source)
        if since:
            sql += " AND event_date >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY seen_at DESC, id DESC LIMIT ?"
        args.append(limit)
        return [self.event_row(r) for r in self.conn.execute(sql, args).fetchall()]

    def company_events(
        self, cik: str, ticker: str = "", *, since: date | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        since = since or date.today() - timedelta(days=400)
        rows = self.conn.execute(
            """SELECT * FROM market_events
               WHERE (issuer_cik = ? OR (? <> '' AND ticker = ?)) AND event_date >= ?
               ORDER BY event_date DESC, id DESC LIMIT ?""",
            (cik, ticker, ticker, since.isoformat(), limit),
        ).fetchall()
        return [self.event_row(r) for r in rows]

    def count_events(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT source, COUNT(*) AS n FROM market_events GROUP BY source"
        ).fetchall()
        return {r["source"]: r["n"] for r in rows}

    # -------------------------------------------------------------------- news

    def news_seen(self, key: str, canonical_url: str, title_hash: str) -> bool:
        """Whether this item, or the same URL, or the same headline was stored already."""
        row = self.conn.execute(
            "SELECT 1 FROM news_items WHERE key = ? OR canonical_url = ? OR title_hash = ? LIMIT 1",
            (key, canonical_url, title_hash),
        ).fetchone()
        return row is not None

    def add_news(self, row: dict[str, Any]) -> bool:
        """Store one news item (a `NewsSource.record`); False when it was already known."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO news_items
               (key, feed, url, canonical_url, title, title_hash, summary, published_at,
                published_raw, seen_at, tickers, ciks, matches, tags, score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["key"],
                row["feed"],
                row["url"],
                row["canonical_url"],
                row["title"],
                row["title_hash"],
                row.get("summary", ""),
                row.get("published_at"),
                row.get("published_raw", ""),
                row["seen_at"],
                json.dumps(row.get("tickers", [])),
                json.dumps(row.get("ciks", [])),
                json.dumps(row.get("matches", [])),
                json.dumps(row.get("tags", [])),
                json.dumps(row["score"]) if row.get("score") is not None else None,
            ),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def recent_news(self, *, limit: int = 100, matched_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM news_items"
        if matched_only:
            sql += " WHERE tickers <> '[]'"
        sql += " ORDER BY seen_at DESC, rowid DESC LIMIT ?"
        out = []
        for r in self.conn.execute(sql, (limit,)).fetchall():
            row = dict(r)
            for name in ("tickers", "ciks", "matches", "tags"):
                row[name] = json.loads(row[name] or "[]")
            row["score"] = json.loads(row["score"]) if row["score"] else None
            out.append(row)
        return out

    def count_news(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT feed, COUNT(*) AS n FROM news_items GROUP BY feed"
        ).fetchall()
        return {r["feed"]: r["n"] for r in rows}

    # ---------------------------------------------------------------- form 144

    def add_notice(self, n) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO form144_notices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                n.accession,
                n.issuer_cik,
                n.issuer_name,
                n.ticker,
                n.seller_cik,
                n.seller_name,
                ", ".join(n.relationships),
                n.filing_date.isoformat(),
                n.market_value,
                n.units,
                n.units_outstanding,
                n.approx_sale_date.isoformat() if n.approx_sale_date else None,
            ),
        )
        self.conn.commit()

    def has_notice(self, accession: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM form144_notices WHERE accession = ?", (accession,)
            ).fetchone()
            is not None
        )

    def notices(self, issuer_cik: str, since: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM form144_notices WHERE issuer_cik = ? AND filing_date >= ? "
            "ORDER BY filing_date, accession",
            (issuer_cik, since.isoformat()),
        ).fetchall()

    # --------------------------------------------------------------------- 13F

    def save_report(self, report) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO thirteenf_reports VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report.accession,
                    report.cik,
                    report.manager,
                    report.period.isoformat(),
                    report.filing_date.isoformat(),
                    report.positions,
                    report.total_value,
                ),
            )
            self.conn.execute(
                "DELETE FROM thirteenf_positions WHERE accession = ?", (report.accession,)
            )
            self.conn.executemany(
                "INSERT INTO thirteenf_positions VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        report.accession,
                        c,
                        report.shares[c],
                        report.values.get(c, 0.0),
                        report.names.get(c, ""),
                    )
                    for c in report.shares
                ],
            )

    def has_report(self, accession: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM thirteenf_reports WHERE accession = ?", (accession,)
            ).fetchone()
            is not None
        )

    def reports_for(self, ciks: Iterable[str] | None, period: date) -> list[sqlite3.Row]:
        sql = "SELECT * FROM thirteenf_reports WHERE period = ?"
        args: list[Any] = [period.isoformat()]
        if ciks is not None:
            wanted = list(ciks)
            sql += f" AND cik IN ({','.join('?' * len(wanted))})"
            args += wanted
        return self.conn.execute(sql, args).fetchall()

    def previous_report(self, cik: str, before: date) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM thirteenf_reports WHERE cik = ? AND period < ? "
            "ORDER BY period DESC, filing_date LIMIT 1",
            (cik, before.isoformat()),
        ).fetchone()

    def positions(self, accession: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM thirteenf_positions WHERE accession = ?", (accession,)
        ).fetchall()

    # ------------------------------------------------------------------- short

    def save_short_interest(self, records) -> int:
        rows = [
            (
                r.symbol,
                r.settlement_date.isoformat(),
                r.short_shares,
                r.previous_short_shares,
                r.days_to_cover,
                r.avg_daily_volume,
                r.market,
                r.name,
            )
            for r in records
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO short_interest VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.conn.commit()
        return len(rows)

    def short_interest_dates(self) -> set[str]:
        rows = self.conn.execute("SELECT DISTINCT settlement_date FROM short_interest").fetchall()
        return {r[0] for r in rows}

    def short_history(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM short_interest WHERE symbol = ? ORDER BY settlement_date DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_short_volume(self, rows) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO short_volume VALUES (?, ?, ?, ?)",
            [(r.symbol, r.day.isoformat(), r.short_volume, r.total_volume) for r in rows],
        )
        self.conn.execute(
            "DELETE FROM short_volume WHERE day < ?",
            ((date.today() - timedelta(days=60)).isoformat(),),
        )
        self.conn.commit()

    def short_volume_history(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM short_volume WHERE symbol = ? ORDER BY day DESC LIMIT ?", (symbol, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def save_fails(self, fails) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO fails_to_deliver VALUES (?, ?, ?, ?, ?)",
            [
                (f.symbol, f.settlement_date.isoformat(), f.cusip, f.quantity, f.price)
                for f in fails
            ],
        )
        self.conn.execute(
            "DELETE FROM fails_to_deliver WHERE settlement_date < ?",
            ((date.today() - timedelta(days=400)).isoformat(),),
        )
        self.conn.commit()

    def fails_history(self, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM fails_to_deliver WHERE symbol = ? ORDER BY settlement_date DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]
