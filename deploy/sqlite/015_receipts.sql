CREATE TABLE order_receipts(
  order_id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  dispute_opened_at TEXT,
  sha256 TEXT
);
CREATE INDEX idx_receipt_sha ON order_receipts(sha256);
CREATE INDEX idx_receipt_dispute ON order_receipts(created_at,order_id)
  WHERE dispute_opened_at IS NULL;
