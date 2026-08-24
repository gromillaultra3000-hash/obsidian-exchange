-- Canonical buy-order ledger. Mirrors the live SQLite orders table without
-- adding foreign keys or a status CHECK during the compatibility migration.
-- Referential constraints and a formal transition enum come after snapshot
-- reconciliation, when legacy rows have been classified.
CREATE TABLE orders(
 order_id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL,
 username TEXT,
 currency TEXT NOT NULL DEFAULT 'BTC',
 rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount > 0),
 crypto_address TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 paid_btc_tx TEXT,
 updated_at TIMESTAMPTZ,
 web_user_id BIGINT,
 rub_volume_counted BOOLEAN NOT NULL DEFAULT false,
 verification_requested TEXT,
 montera_invoice_id TEXT,
 receipt_deadline TIMESTAMPTZ,
 receipt_sent_at TIMESTAMPTZ,
 network TEXT,
 agreed_rate NUMERIC(30,12),
 agreed_crypto_amount NUMERIC(30,12),
 agreed_at TIMESTAMPTZ
);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created ON orders(created_at);
CREATE INDEX idx_orders_recent_duplicate
 ON orders(user_id,currency,rub_amount,crypto_address,created_at DESC)
 WHERE status='pending';
