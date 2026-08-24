CREATE TABLE system_flags(key TEXT PRIMARY KEY,value TEXT,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE audit_log(id BIGSERIAL PRIMARY KEY,event TEXT NOT NULL,details TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_audit_created ON audit_log(created_at);
