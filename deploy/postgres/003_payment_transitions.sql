CREATE TABLE payment_transition_audit(
 id BIGSERIAL PRIMARY KEY,order_id BIGINT NOT NULL,provider TEXT NOT NULL,
 action TEXT NOT NULL,from_status TEXT,to_status TEXT,evidence TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_payment_transition_order ON payment_transition_audit(order_id,created_at);
CREATE TABLE payment_notification_outbox(
 id BIGSERIAL PRIMARY KEY,order_id BIGINT NOT NULL UNIQUE,recipient_id BIGINT NOT NULL,
 payload JSONB NOT NULL,state TEXT NOT NULL DEFAULT 'pending'
 CHECK(state IN('pending','sending','sent')),attempts INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),claimed_at TIMESTAMPTZ,sent_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_payment_notification_state ON payment_notification_outbox(state,created_at);
