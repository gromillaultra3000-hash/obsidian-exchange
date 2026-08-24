CREATE TABLE e4_action_reservations(
 reservation_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL UNIQUE,
 draft_id TEXT NOT NULL UNIQUE,
 assessment_id TEXT NOT NULL,
 principal_ref TEXT NOT NULL,
 actor_user_id BIGINT NOT NULL CHECK(actor_user_id>0),
 idempotency_key_sha256 TEXT NOT NULL,
 workflow_mapping TEXT NOT NULL CHECK(workflow_mapping IN
  ('BUY_ORDER_CREATION','SELL_ORDER_CREATION')),
 payload_sha256 TEXT NOT NULL,
 quote_expires_at_epoch_ms BIGINT NOT NULL,
 requested_at_epoch_ms BIGINT NOT NULL CHECK(requested_at_epoch_ms>0),
 expires_at_epoch_ms BIGINT NOT NULL CHECK(expires_at_epoch_ms>requested_at_epoch_ms
  AND expires_at_epoch_ms<=quote_expires_at_epoch_ms),
 state TEXT NOT NULL CHECK(state IN('reserved','committed')),
 result_kind TEXT CHECK(result_kind IN('BUY_ORDER','SELL_ORDER')),
 result_id BIGINT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(principal_ref,idempotency_key_sha256)
);
