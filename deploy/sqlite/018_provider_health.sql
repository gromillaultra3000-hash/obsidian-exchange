CREATE TABLE provider_health(
  provider TEXT PRIMARY KEY,
  avg_response_time REAL NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  last_checked TEXT,
  is_healthy INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT '',
  blocker TEXT NOT NULL DEFAULT ''
);
CREATE TABLE provider_attempts(
  provider TEXT NOT NULL,
  ts TEXT NOT NULL,
  success INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_provider_attempts ON provider_attempts(provider,ts);
