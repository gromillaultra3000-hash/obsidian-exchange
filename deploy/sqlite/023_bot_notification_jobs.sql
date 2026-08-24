CREATE TABLE bot_notification_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  payload TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  sent_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind,dedupe_key),
  CHECK(kind IN('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo')),
  CHECK(state IN('pending','sending','sent')),
  CHECK(attempts>=0)
);
CREATE INDEX idx_bot_notification_jobs_pending
  ON bot_notification_jobs(state,attempts,id) WHERE state='pending';
