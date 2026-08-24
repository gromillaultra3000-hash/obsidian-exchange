CREATE TABLE bot_notification_jobs(
 id BIGSERIAL PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo')),
 dedupe_key TEXT NOT NULL,payload JSONB NOT NULL,state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),claimed_at TIMESTAMPTZ,sent_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(kind,dedupe_key));
CREATE INDEX idx_bot_notification_jobs_pending ON bot_notification_jobs(state,attempts,id) WHERE state='pending';
