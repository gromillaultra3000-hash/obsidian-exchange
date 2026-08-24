CREATE TABLE support_tickets(
 id BIGSERIAL PRIMARY KEY,web_user_id BIGINT NOT NULL DEFAULT 0,user_id BIGINT,
 username TEXT,subject TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open'
 CHECK(status IN('open','answered','closed')),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_support_web ON support_tickets(web_user_id,updated_at DESC);
CREATE INDEX idx_support_user ON support_tickets(user_id,updated_at DESC);
CREATE TABLE support_messages(
 id BIGSERIAL PRIMARY KEY,ticket_id BIGINT NOT NULL REFERENCES support_tickets(id),
 sender TEXT NOT NULL CHECK(sender IN('user','admin')),message TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_support_messages_ticket ON support_messages(ticket_id,id);
