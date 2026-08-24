CREATE TABLE order_receipts(order_id BIGINT PRIMARY KEY,path TEXT NOT NULL,filename TEXT NOT NULL,
 content_type TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 dispute_opened_at TIMESTAMPTZ,sha256 TEXT);
CREATE INDEX idx_receipt_sha ON order_receipts(sha256);
CREATE INDEX idx_receipt_dispute ON order_receipts(created_at,order_id) WHERE dispute_opened_at IS NULL;
