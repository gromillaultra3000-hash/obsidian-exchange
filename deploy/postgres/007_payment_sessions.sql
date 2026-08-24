CREATE TABLE payment_sessions(
 id BIGSERIAL PRIMARY KEY,session_token TEXT NOT NULL UNIQUE,order_id BIGINT NOT NULL,
 amount NUMERIC(20,2) NOT NULL CHECK(amount>0),provider TEXT NOT NULL,status TEXT NOT NULL
 CHECK(status IN('created','invoice_created','awaiting_payment','payment_detected','confirming',
 'payout_queued','payout_sent','completed','paid','expired','failed')),
 provider_invoice_id TEXT,qr_payload TEXT,provider_payload TEXT,client_ip TEXT,user_agent TEXT,
 telegram_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),expires_at TIMESTAMPTZ);
CREATE INDEX idx_payment_sessions_order ON payment_sessions(order_id,id DESC);
CREATE INDEX idx_payment_sessions_active ON payment_sessions(expires_at,id)
 WHERE status IN('invoice_created','awaiting_payment');
