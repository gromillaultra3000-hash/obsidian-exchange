-- PostgreSQL rehearsal schema for the money-moving boundary only.
-- Production remains on SQLite until every writer uses the shared DB layer.
CREATE TABLE payout_intents (
 id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE,
 idempotency_key TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL DEFAULT 'pending'
   CHECK (state IN ('pending','processing','succeeded','review')),
 source TEXT NOT NULL, requested_by TEXT, rub_amount NUMERIC(20,2) NOT NULL,
 crypto_amount NUMERIC(30,12) NOT NULL, currency TEXT NOT NULL,
 network TEXT, destination TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 txid TEXT, error_code TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 claimed_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_payout_intents_state ON payout_intents(state,created_at);

CREATE TABLE referral_payout_intents (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL DEFAULT 'pending'
   CHECK(state IN ('pending','processing','succeeded','review','reconciled')),
 crypto_amount NUMERIC(30,12) NOT NULL CHECK(crypto_amount > 0),
 currency TEXT NOT NULL DEFAULT 'BTC', network TEXT, destination TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, txid TEXT, error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), claimed_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_referral_payout_active ON referral_payout_intents(user_id)
 WHERE state IN ('pending','processing','succeeded','review');
CREATE INDEX idx_referral_payout_state ON referral_payout_intents(state,created_at);

CREATE TABLE payout_intent_audit (
 id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL,
 evidence TEXT NOT NULL, txid TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE referral_payout_intent_audit (
 id BIGSERIAL PRIMARY KEY, intent_id BIGINT NOT NULL REFERENCES referral_payout_intents(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, from_state TEXT NOT NULL,
 to_state TEXT NOT NULL, evidence TEXT NOT NULL, txid TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE payout_reconciliations (
 order_id BIGINT PRIMARY KEY, intent_id BIGINT NOT NULL UNIQUE REFERENCES payout_intents(id),
 txid TEXT NOT NULL, referral_btc NUMERIC(30,12) NOT NULL DEFAULT 0,
 vip_rub NUMERIC(20,2) NOT NULL, reconciled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE notification_outbox (
 id BIGSERIAL PRIMARY KEY, topic TEXT NOT NULL, aggregate_id TEXT NOT NULL,
 recipient_id BIGINT NOT NULL, payload JSONB NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sending','sent')),
 attempts INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 claimed_at TIMESTAMPTZ, sent_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(topic,aggregate_id)
);
CREATE INDEX idx_notification_outbox_state ON notification_outbox(state,created_at);

-- Canonical PostgreSQL claim: transaction + row lock prevents double workers
-- without relying on SQLite's database-wide writer serialization.
CREATE OR REPLACE FUNCTION claim_next_order_payout()
RETURNS SETOF payout_intents LANGUAGE sql AS $$
 WITH candidate AS (
   SELECT id FROM payout_intents WHERE state='pending'
   ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
 ), changed AS (
   UPDATE payout_intents p SET state='processing',attempts=p.attempts+1,
          claimed_at=now(),updated_at=now()
   FROM candidate c WHERE p.id=c.id AND p.state='pending' RETURNING p.*
 ) SELECT * FROM changed;
$$;

CREATE OR REPLACE FUNCTION claim_next_referral_payout()
RETURNS SETOF referral_payout_intents LANGUAGE sql AS $$
 WITH candidate AS (
   SELECT id FROM referral_payout_intents WHERE state='pending'
   ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
 ), changed AS (
   UPDATE referral_payout_intents p SET state='processing',attempts=p.attempts+1,
          claimed_at=now(),updated_at=now()
   FROM candidate c WHERE p.id=c.id AND p.state='pending' RETURNING p.*
 ) SELECT * FROM changed;
$$;
