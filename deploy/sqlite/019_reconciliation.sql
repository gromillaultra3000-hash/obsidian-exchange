CREATE TABLE payout_reconciliations(
  order_id INTEGER PRIMARY KEY,
  intent_id INTEGER NOT NULL UNIQUE,
  txid TEXT NOT NULL,
  referral_btc REAL NOT NULL DEFAULT 0,
  vip_rub REAL NOT NULL,
  reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE notification_outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  recipient_id INTEGER NOT NULL,
  payload TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  sent_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(topic,aggregate_id)
);
CREATE INDEX idx_notification_outbox_state
  ON notification_outbox(state,created_at);
