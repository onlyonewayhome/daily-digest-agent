SCHEMA_VERSION = 4

SCHEMA_META_SQL = """CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER NOT NULL
)"""

STORIES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY,
  canonical_url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  publisher TEXT,
  published_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  category TEXT,
  relevance_score REAL NOT NULL,
  importance INTEGER NOT NULL,
  story_key TEXT NOT NULL,
  factual_summary TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  included_in_digest INTEGER NOT NULL DEFAULT 0,
  digest_id TEXT
)"""

RUNS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  local_date TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  forced INTEGER NOT NULL,
  error TEXT
)"""

DIGESTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS digests (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  digest_date TEXT NOT NULL,
  subject TEXT NOT NULL,
  plain_text TEXT NOT NULL,
  html TEXT NOT NULL,
  story_ids_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  sent_at TEXT
)"""

USAGE_V1_TABLE_SQL = """CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  estimated_cost_usd REAL
)"""

BASE_SCHEMA_STATEMENTS = (
    STORIES_TABLE_SQL,
    RUNS_TABLE_SQL,
    DIGESTS_TABLE_SQL,
    USAGE_V1_TABLE_SQL,
    "CREATE INDEX IF NOT EXISTS idx_stories_published ON stories(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_stories_first_seen ON stories(first_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_stories_story_key ON stories(story_key)",
    "CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(local_date)",
    "CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(digest_date)",
    "CREATE INDEX IF NOT EXISTS idx_usage_occurred ON usage(occurred_at)",
)

USAGE_DATE_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_usage_local_date ON usage(local_date)",
    "CREATE INDEX IF NOT EXISTS idx_usage_local_month ON usage(local_month)",
)

DELIVERIES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS deliveries (
  id TEXT PRIMARY KEY,
  digest_date TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  run_id TEXT NOT NULL,
  digest_id TEXT,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  error TEXT,
  UNIQUE(digest_date, attempt)
)"""

DELIVERY_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_deliveries_date ON deliveries(digest_date)",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_state ON deliveries(state)",
)

BUDGET_RESERVATIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS budget_reservations (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  local_date TEXT NOT NULL,
  local_month TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  reserved_cost_usd REAL NOT NULL,
  actual_cost_usd REAL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)"""

BUDGET_RESERVATION_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_budget_reservations_month ON budget_reservations(local_month)",
    "CREATE INDEX IF NOT EXISTS idx_budget_reservations_state ON budget_reservations(state)",
)