CREATE TABLE client_address_notes(
  user_id INTEGER NOT NULL,
  currency TEXT NOT NULL,
  network TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  hidden INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(user_id,currency,network,address)
);
CREATE TABLE payout_shadow(
  order_id INTEGER PRIMARY KEY,
  decided_at TEXT DEFAULT CURRENT_TIMESTAMP,
  verdict TEXT,
  detail TEXT,
  provider TEXT,
  circuit_action TEXT,
  would_auto_pay INTEGER,
  rub_amount REAL,
  currency TEXT,
  outcome TEXT,
  outcome_at TEXT
);
CREATE INDEX idx_payout_shadow_decided ON payout_shadow(decided_at);
