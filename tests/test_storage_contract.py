import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from daily_digest_agent.models import Digest, SourceRecord, Story
from daily_digest_agent.storage.base import StateStore
from daily_digest_agent.storage.d1 import D1StateStore
from daily_digest_agent.storage.sqlite import SQLiteStateStore


class SQLiteBackedD1Store(D1StateStore):
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row

    def _query(self, sql, params=None):
        cursor = self.db.execute(sql, params or [])
        rows = [dict(row) for row in cursor.fetchall()]
        self.db.commit()
        return rows


class InterleavingD1Store(SQLiteBackedD1Store):
    def __init__(self) -> None:
        super().__init__()
        self.before_insert = None

    def _query(self, sql, params=None):
        if self.before_insert is not None and sql.lstrip().startswith("INSERT INTO budget_reservations"):
            callback = self.before_insert
            self.before_insert = None
            callback()
        return super()._query(sql, params)


@pytest.fixture(params=["sqlite", "d1"], ids=["sqlite", "d1"])
def store(request, tmp_path) -> StateStore:
    value: StateStore
    if request.param == "sqlite":
        value = SQLiteStateStore(str(tmp_path / "state.db"))
    else:
        value = SQLiteBackedD1Store()
    value.initialize()
    return value


def sample_story(now: datetime) -> Story:
    return Story(
        canonical_url="https://example.com/story",
        title="Original title",
        publisher="Example",
        published_at=now - timedelta(hours=1),
        first_seen_at=now,
        last_seen_at=now,
        category="major_news",
        relevance_score=0.9,
        importance=4,
        story_key="example-story",
        factual_summary="Original fact.",
        sources=[SourceRecord(title="Original source", url="https://example.com/story")],
    )


def test_story_lifecycle_contract(store):
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    story = sample_story(now)

    assert not store.story_exists(story.canonical_url)
    story_id = store.upsert_story(story)
    assert store.story_exists(story.canonical_url)

    stored = store.get_recent_stories(now - timedelta(seconds=1))
    assert len(stored) == 1
    assert stored[0].id == story_id
    assert stored[0].title == "Original title"
    assert stored[0].sources == story.sources

    story.title = "Updated title"
    story.factual_summary = "Updated fact."
    story.last_seen_at = now + timedelta(hours=1)
    story.sources = [SourceRecord(title="Updated source", url="https://example.com/story")]
    assert store.upsert_story(story) == story_id

    updated = store.get_recent_stories(now - timedelta(seconds=1))
    assert len(updated) == 1
    assert updated[0].title == "Updated title"
    assert updated[0].factual_summary == "Updated fact."
    assert updated[0].last_seen_at == story.last_seen_at
    assert updated[0].sources == story.sources
    assert store.get_recent_stories(now + timedelta(seconds=1)) == []


def test_run_lifecycle_contract(store):
    local_date = date(2026, 8, 30)
    assert store.get_last_run() is None
    assert store.get_successful_runs(local_date) == 0

    failed_id = store.record_run_start(local_date, forced=True)
    store.record_run_finish(failed_id, "failed", "provider failure")
    assert store.get_successful_runs(local_date) == 0

    success_id = store.record_run_start(local_date, forced=False)
    store.record_run_finish(success_id, "success")

    assert store.get_successful_runs(local_date) == 1
    last = store.get_last_run()
    assert last is not None
    assert last["id"] == success_id
    assert last["status"] == "success"
    assert last["local_date"] == local_date.isoformat()
    assert last["forced"] == 0
    assert last["finished_at"] is not None


def test_usage_accounting_contract(store):
    august = date(2026, 8, 30)
    september = date(2026, 9, 1)
    store.record_usage("run-a", august, "google", "gemini", 10, 5, 0.01)
    store.record_usage("run-a", august, "google", "gemini", 20, 5, 0.02)
    store.record_usage("run-a", august, "openai", "writer", 30, 10, None)
    store.record_usage("run-b", september, "google", "gemini", 10, 5, 0.04)

    august_usage = store.get_usage(august)
    assert august_usage.provider_calls_today == {"google": 2, "openai": 1}
    assert august_usage.provider_calls_month == {"google": 2, "openai": 1}
    assert august_usage.estimated_monthly_cost_usd == pytest.approx(0.03)

    september_usage = store.get_usage(september)
    assert september_usage.provider_calls_today == {"google": 1}
    assert september_usage.provider_calls_month == {"google": 1}
    assert september_usage.estimated_monthly_cost_usd == pytest.approx(0.04)


def test_budget_reservation_contract(store):
    local_date = date(2026, 8, 30)
    reservation_id = store.reserve_budget("run", local_date, "google", "gemini", 0.40, 1.00)
    assert reservation_id is not None
    assert store.get_usage(local_date).reserved_monthly_cost_usd == pytest.approx(0.40)

    second_id = store.reserve_budget("run", local_date, "openai", "writer", 0.50, 1.00)
    assert second_id is not None
    assert store.reserve_budget("run", local_date, "google", "gemini", 0.11, 1.00) is None

    store.reconcile_budget(reservation_id, 0.10)
    usage = store.get_usage(local_date)
    assert usage.reserved_monthly_cost_usd == pytest.approx(0.50)

    store.record_usage("run", local_date, "google", "gemini", 10, 5, 0.10)
    assert store.reserve_budget("run", local_date, "google", "gemini", 0.40, 1.00) is not None


def test_d1_budget_reservation_uses_single_conditional_insert():
    store = SQLiteBackedD1Store()
    store.initialize()
    calls = []
    original = store._query

    def query(sql, params=None):
        calls.append(sql)
        return original(sql, params)

    store._query = query
    assert store.reserve_budget("run", date(2026, 8, 30), "google", "gemini", 0.40, 1.00) is not None
    reservation_calls = [sql for sql in calls if "budget_reservations" in sql]
    assert reservation_calls[0].lstrip().startswith("INSERT INTO budget_reservations")
    assert "WHERE COALESCE" in reservation_calls[0]


def test_d1_conditional_budget_insert_observes_competing_reservation():
    store = InterleavingD1Store()
    store.initialize()
    local_date = date(2026, 8, 30)

    def competing_insert():
        SQLiteBackedD1Store._query(
            store,
            """INSERT INTO budget_reservations(
            id,run_id,local_date,local_month,provider,model,reserved_cost_usd,state,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ["other", "run", local_date.isoformat(), "2026-08", "google", "gemini", 0.70,
             "reserved", "2026-08-30T00:00:00+00:00", "2026-08-30T00:00:00+00:00"],
        )

    store.before_insert = competing_insert
    assert store.reserve_budget("run", local_date, "google", "gemini", 0.40, 1.00) is None


def test_digest_and_sent_state_contract(store):
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    local_date = now.date()
    story_id = store.upsert_story(sample_story(now))
    run_id = store.record_run_start(local_date, forced=False)
    digest = Digest(
        digest_date=local_date,
        subject="Example Daily",
        plain_text="Plain body",
        html="<p>HTML body</p>",
        included_story_ids=[story_id],
        generated_at=now,
    )

    assert not store.digest_sent_for_date(local_date)
    digest_id = store.record_digest(digest, run_id)
    assert not store.digest_sent_for_date(local_date)

    story = store.get_recent_stories(now - timedelta(seconds=1))[0]
    assert story.included_in_digest
    assert story.digest_id == digest_id

    store.mark_digest_sent(digest_id, now + timedelta(minutes=1))
    assert store.digest_sent_for_date(local_date)
    assert not store.digest_sent_for_date(local_date + timedelta(days=1))


def test_delivery_reservation_contract(store):
    local_date = date(2026, 8, 30)
    run_id = store.record_run_start(local_date, forced=False)

    delivery_id = store.reserve_delivery(local_date, run_id)
    assert delivery_id is not None
    assert store.reserve_delivery(local_date, run_id) is None
    delivery = store.get_delivery(delivery_id)
    assert delivery is not None
    assert delivery["state"] == "pending"
    assert delivery["attempt"] == 1

    store.update_delivery(delivery_id, "sending", digest_id="digest-id")
    assert store.get_delivery(delivery_id)["state"] == "sending"
    store.update_delivery(delivery_id, "unknown", error="ambiguous failure")
    assert store.get_delivery(delivery_id)["state"] == "unknown"

    forced_id = store.reserve_delivery(local_date, run_id, force=True)
    assert forced_id is not None
    forced = store.get_delivery(forced_id)
    assert forced is not None
    assert forced["attempt"] == 2
    store.update_delivery(forced_id, "sent", digest_id="digest-id-2")
    assert store.get_delivery(forced_id)["state"] == "sent"