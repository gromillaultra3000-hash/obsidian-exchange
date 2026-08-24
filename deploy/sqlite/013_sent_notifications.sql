CREATE TABLE sent_notifications(
  order_id INTEGER NOT NULL,
  event TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(order_id,event)
);
