from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import httpx

from ..exceptions import DeliveryStateError, StorageSchemaError
from ..models import Digest, SourceRecord, Story, UsageSummary
from .schema import (
    BASE_SCHEMA_STATEMENTS,
    DELIVERIES_TABLE_SQL,
    DELIVERY_INDEX_STATEMENTS,
    SCHEMA_META_SQL,
    SCHEMA_VERSION,
    USAGE_DATE_INDEX_STATEMENTS,
)


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
        self._query(SCHEMA_META_SQL)
        rows = self._query("SELECT version FROM schema_meta LIMIT 1")
        version = int(rows[0]["version"]) if rows else 0
        if version > SCHEMA_VERSION:
            raise StorageSchemaError(
                f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}"
            )
        if version < 1:
            for statement in BASE_SCHEMA_STATEMENTS:
                self._query(statement)
            self._set_schema_version(1)
            version = 1
        if version < 2:
            columns = {row["name"] for row in self._query("PRAGMA table_info(usage)")}
            if "local_date" not in columns:
                self._query("ALTER TABLE usage ADD COLUMN local_date TEXT")
            if "local_month" not in columns:
                self._query("ALTER TABLE usage ADD COLUMN local_month TEXT")
            self._query("UPDATE usage SET local_date=substr(occurred_at,1,10) WHERE local_date IS NULL")
            self._query("UPDATE usage SET local_month=substr(occurred_at,1,7) WHERE local_month IS NULL")
            for statement in USAGE_DATE_INDEX_STATEMENTS:
                self._query(statement)
            self._set_schema_version(2)
            version = 2
        if version < 3:
            self._query(DELIVERIES_TABLE_SQL)
            for statement in DELIVERY_INDEX_STATEMENTS:
                self._query(statement)
            self._query("""INSERT INTO deliveries(
                id,digest_date,attempt,run_id,digest_id,state,created_at,updated_at,error
            ) SELECT id,digest_date,0,run_id,id,'sent',generated_at,COALESCE(sent_at,generated_at),NULL
              FROM digests WHERE sent_at IS NOT NULL""")
            self._set_schema_version(3)

    def _set_schema_version(self, version: int) -> None:
        self._query("DELETE FROM schema_meta")
        self._query("INSERT INTO schema_meta(version) VALUES(?)", [version])

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
            **{key: value for key, value in row.items() if key not in {"included_in_digest", "sources_json"}},
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

    def reserve_delivery(self, digest_date: date, run_id: str, force: bool = False) -> str | None:
        rows = self._query(
            "SELECT attempt,state FROM deliveries WHERE digest_date=? ORDER BY attempt DESC LIMIT 1",
            [digest_date.isoformat()],
        )
        if rows and not force:
            return None
        attempt = int(rows[0]["attempt"]) + 1 if rows else 1
        delivery_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        try:
            self._query(
                """INSERT INTO deliveries(
                id,digest_date,attempt,run_id,state,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)""",
                [delivery_id, digest_date.isoformat(), attempt, run_id, "pending", now, now],
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper() or "CONSTRAINT" in str(exc).upper():
                return None
            raise
        return delivery_id

    def update_delivery(self, delivery_id: str, state: str, digest_id: str | None = None,
                        error: str | None = None) -> None:
        if state not in {"pending", "sending", "sent", "failed", "unknown"}:
            raise DeliveryStateError(f"Unknown delivery state: {state}")
        self._query(
            """UPDATE deliveries SET state=?,digest_id=COALESCE(?,digest_id),updated_at=?,error=?
            WHERE id=?""",
            [state, digest_id, datetime.now(UTC).isoformat(), error, delivery_id],
        )

    def get_delivery(self, delivery_id: str) -> dict[str, object] | None:
        rows = self._query("SELECT * FROM deliveries WHERE id=?", [delivery_id])
        return rows[0] if rows else None

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
