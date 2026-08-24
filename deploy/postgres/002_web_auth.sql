-- Dashboard identity/session boundary. Apply only in PostgreSQL rehearsal.
CREATE TABLE web_users (
 id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, telegram_id BIGINT UNIQUE,
 telegram_username TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 totp_secret TEXT, totp_enabled BOOLEAN NOT NULL DEFAULT false
);
CREATE TABLE web_sessions (
 token TEXT PRIMARY KEY, web_user_id BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
 csrf_token TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_web_sessions_expiry ON web_sessions(expires_at);
