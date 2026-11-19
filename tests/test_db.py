"""SQLite storage, and the migration of databases written by the first version."""

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from radar.db import SCHEMA_VERSION, Database
from radar.edgar import parse_submission
from radar.models import FilingRef, Signal
from radar.parsers.form4 import parse_form4
from radar.parsers.sc13d import parse_13d
from tests.conftest import read_fixture


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


def ref(accession: str = "0001831686-26-000014", form: str = "4") -> FilingRef:
    return FilingRef(
        accession=accession,
        form=form,
        cik="1801368",
        company="MP Materials Corp. / DE",
        filed_date=date(2026, 11, 17),
        url=f"https://www.sec.gov/Archives/edgar/data/1801368/x/{accession}-index.htm",
    )


def signal(key: str = "cluster_buy:1:2026-11-17") -> Signal:
    return Signal(
        type="cluster_buy",
        dedupe_key=key,
        issuer_cik="1",
        issuer_name="Company",
        ticker="CMP",
        signal_date=date(2026, 11, 17),
        score=70.0,
        explanation="explanation",
        trigger_accession="acc",
        details={"n_insiders": 2},
    )


def test_filings_are_never_duplicated(db):
    assert db.add_filing(ref()) is True
    assert db.add_filing(ref()) is False
    assert db.count_filings() == 1
    assert db.has_filing("0001831686-26-000014")
    assert [r.accession for r in db.pending_filings()] == ["0001831686-26-000014"]
    status = db.conn.execute("SELECT status FROM filings").fetchone()[0]
    assert status == "new"


def test_processed_filings_leave_the_pending_queue(db):
    db.add_filing(ref())
    db.mark_filing("0001831686-26-000014", "processed")
    assert db.pending_filings() == []


def test_form4_roundtrip_builds_purchase_filings(db):
    accession = "0001831686-26-000014"
    sub = parse_submission(read_fixture(f"{accession}.txt"))
    db.add_filing(ref(accession))
    db.save_form4(accession, sub.filed_date, parse_form4(sub.primary_document.xml))

    (purchase,) = db.purchase_filings("1801368")
    assert purchase.accession == accession
    assert purchase.ticker == "MP"
    assert purchase.filing_date == date(2026, 11, 17)
    assert purchase.is_cfo and not purchase.is_ceo
    assert purchase.is_officer_or_director
    assert purchase.officer_title == "Chief Financial Officer"
    assert purchase.value == pytest.approx(91_577.22)
    assert purchase.purchases[0].shares_after == 120_620
    assert purchase.shares_after == 120_620
    assert db.issuers_with_purchases([accession]) == ["1801368"]


def test_filings_without_purchases_are_not_purchase_filings(db):
    accession = "0001782135-26-000037"  # option exercise and sales
    sub = parse_submission(read_fixture(f"{accession}.txt"))
    db.add_filing(ref(accession))
    db.save_form4(accession, sub.filed_date, parse_form4(sub.primary_document.xml))
    assert db.purchase_filings("882095") == []
    rows = db.conn.execute("SELECT code FROM form4_transactions ORDER BY position").fetchall()
    assert [r["code"] for r in rows] == [
        "M",
        "S",
        "S",
        "S",
    ]  # stored even though they are not a signal


def test_13d_is_stored_with_reporters(db):
    accession = "0001213900-26-121050"
    db.add_filing(ref(accession, "SCHEDULE 13D"))
    db.save_13d(accession, parse_13d(parse_submission(read_fixture(f"{accession}.txt"))))
    row = db.conn.execute("SELECT * FROM sc13d").fetchone()
    assert row["max_percent"] == 15.56 and row["is_amendment"] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM sc13d_reporters").fetchone()[0] == 4


def test_signals_are_deduplicated_by_key(db):
    first = signal()
    assert db.add_signal(first) is True and first.id is not None
    assert db.add_signal(signal()) is False
    assert len(db.list_signals()) == 1
    assert db.prior_signal_dates("cluster_buy", "1") == [date(2026, 11, 17)]


def test_list_signals_filters_by_date_and_type(db):
    db.add_signal(signal())
    assert db.list_signals(since=date(2026, 11, 18)) == []
    assert db.list_signals(signal_type="big_officer_buy") == []
    (found,) = db.list_signals(since=date(2026, 11, 1), signal_type="cluster_buy")
    assert found.details == {"n_insiders": 2}


def test_ai_cache_and_hourly_counter(db):
    assert db.cached_ai_summary("acc", "cluster_buy") is None
    db.store_ai_summary("acc", "cluster_buy", "haiku", "summary")
    db.store_ai_summary("acc", "cluster_buy", "haiku", "resumo", "pt-BR")
    assert db.cached_ai_summary("acc", "cluster_buy") == "summary"
    assert db.cached_ai_summary("acc", "cluster_buy", "pt-BR") == "resumo"
    assert db.cached_ai_summaries("acc", "cluster_buy") == {"en": "summary", "pt-BR": "resumo"}
    assert db.cached_ai_summary("acc", "big_officer_buy") is None

    db.record_ai_call(ok=True)
    db.record_ai_call(ok=False)
    assert db.ai_calls_last_hour() == 2
    assert db.ai_calls_last_hour(datetime.now(UTC) + timedelta(hours=2)) == 0


def test_filing_brief_uses_english_codes(db):
    accession = "0001782135-26-000037"
    sub = parse_submission(read_fixture(f"{accession}.txt"))
    db.add_filing(ref(accession))
    db.save_form4(accession, sub.filed_date, parse_form4(sub.primary_document.xml))
    db.mark_filing(accession, "processed")
    brief = db.filing_brief(accession)
    assert brief["kind"] in {"sale", "exercise"} and brief["status"] == "processed"
    assert [b["accession"] for b in db.recent_filings()] == [accession]

    thirteen_d = "0001213900-26-121050"
    db.add_filing(ref(thirteen_d, "SCHEDULE 13D"))
    db.save_13d(thirteen_d, parse_13d(parse_submission(read_fixture(f"{thirteen_d}.txt"))))
    brief = db.filing_brief(thirteen_d)
    assert brief["kind"] == "new_13d" and brief["role"] == "13D filer"


# ---------------------------------------------------------------- migration

OLD_SCHEMA = """
CREATE TABLE filings (
    accession TEXT PRIMARY KEY, form TEXT NOT NULL, cik TEXT NOT NULL,
    company TEXT NOT NULL, filed_date TEXT NOT NULL, accepted_at TEXT, url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'novo', error TEXT, first_seen_at TEXT NOT NULL
);
CREATE INDEX idx_filings_status ON filings(status);
CREATE TABLE form4 (
    accession TEXT PRIMARY KEY REFERENCES filings(accession), document_type TEXT NOT NULL,
    issuer_cik TEXT NOT NULL, issuer_name TEXT NOT NULL, ticker TEXT NOT NULL,
    period_of_report TEXT, filed_date TEXT NOT NULL, remarks TEXT
);
CREATE TABLE sc13d (
    accession TEXT PRIMARY KEY REFERENCES filings(accession), form TEXT NOT NULL,
    is_amendment INTEGER NOT NULL, issuer_cik TEXT, issuer_name TEXT, cusip TEXT,
    event_date TEXT, max_percent REAL, source_format TEXT NOT NULL, purpose TEXT
);
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE,
    issuer_cik TEXT, issuer_name TEXT, ticker TEXT, signal_date TEXT NOT NULL,
    score REAL NOT NULL, explanation TEXT NOT NULL, summary TEXT, summary_source TEXT,
    trigger_accession TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL,
    alerted_at TEXT
);
CREATE TABLE ai_summaries (
    accession TEXT NOT NULL, signal_type TEXT NOT NULL, model TEXT NOT NULL,
    summary TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (accession, signal_type)
);
CREATE TABLE issuers (
    cik TEXT PRIMARY KEY, sic TEXT, sector TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

OLD_CLUSTER = {
    "insiders": [
        {"nome": "Doe Jane", "cargo": "CFO", "valor": 78_000.0},
        {"nome": "Roe Rick", "cargo": "diretor/executivo", "valor": 66_000.0},
    ],
    "n_insiders": 2,
    "n_insiders_od": 2,
    "valor_total": 144_000.0,
    "acoes": 1_000.0,
    "preco_medio": 144.0,
    "primeira_compra": "2026-11-10",
    "ultima_compra": "2026-11-12",
    "tem_ceo_cfo": True,
    "accessions": ["acc-1", "acc-2"],
}
OLD_13D = {
    "declarante": "Declarante não identificado",
    "percentual": 9.9,
    "acoes": 1_000.0,
    "codeclarantes": ["Fund LP"],
    "data_evento": "2026-11-01",
    "cusip": "123",
    "formato": "legado",
    "tom_ativista": False,
    "proposito": "Investment.",
    "accessions": ["acc-3"],
}


def old_database(path) -> None:
    """A database as the first (Portuguese) version left it."""
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    for accession, status in (
        ("acc-1", "processado"),
        ("acc-2", "novo"),
        ("acc-3", "erro"),
        ("acc-4", "ignorado"),
    ):
        conn.execute(
            "INSERT INTO filings (accession, form, cik, company, filed_date, url, status,"
            " first_seen_at) VALUES (?, '4', '1', 'Acme', '2026-11-12', 'u', ?, 'now')",
            (accession, status),
        )
    conn.execute(
        "INSERT INTO form4 VALUES ('acc-1', '4', '1', 'Acme', 'ACME', NULL, '2026-11-12', NULL)"
    )
    conn.execute(
        "INSERT INTO sc13d VALUES ('acc-3', 'SC 13D', 0, '1', 'Acme', '123', NULL, 9.9,"
        " 'legado', 'Investment.')"
    )
    rows = [
        ("cluster_buy", "c", "acc-2", OLD_CLUSTER, "Quem: 2 insiders.", "ia"),
        ("activist_13d", "a", "acc-3", OLD_13D, "Quem: declarante.", "template"),
        ("cluster_buy", "old", "acc-1", OLD_CLUSTER, None, None),
    ]
    for kind, key, accession, details, summary, source in rows:
        conn.execute(
            "INSERT INTO signals (type, dedupe_key, issuer_cik, issuer_name, ticker, signal_date,"
            " score, explanation, summary, summary_source, trigger_accession, details,"
            " created_at) VALUES (?, ?, '1', 'Acme', 'ACME', '2026-11-12', 70, 'texto antigo',"
            " ?, ?, ?, ?, '2026-11-12T10:00:00+00:00')",
            (kind, key, summary, source, accession, json.dumps(details, ensure_ascii=False)),
        )
    conn.execute(
        "INSERT INTO ai_summaries VALUES ('acc-2', 'cluster_buy', 'haiku', 'Resumo da IA.', 'now')"
    )
    conn.execute("INSERT INTO issuers VALUES ('1', '2834', 'Saúde', 'now')")
    conn.execute("INSERT INTO issuers VALUES ('2', '', 'Sem setor', 'now')")
    conn.commit()
    conn.close()


def test_a_database_from_the_first_version_is_migrated(tmp_path):
    path = tmp_path / "radar.sqlite"
    old_database(path)

    with Database(path) as db:
        conn = db.conn
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        statuses = dict(conn.execute("SELECT accession, status FROM filings").fetchall())
        assert statuses == {
            "acc-1": "processed",
            "acc-2": "new",
            "acc-3": "error",
            "acc-4": "skipped",
        }
        assert [r.accession for r in db.pending_filings()] == ["acc-2"]
        # The rebuilt table defaults to the English code and keeps its foreign keys working.
        conn.execute(
            "INSERT INTO filings (accession, form, cik, company, filed_date, url, first_seen_at)"
            " VALUES ('acc-5', '4', '1', 'Acme', '2026-11-13', 'u', 'now')"
        )
        assert db.count_pending() == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO form4 VALUES ('nope', '4', '1', 'A', 'A', NULL, 'd', NULL)")
        conn.rollback()

        assert conn.execute("SELECT source_format FROM sc13d").fetchone()[0] == "legacy"
        sectors = dict(conn.execute("SELECT cik, sector FROM issuers").fetchall())
        assert sectors == {"1": "Healthcare", "2": "Unclassified"}

        assert db.cached_ai_summaries("acc-2", "cluster_buy") == {"pt-BR": "Resumo da IA."}

        signals = {s.dedupe_key: s for s in db.list_signals()}
        cluster = signals["c"]
        assert cluster.details["insiders"] == [
            {"name": "Doe Jane", "role": "CFO", "value": 78_000.0},
            {"name": "Roe Rick", "role": "Director/Officer", "value": 66_000.0},
        ]
        assert cluster.details["total_value"] == 144_000.0
        assert cluster.details["n_officer_director"] == 2 and cluster.details["has_ceo_cfo"]
        assert "valor_total" not in cluster.details
        assert cluster.explanation.startswith("2 distinct insiders bought $144K of Acme (ACME)")
        assert "14-day window" in cluster.explanation  # default window: it was not stored
        # The Portuguese AI summary stays in ai_summaries; the English column gets the template.
        assert cluster.summary_source == "template"
        assert cluster.summary.startswith("Who: 2 insiders at Acme (ACME)")

        activist = signals["a"]
        assert activist.details["filer"] == "Unidentified filer"
        assert activist.details["source_format"] == "legacy"
        assert activist.details["co_filers"] == ["Fund LP"]
        assert activist.explanation.endswith("check the filing.")
        assert activist.summary.startswith("Who: Unidentified filer reported a stake in Acme")

        stored_only = signals["old"]
        assert stored_only.summary == "" and stored_only.summary_source == ""
        assert stored_only.explanation.startswith("2 distinct insiders")


def test_migration_prefers_a_cached_english_ai_summary(tmp_path):
    # An old database whose AI cache already has an English text (per-language table).
    path = tmp_path / "radar.sqlite"
    old_database(path)
    conn = sqlite3.connect(path)
    conn.executescript(
        "ALTER TABLE ai_summaries RENAME TO old_ai;"
        "CREATE TABLE ai_summaries (accession TEXT, signal_type TEXT, lang TEXT, model TEXT,"
        " summary TEXT, created_at TEXT, PRIMARY KEY (accession, signal_type, lang));"
        "INSERT INTO ai_summaries VALUES ('acc-2', 'cluster_buy', 'en', 'haiku', 'AI text.', 'now');"
        "INSERT INTO ai_summaries VALUES ('acc-2', 'cluster_buy', 'pt-BR', 'haiku', 'IA.', 'now');"
        "DROP TABLE old_ai;"
    )
    conn.close()
    with Database(path) as db:
        cluster = next(s for s in db.list_signals() if s.dedupe_key == "c")
        assert (cluster.summary, cluster.summary_source) == ("AI text.", "ai")
        assert db.cached_ai_summaries("acc-2", "cluster_buy") == {"en": "AI text.", "pt-BR": "IA."}


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "radar.sqlite"
    old_database(path)
    with Database(path) as db:
        first = [(s.dedupe_key, s.details, s.explanation, s.summary) for s in db.list_signals()]
    with Database(path) as db:
        again = [(s.dedupe_key, s.details, s.explanation, s.summary) for s in db.list_signals()]
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert first == again


def test_a_failed_migration_leaves_the_database_untouched(tmp_path, monkeypatch):
    import radar.db

    path = tmp_path / "radar.sqlite"
    old_database(path)

    def broken(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(radar.db, "_migrate_signals_v1", broken)
    with pytest.raises(RuntimeError, match="boom"):
        Database(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM filings WHERE accession = 'acc-1'").fetchone()[0] == (
        "processado"
    )
    assert conn.execute("SELECT COUNT(*) FROM ai_summaries").fetchone()[0] == 1
    conn.close()


def test_a_new_database_starts_at_the_current_version(tmp_path):
    with Database(tmp_path / "fresh.sqlite") as db:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_placeholder_tickers_are_cleared_when_migrating_to_v2(tmp_path):
    path = tmp_path / "radar.sqlite"
    accession = "0001831686-26-000014"
    sub = parse_submission(read_fixture(f"{accession}.txt"))
    with Database(path) as db:
        db.add_filing(ref(accession))
        db.save_form4(accession, sub.filed_date, parse_form4(sub.primary_document.xml))
        db.conn.execute("UPDATE form4 SET ticker = 'NONE'")
        db.conn.execute("PRAGMA user_version = 1")
        db.conn.commit()
    with Database(path) as db:
        assert db.conn.execute("SELECT ticker FROM form4").fetchone()[0] == ""
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
