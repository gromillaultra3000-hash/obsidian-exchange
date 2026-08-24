CREATE TABLE system_flags(
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  details TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_created ON audit_log(created_at);
