from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import httpx

from ..models import Digest, SourceRecord, Story, UsageSummary
from .schema import SCHEMA_META_SQL, SCHEMA_VERSION, USAGE_TABLE_SQL


class D1StateStore:
    def __init__(self, account_id: str, database_id: str, api_token: str) -> None:
        self.url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/"
            f"{database_id}/query"
        )
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {api_token}"}, timeout=30.0
        )

    def _query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        response = self.client.post(self.url, json={"sql": sql, "params": params or []})
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"D1 query failed: {payload.get('errors', [])}")
        results = payload.get("result", [])
        return results[0].get("results", []) if results else []

    def initialize(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS stories (id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL
            UNIQUE, title TEXT NOT NULL, publisher TEXT, published_at TEXT, first_seen_at TEXT NOT
            NULL, last_seen_at TEXT NOT NULL, category TEXT, relevance_score REAL NOT NULL,
            importance INTEGER NOT NULL, story_key TEXT NOT NULL, factual_summary TEXT NOT NULL,
            sources_json TEXT NOT NULL, included_in_digest INTEGER NOT NULL DEFAULT 0,
            digest_id TEXT)""",
            """CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, local_date TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, forced INTEGER NOT NULL,
            error TEXT)""",
            """CREATE TABLE IF NOT EXISTS digests (id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            digest_date TEXT NOT NULL, subject TEXT NOT NULL, plain_text TEXT NOT NULL, html TEXT NOT
            NULL, story_ids_json TEXT NOT NULL, generated_at TEXT NOT NULL, sent_at TEXT)""",
            SCHEMA_META_SQL,
            USAGE_TABLE_SQL,
            "CREATE INDEX IF NOT EXISTS idx_stories_published ON stories(published_at)",
            "CREATE INDEX IF NOT EXISTS idx_stories_first_seen ON stories(first_seen_at)",
            "CREATE INDEX IF NOT EXISTS idx_stories_story_key ON stories(story_key)",
            "CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(local_date)",
            "CREATE INDEX IF NOT EXISTS idx_usage_occurred ON usage(occurred_at)",
        ]
        for statement in statements:
            self._query(statement)
        columns = {row["name"] for row in self._query("PRAGMA table_info(usage)")}
        if "local_date" not in columns:
            self._query("ALTER TABLE usage ADD COLUMN local_date TEXT")
        if "local_month" not in columns:
            self._query("ALTER TABLE usage ADD COLUMN local_month TEXT")
        self._query("UPDATE usage SET local_date=substr(occurred_at,1,10) WHERE local_date IS NULL")
        self._query("UPDATE usage SET local_month=substr(occurred_at,1,7) WHERE local_month IS NULL")
        self._query("CREATE INDEX IF NOT EXISTS idx_usage_local_date ON usage(local_date)")
        self._query("CREATE INDEX IF NOT EXISTS idx_usage_local_month ON usage(local_month)")
        self._query("DELETE FROM schema_meta")
        self._query("INSERT INTO schema_meta(version) VALUES(?)", [SCHEMA_VERSION])

    def story_exists(self, canonical_url: str) -> bool:
        return bool(self._query("SELECT 1 FROM stories WHERE canonical_url=?", [canonical_url]))

    def upsert_story(self, story: Story) -> str:
        story_id = story.id or str(uuid.uuid4())
        params = [
            story_id, story.canonical_url, story.title, story.publisher,
            story.published_at.isoformat() if story.published_at else None,
            story.first_seen_at.isoformat(), story.last_seen_at.isoformat(), story.category,
            story.relevance_score, story.importance, story.story_key, story.factual_summary,
            json.dumps([source.model_dump(mode="json") for source in story.sources]),
            int(story.included_in_digest), story.digest_id,
        ]
        self._query(
            """INSERT INTO stories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(canonical_url)
            DO UPDATE SET last_seen_at=excluded.last_seen_at,title=excluded.title,
            publisher=excluded.publisher,published_at=excluded.published_at,
            category=excluded.category,relevance_score=excluded.relevance_score,
            importance=excluded.importance,story_key=excluded.story_key,
            factual_summary=excluded.factual_summary,sources_json=excluded.sources_json""",
            params,
        )
        return str(self._query("SELECT id FROM stories WHERE canonical_url=?", [story.canonical_url])[0]["id"])

    def get_recent_stories(self, since: datetime) -> list[Story]:
        rows = self._query(
            "SELECT * FROM stories WHERE first_seen_at>=? ORDER BY importance DESC",
            [since.isoformat()],
        )
        return [self._story(row) for row in rows]

    def _story(self, row: dict[str, Any]) -> Story:
        return Story(
            **{key: value for key, value in row.items() if key not in {"sources_json"}},
            sources=[SourceRecord.model_validate(value) for value in json.loads(row["sources_json"])],
            included_in_digest=bool(row["included_in_digest"]),
        )

    def record_run_start(self, local_date: date, forced: bool) -> str:
        run_id = str(uuid.uuid4())
        self._query(
            "INSERT INTO runs(id,local_date,started_at,status,forced) VALUES(?,?,?,?,?)",
            [run_id, local_date.isoformat(), datetime.now(UTC).isoformat(), "running", int(forced)],
        )
        return run_id

    def record_run_finish(self, run_id: str, status: str, error: str | None = None) -> None:
        self._query(
            "UPDATE runs SET finished_at=?,status=?,error=? WHERE id=?",
            [datetime.now(UTC).isoformat(), status, error, run_id],
        )

    def get_successful_runs(self, local_date: date) -> int:
        rows = self._query(
            "SELECT COUNT(*) count FROM runs WHERE local_date=? AND status='success'",
            [local_date.isoformat()],
        )
        return int(rows[0]["count"])

    def get_usage(self, local_date: date) -> UsageSummary:
        day = local_date.isoformat()
        month = day[:7]
        daily = self._query(
            "SELECT provider,COUNT(*) count FROM usage WHERE local_date=? GROUP BY provider",
            [day],
        )
        monthly = self._query(
            "SELECT provider,COUNT(*) count FROM usage WHERE local_month=? GROUP BY provider",
            [month],
        )
        costs = self._query(
            "SELECT COALESCE(SUM(estimated_cost_usd),0) cost FROM usage WHERE local_month=?",
            [month],
        )
        return UsageSummary(
            provider_calls_today={row["provider"]: row["count"] for row in daily},
            provider_calls_month={row["provider"]: row["count"] for row in monthly},
            estimated_monthly_cost_usd=float(costs[0]["cost"]),
        )

    def record_usage(self, run_id: str, local_date: date, provider: str, model: str, input_tokens: int,
                     output_tokens: int, estimated_cost_usd: float | None) -> None:
        self._query(
            """INSERT INTO usage(run_id,occurred_at,local_date,local_month,provider,model,input_tokens,
            output_tokens,estimated_cost_usd) VALUES(?,?,?,?,?,?,?,?,?)""",
            [run_id, datetime.now(UTC).isoformat(), local_date.isoformat(), local_date.strftime("%Y-%m"),
             provider, model, input_tokens, output_tokens, estimated_cost_usd],
        )

    def record_digest(self, digest: Digest, run_id: str) -> str:
        digest_id = digest.id or str(uuid.uuid4())
        self._query(
            "INSERT INTO digests VALUES(?,?,?,?,?,?,?,?,?)",
            [digest_id, run_id, digest.digest_date.isoformat(), digest.subject, digest.plain_text,
             digest.html, json.dumps(digest.included_story_ids), digest.generated_at.isoformat(), None],
        )
        for story_id in digest.included_story_ids:
            self._query(
                "UPDATE stories SET included_in_digest=1,digest_id=? WHERE id=?",
                [digest_id, story_id],
            )
        return digest_id

    def mark_digest_sent(self, digest_id: str, sent_at: datetime) -> None:
        self._query("UPDATE digests SET sent_at=? WHERE id=?", [sent_at.isoformat(), digest_id])

    def digest_sent_for_date(self, digest_date: date) -> bool:
        return bool(self._query(
            "SELECT 1 FROM digests WHERE digest_date=? AND sent_at IS NOT NULL",
            [digest_date.isoformat()],
        ))

    def get_last_run(self) -> dict[str, object] | None:
        rows = self._query("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1")
        return rows[0] if rows else None
