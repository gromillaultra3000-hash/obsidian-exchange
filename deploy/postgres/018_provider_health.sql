CREATE TABLE provider_health(provider TEXT PRIMARY KEY,avg_response_time DOUBLE PRECISION NOT NULL DEFAULT 0,
 failed_count INTEGER NOT NULL DEFAULT 0,last_checked TIMESTAMPTZ,is_healthy BOOLEAN NOT NULL DEFAULT true,
 status TEXT NOT NULL DEFAULT '',blocker TEXT NOT NULL DEFAULT '');
CREATE TABLE provider_attempts(provider TEXT NOT NULL,ts TIMESTAMPTZ NOT NULL,success BOOLEAN NOT NULL DEFAULT true);
CREATE INDEX idx_provider_attempts ON provider_attempts(provider,ts);
