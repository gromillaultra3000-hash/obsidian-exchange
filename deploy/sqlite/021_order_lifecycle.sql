CREATE TABLE order_lifecycle_work(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  order_id INTEGER NOT NULL,
  session_token TEXT,
  provider TEXT,
  provider_invoice_id TEXT,
  user_id INTEGER,
  currency TEXT,
  rub_amount REAL,
  order_status TEXT,
  has_receipt INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind,order_id,session_token),
  CHECK(kind IN('order_expired_notify','session_dead_admin','session_dead_customer','provider_cancel')),
  CHECK(state IN('pending','sending','done')),
  CHECK(attempts>=0)
);
CREATE INDEX idx_order_lifecycle_work_pending
  ON order_lifecycle_work(state,id) WHERE state='pending';
