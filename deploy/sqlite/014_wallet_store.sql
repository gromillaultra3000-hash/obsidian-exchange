CREATE TABLE wallet_links(
  user_id INTEGER NOT NULL,
  chain TEXT NOT NULL,
  address TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  PRIMARY KEY(user_id,chain)
);
CREATE TABLE wallet_send_intents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  chain TEXT NOT NULL,
  sell_id INTEGER NOT NULL,
  from_address TEXT NOT NULL,
  to_address TEXT NOT NULL,
  amount REAL NOT NULL CHECK(amount>0),
  marker TEXT NOT NULL,
  created_at TEXT NOT NULL,
  signed_at TEXT
);
CREATE INDEX idx_wallet_send_sell ON wallet_send_intents(sell_id,id);
