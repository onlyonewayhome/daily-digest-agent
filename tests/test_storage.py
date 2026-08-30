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