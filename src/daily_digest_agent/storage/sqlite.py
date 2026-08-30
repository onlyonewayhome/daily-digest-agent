from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from ..exceptions import DeliveryStateError, StorageSchemaError
from ..models import Digest, SourceRecord, Story, UsageSummary
from .schema import (
    BASE_SCHEMA_STATEMENTS,
    BUDGET_RESERVATION_INDEX_STATEMENTS,
    BUDGET_RESERVATIONS_TABLE_SQL,
    DELIVERIES_TABLE_SQL,
    DELIVERY_INDEX_STATEMENTS,
    SCHEMA_META_SQL,
    SCHEMA_VERSION,
    USAGE_DATE_INDEX_STATEMENTS,
)


class SQLiteStateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(SCHEMA_META_SQL)
            row = db.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            version = int(row["version"]) if row else 0
            if version > SCHEMA_VERSION:
                raise StorageSchemaError(
                    f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}"
                )
            if version < 1:
                for statement in BASE_SCHEMA_STATEMENTS:
                    db.execute(statement)
                self._set_schema_version(db, 1)
                version = 1
            if version < 2:
                columns = {row["name"] for row in db.execute("PRAGMA table_info(usage)").fetchall()}
                if "local_date" not in columns:
                    db.execute("ALTER TABLE usage ADD COLUMN local_date TEXT")
                if "local_month" not in columns:
                    db.execute("ALTER TABLE usage ADD COLUMN local_month TEXT")
                db.execute("UPDATE usage SET local_date=substr(occurred_at,1,10) WHERE local_date IS NULL")
                db.execute("UPDATE usage SET local_month=substr(occurred_at,1,7) WHERE local_month IS NULL")
                for statement in USAGE_DATE_INDEX_STATEMENTS:
                    db.execute(statement)
                self._set_schema_version(db, 2)
                version = 2
            if version < 3:
                db.execute(DELIVERIES_TABLE_SQL)
                for statement in DELIVERY_INDEX_STATEMENTS:
                    db.execute(statement)
                db.execute("""INSERT INTO deliveries(
                    id,digest_date,attempt,run_id,digest_id,state,created_at,updated_at,error
                ) SELECT id,digest_date,0,run_id,id,'sent',generated_at,COALESCE(sent_at,generated_at),NULL
                  FROM digests WHERE sent_at IS NOT NULL""")
                self._set_schema_version(db, 3)
                version = 3
            if version < 4:
                db.execute(BUDGET_RESERVATIONS_TABLE_SQL)
                for statement in BUDGET_RESERVATION_INDEX_STATEMENTS:
                    db.execute(statement)
                self._set_schema_version(db, 4)

    @staticmethod
    def _set_schema_version(db: sqlite3.Connection, version: int) -> None:
        db.execute("DELETE FROM schema_meta")
        db.execute("INSERT INTO schema_meta(version) VALUES(?)", (version,))

    def story_exists(self, canonical_url: str) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM stories WHERE canonical_url=?", (canonical_url,)).fetchone() is not None

    def upsert_story(self, story: Story) -> str:
        story_id = story.id or str(uuid.uuid4())
        values = (story_id, story.canonical_url, story.title, story.publisher,
                  story.published_at.isoformat() if story.published_at else None,
                  story.first_seen_at.isoformat(), story.last_seen_at.isoformat(), story.category,
                  story.relevance_score, story.importance, story.story_key, story.factual_summary,
                  json.dumps([source.model_dump(mode="json") for source in story.sources]),
                  int(story.included_in_digest), story.digest_id)
        with self._connect() as db:
            db.execute("""INSERT INTO stories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(canonical_url) DO UPDATE SET last_seen_at=excluded.last_seen_at,
              title=excluded.title, publisher=excluded.publisher, published_at=excluded.published_at,
              category=excluded.category, relevance_score=excluded.relevance_score,
              importance=excluded.importance, story_key=excluded.story_key,
              factual_summary=excluded.factual_summary, sources_json=excluded.sources_json""", values)
            row = db.execute("SELECT id FROM stories WHERE canonical_url=?", (story.canonical_url,)).fetchone()
            return str(row["id"])

    def get_recent_stories(self, since: datetime) -> list[Story]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM stories WHERE first_seen_at>=? ORDER BY importance DESC",
                              (since.isoformat(),)).fetchall()
        return [self._story(row) for row in rows]

    def _story(self, row: sqlite3.Row) -> Story:
        return Story(id=row["id"], canonical_url=row["canonical_url"], title=row["title"],
                     publisher=row["publisher"], published_at=row["published_at"],
                     first_seen_at=row["first_seen_at"], last_seen_at=row["last_seen_at"],
                     category=row["category"], relevance_score=row["relevance_score"],
                     importance=row["importance"], story_key=row["story_key"],
                     factual_summary=row["factual_summary"],
                     sources=[SourceRecord.model_validate(value) for value in json.loads(row["sources_json"])],
                     included_in_digest=bool(row["included_in_digest"]), digest_id=row["digest_id"])

    def record_run_start(self, local_date: date, forced: bool) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO runs(id,local_date,started_at,status,forced) VALUES(?,?,?,?,?)",
                       (run_id, local_date.isoformat(), datetime.now(UTC).isoformat(), "running", int(forced)))
        return run_id

    def record_run_finish(self, run_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as db:
            db.execute("UPDATE runs SET finished_at=?,status=?,error=? WHERE id=?",
                       (datetime.now(UTC).isoformat(), status, error, run_id))

    def get_successful_runs(self, local_date: date) -> int:
        with self._connect() as db:
            row = db.execute("SELECT COUNT(*) count FROM runs WHERE local_date=? AND status='success'",
                             (local_date.isoformat(),)).fetchone()
            return int(row["count"])

    def get_usage(self, local_date: date) -> UsageSummary:
        day = local_date.isoformat()
        month = day[:7]
        with self._connect() as db:
            daily = db.execute(
                "SELECT provider,COUNT(*) count FROM usage WHERE local_date=? GROUP BY provider",
                (day,),
            ).fetchall()
            monthly = db.execute(
                "SELECT provider,COUNT(*) count FROM usage WHERE local_month=? GROUP BY provider",
                (month,),
            ).fetchall()
            cost = db.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd),0) cost FROM usage WHERE local_month=?",
                (month,),
            ).fetchone()
            reserved = db.execute(
                """SELECT COALESCE(SUM(reserved_cost_usd),0) cost FROM budget_reservations
                WHERE local_month=? AND state='reserved'""",
                (month,),
            ).fetchone()
        return UsageSummary(provider_calls_today={row["provider"]: row["count"] for row in daily},
                            provider_calls_month={row["provider"]: row["count"] for row in monthly},
                            estimated_monthly_cost_usd=float(cost["cost"]),
                            reserved_monthly_cost_usd=float(reserved["cost"]))

    def reserve_budget(self, run_id: str, local_date: date, provider: str, model: str,
                       reserved_cost_usd: float, monthly_limit_usd: float) -> str | None:
        reservation_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        month = local_date.strftime("%Y-%m")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            usage = db.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd),0) cost FROM usage WHERE local_month=?",
                (month,),
            ).fetchone()
            reserved = db.execute(
                """SELECT COALESCE(SUM(reserved_cost_usd),0) cost FROM budget_reservations
                WHERE local_month=? AND state='reserved'""",
                (month,),
            ).fetchone()
            if float(usage["cost"]) + float(reserved["cost"]) + reserved_cost_usd > monthly_limit_usd:
                return None
            db.execute(
                """INSERT INTO budget_reservations(
                id,run_id,local_date,local_month,provider,model,reserved_cost_usd,state,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (reservation_id, run_id, local_date.isoformat(), month, provider, model,
                 reserved_cost_usd, "reserved", now, now),
            )
        return reservation_id

    def reconcile_budget(self, reservation_id: str, actual_cost_usd: float) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE budget_reservations SET actual_cost_usd=?,state='reconciled',updated_at=? WHERE id=?""",
                (actual_cost_usd, datetime.now(UTC).isoformat(), reservation_id),
            )

    def record_usage(self, run_id: str, local_date: date, provider: str, model: str, input_tokens: int,
                     output_tokens: int, estimated_cost_usd: float | None) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO usage(run_id,occurred_at,local_date,local_month,provider,model,
                input_tokens,output_tokens,estimated_cost_usd) VALUES(?,?,?,?,?,?,?,?,?)""",
                (run_id, datetime.now(UTC).isoformat(), local_date.isoformat(), local_date.strftime("%Y-%m"),
                 provider, model, input_tokens, output_tokens, estimated_cost_usd),
            )

    def record_digest(self, digest: Digest, run_id: str) -> str:
        digest_id = digest.id or str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO digests VALUES(?,?,?,?,?,?,?,?,?)",
                       (digest_id, run_id, digest.digest_date.isoformat(), digest.subject, digest.plain_text,
                        digest.html, json.dumps(digest.included_story_ids), digest.generated_at.isoformat(), None))
            if digest.included_story_ids:
                db.executemany("UPDATE stories SET included_in_digest=1,digest_id=? WHERE id=?",
                               [(digest_id, story_id) for story_id in digest.included_story_ids])
        return digest_id

    def reserve_delivery(self, digest_date: date, run_id: str, force: bool = False) -> str | None:
        delivery_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT attempt,state FROM deliveries WHERE digest_date=? ORDER BY attempt DESC LIMIT 1",
                (digest_date.isoformat(),),
            ).fetchone()
            if row is not None and not force:
                return None
            attempt = int(row["attempt"]) + 1 if row is not None else 1
            try:
                db.execute(
                    """INSERT INTO deliveries(
                    id,digest_date,attempt,run_id,state,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (delivery_id, digest_date.isoformat(), attempt, run_id, "pending", now, now),
                )
            except sqlite3.IntegrityError:
                return None
        return delivery_id

    def update_delivery(self, delivery_id: str, state: str, digest_id: str | None = None,
                        error: str | None = None) -> None:
        if state not in {"pending", "sending", "sent", "failed", "unknown"}:
            raise DeliveryStateError(f"Unknown delivery state: {state}")
        with self._connect() as db:
            db.execute(
                """UPDATE deliveries SET state=?,digest_id=COALESCE(?,digest_id),updated_at=?,error=?
                WHERE id=?""",
                (state, digest_id, datetime.now(UTC).isoformat(), error, delivery_id),
            )

    def get_delivery(self, delivery_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            return dict(row) if row else None

    def mark_digest_sent(self, digest_id: str, sent_at: datetime) -> None:
        with self._connect() as db:
            db.execute("UPDATE digests SET sent_at=? WHERE id=?", (sent_at.isoformat(), digest_id))

    def digest_sent_for_date(self, digest_date: date) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM digests WHERE digest_date=? AND sent_at IS NOT NULL",
                              (digest_date.isoformat(),)).fetchone() is not None

    def get_last_run(self) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None
