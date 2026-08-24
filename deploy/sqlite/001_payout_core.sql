CREATE TABLE payout_intents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','processing','succeeded','review')),
  source TEXT NOT NULL,
  requested_by TEXT,
  rub_amount REAL NOT NULL,
  crypto_amount REAL NOT NULL,
  currency TEXT NOT NULL,
  network TEXT,
  destination TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  txid TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_payout_intents_state ON payout_intents(state,created_at);
CREATE TABLE payout_intent_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  evidence TEXT NOT NULL,
  txid TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE referral_payout_intents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','processing','succeeded','review','reconciled')),
  crypto_amount REAL NOT NULL CHECK(crypto_amount>0),
  currency TEXT NOT NULL DEFAULT 'BTC',
  network TEXT,
  destination TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  txid TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_referral_payout_active ON referral_payout_intents(user_id)
  WHERE state IN('pending','processing','succeeded','review');
CREATE INDEX idx_referral_payout_state ON referral_payout_intents(state,created_at);
CREATE TABLE referral_payout_intent_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_id INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  evidence TEXT NOT NULL,
  txid TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
