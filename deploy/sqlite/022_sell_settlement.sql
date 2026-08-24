CREATE TABLE sell_settlement_ledger(
  sell_id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  rub_amount REAL NOT NULL CHECK(rub_amount>0),
  payout_provider TEXT NOT NULL CHECK(payout_provider='vertu'),
  payout_ref TEXT NOT NULL CHECK(payout_ref<>''),
  payout_status TEXT NOT NULL CHECK(payout_status='paid'),
  settled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE sell_settlement_outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sell_id INTEGER NOT NULL UNIQUE,
  recipient_id INTEGER NOT NULL,
  rub_amount REAL NOT NULL CHECK(rub_amount>0),
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  sent_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sell_settlement_outbox_pending
  ON sell_settlement_outbox(state,id) WHERE state='pending';
