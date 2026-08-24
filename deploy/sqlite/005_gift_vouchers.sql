CREATE TABLE gift_vouchers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sender_id INTEGER NOT NULL,
  currency TEXT NOT NULL,
  rub_amount REAL NOT NULL,
  code TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  order_id INTEGER,
  recipient_id INTEGER,
  recipient_address TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  claimed_at TEXT
);
