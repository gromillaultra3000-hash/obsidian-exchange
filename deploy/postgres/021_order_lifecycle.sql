-- Durable consequences of order/session lifecycle transitions.  A claimed job
-- remains in `sending` after an uncertain external call and requires review or
-- an explicit known-safe retry; it is never rediscovered through a time window.
CREATE TABLE order_lifecycle_work(
 id BIGSERIAL PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN('order_expired_notify','session_dead_admin',
                                  'session_dead_customer','provider_cancel')),
 order_id BIGINT NOT NULL,
 session_token TEXT,
 provider TEXT,
 provider_invoice_id TEXT,
 user_id BIGINT,
 currency TEXT,
 rub_amount NUMERIC(20,2),
 order_status TEXT,
 has_receipt BOOLEAN NOT NULL DEFAULT false,
 detail TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','done')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 claimed_at TIMESTAMPTZ,
 completed_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(kind,order_id,session_token)
);
CREATE INDEX idx_order_lifecycle_work_pending
 ON order_lifecycle_work(state,id) WHERE state='pending';
