-- Atomic completion of a confirmed Vertu RUB payout.  The ledger makes VIP
-- credit immutable/idempotent; the outbox keeps customer delivery durable.
CREATE TABLE sell_settlement_ledger(
 sell_id BIGINT PRIMARY KEY,
 user_id BIGINT NOT NULL,
 rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount>0),
 payout_provider TEXT NOT NULL CHECK(payout_provider='vertu'),
 payout_ref TEXT NOT NULL CHECK(payout_ref<>''),
 payout_status TEXT NOT NULL CHECK(payout_status='paid'),
 settled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE sell_settlement_outbox(
 id BIGSERIAL PRIMARY KEY,
 sell_id BIGINT NOT NULL UNIQUE,
 recipient_id BIGINT NOT NULL,
 rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount>0),
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 claimed_at TIMESTAMPTZ,
 sent_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sell_settlement_outbox_pending
 ON sell_settlement_outbox(state,id) WHERE state='pending';
