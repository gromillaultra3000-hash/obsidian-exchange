CREATE TABLE dca_schedules(
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,currency TEXT NOT NULL,
 rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount>0),crypto_address TEXT NOT NULL,
 interval_days INTEGER NOT NULL CHECK(interval_days>0),next_run TIMESTAMPTZ NOT NULL,
 runs_total INTEGER NOT NULL DEFAULT 0 CHECK(runs_total>=0),status TEXT NOT NULL DEFAULT 'active'
 CHECK(status IN('active','cancelled')));
CREATE INDEX idx_dca_due ON dca_schedules(next_run,id) WHERE status='active';

CREATE TABLE limit_orders(
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,currency TEXT NOT NULL,
 target_rate NUMERIC(30,12) NOT NULL CHECK(target_rate>0),direction TEXT NOT NULL
 CHECK(direction IN('above','below')),rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount>0),
 crypto_address TEXT NOT NULL,payment_method TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active'
 CHECK(status IN('active','cancelled','expired','triggered')),expires_at TIMESTAMPTZ NOT NULL,
 triggered_at TIMESTAMPTZ,order_id BIGINT);
CREATE INDEX idx_limit_active ON limit_orders(expires_at,id) WHERE status='active';
