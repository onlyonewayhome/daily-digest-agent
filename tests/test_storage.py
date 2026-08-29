import sqlite3
from datetime import date

from daily_digest_agent.storage.d1 import D1StateStore
from daily_digest_agent.storage.sqlite import SQLiteStateStore


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