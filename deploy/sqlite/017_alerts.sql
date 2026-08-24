CREATE TABLE alert_throttle(
  key TEXT PRIMARY KEY,
  last_sent TEXT NOT NULL
);

CREATE TABLE alert_watermark(
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
