import sqlite3
from datetime import date

import pytest

from daily_digest_agent.exceptions import StorageSchemaError
from daily_digest_agent.storage.d1 import D1StateStore
from daily_digest_agent.storage.schema import SCHEMA_VERSION
from daily_digest_agent.storage.sqlite import SQLiteStateStore
from tests.test_storage_contract import SQLiteBackedD1Store


def test_sqlite_usage_uses_explicit_local_month_at_utc_boundary(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    store.record_usage("run", date(2026, 8, 31), "google", "model", 10, 5, 0.01)
    with store._connect() as db:
        db.execute("UPDATE usage SET occurred_at='2026-09-01T03:30:00+00:00'")
        row = db.execute("SELECT occurred_at,local_date,local_month FROM usage").fetchone()
    assert row["local_date"] == "2026-08-31"
    assert row["local_month"] == "2026-08"
    assert store.get_usage(date(2026, 8, 31)).provider_calls_month == {"google": 1}
    assert store.get_usage(date(2026, 9, 1)).provider_calls_month == {}


def test_sqlite_migrates_legacy_usage_table(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, estimated_cost_usd REAL)""")
        db.execute(
            "INSERT INTO usage(run_id,occurred_at,provider,model,input_tokens,output_tokens) VALUES(?,?,?,?,?,?)",
            ("run", "2026-09-01T03:30:00+00:00", "google", "model", 1, 1),
        )
    store = SQLiteStateStore(str(path))
    store.initialize()
    with store._connect() as db:
        row = db.execute("SELECT local_date,local_month FROM usage").fetchone()
    assert tuple(row) == ("2026-09-01", "2026-09")


def test_sqlite_initialize_is_repeatable_and_preserves_schema_version(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    store.initialize()
    with store._connect() as db:
        assert db.execute("SELECT version FROM schema_meta").fetchone()["version"] == SCHEMA_VERSION


def test_sqlite_rejects_future_schema_version(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    with store._connect() as db:
        db.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION + 1,))
    with pytest.raises(StorageSchemaError, match="newer than supported"):
        store.initialize()


def test_d1_initialize_is_repeatable_and_preserves_schema_version():
    store = SQLiteBackedD1Store()
    store.initialize()
    store.initialize()
    assert store._query("SELECT version FROM schema_meta") == [{"version": SCHEMA_VERSION}]


def test_d1_rejects_future_schema_version():
    store = SQLiteBackedD1Store()
    store.initialize()
    store._query("UPDATE schema_meta SET version=?", [SCHEMA_VERSION + 1])
    with pytest.raises(StorageSchemaError, match="newer than supported"):
        store.initialize()


def test_sqlite_migrates_sent_digests_to_delivery_history(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    with store._connect() as db:
        db.execute("DELETE FROM deliveries")
        db.execute("UPDATE schema_meta SET version=2")
        db.execute(
            """INSERT INTO digests(
            id,run_id,digest_date,subject,plain_text,html,story_ids_json,generated_at,sent_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("digest", "run", "2026-08-30", "Subject", "Body", "<p>Body</p>", "[]",
             "2026-08-30T12:00:00+00:00", "2026-08-30T12:01:00+00:00"),
        )
    store.initialize()
    with store._connect() as db:
        row = db.execute("SELECT digest_date,attempt,state,digest_id FROM deliveries").fetchone()
    assert tuple(row) == ("2026-08-30", 0, "sent", "digest")


def test_sqlite_migrates_version_three_to_budget_reservations(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    with store._connect() as db:
        db.execute("DROP TABLE budget_reservations")
        db.execute("UPDATE schema_meta SET version=3")
    store.initialize()
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) count FROM budget_reservations").fetchone()["count"] == 0


def test_sqlite_migrates_version_four_to_delivery_receipts(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    with store._connect() as db:
        db.execute("UPDATE schema_meta SET version=4")
        db.execute("ALTER TABLE deliveries RENAME TO deliveries_v5")
        db.execute("""CREATE TABLE deliveries (
            id TEXT PRIMARY KEY, digest_date TEXT NOT NULL, attempt INTEGER NOT NULL,
            run_id TEXT NOT NULL, digest_id TEXT, state TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, error TEXT, UNIQUE(digest_date,attempt))""")
        db.execute("""INSERT INTO deliveries(
            id,digest_date,attempt,run_id,digest_id,state,created_at,updated_at,error
        ) SELECT id,digest_date,attempt,run_id,digest_id,state,created_at,updated_at,error FROM deliveries_v5""")
        db.execute("DROP TABLE deliveries_v5")
    store.initialize()
    with store._connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(deliveries)")}
    assert {"provider", "provider_message_id"} <= columns


def test_sqlite_migrates_version_five_to_reservation_release_audit(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    with store._connect() as db:
        db.execute("UPDATE schema_meta SET version=5")
        db.execute("ALTER TABLE budget_reservations RENAME TO budget_reservations_v6")
        db.execute("""CREATE TABLE budget_reservations (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, local_date TEXT NOT NULL,
            local_month TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            reserved_cost_usd REAL NOT NULL, actual_cost_usd REAL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO budget_reservations(
            id,run_id,local_date,local_month,provider,model,reserved_cost_usd,actual_cost_usd,
            state,created_at,updated_at
        ) SELECT id,run_id,local_date,local_month,provider,model,reserved_cost_usd,actual_cost_usd,
            state,created_at,updated_at FROM budget_reservations_v6""")
        db.execute("DROP TABLE budget_reservations_v6")
    store.initialize()
    with store._connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(budget_reservations)")}
    assert {"released_at", "release_reason"} <= columns


def test_d1_usage_queries_and_insert_use_logical_dates():
    store = object.__new__(D1StateStore)
    calls = []

    def query(sql, params=None):
        calls.append((sql, params or []))
        if "COALESCE" in sql:
            return [{"cost": 0}]
        return []

    store._query = query
    store.record_usage("run", date(2026, 8, 31), "google", "model", 10, 5, 0.01)
    store.get_usage(date(2026, 8, 31))
    assert calls[0][1][2:4] == ["2026-08-31", "2026-08"]
    assert any("WHERE local_date=?" in sql for sql, _ in calls)
    assert any("WHERE local_month=?" in sql for sql, _ in calls)