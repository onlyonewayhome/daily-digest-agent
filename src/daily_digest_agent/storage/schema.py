SCHEMA_VERSION = 2

SCHEMA_META_SQL = """CREATE TABLE IF NOT EXISTS schema_meta (
  version INTEGER NOT NULL
)"""

USAGE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  local_date TEXT NOT NULL,
  local_month TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  estimated_cost_usd REAL
)"""