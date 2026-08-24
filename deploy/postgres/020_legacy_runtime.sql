-- Remaining live/read-compatible tables discovered by the full inventory.
-- Names and column order mirror production SQLite for snapshot reconciliation.
CREATE TABLE admin_log(
 id BIGSERIAL PRIMARY KEY,admin_id BIGINT NOT NULL,action TEXT NOT NULL,
 target_id BIGINT,details TEXT,created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE client_address_notes(
 user_id BIGINT NOT NULL,currency TEXT NOT NULL,network TEXT NOT NULL DEFAULT '',
 address TEXT NOT NULL,label TEXT NOT NULL DEFAULT '',hidden BOOLEAN NOT NULL DEFAULT false,
 updated_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(user_id,currency,network,address));

CREATE TABLE payout_queue(
 id BIGSERIAL PRIMARY KEY,order_id BIGINT NOT NULL,btc_address TEXT NOT NULL,
 btc_amount NUMERIC(30,12) NOT NULL,status TEXT DEFAULT 'new',txid TEXT,
 created_at TIMESTAMPTZ DEFAULT now(),crypto_address TEXT,amount NUMERIC(30,12),
 currency TEXT DEFAULT 'BTC');

CREATE TABLE payout_shadow(
 order_id BIGINT PRIMARY KEY,decided_at TIMESTAMPTZ DEFAULT now(),verdict TEXT,
 detail TEXT,provider TEXT,circuit_action TEXT,would_auto_pay BOOLEAN,
 rub_amount NUMERIC(20,2),currency TEXT,outcome TEXT,outcome_at TIMESTAMPTZ);

CREATE TABLE rate_subscriptions(
 user_id BIGINT PRIMARY KEY,enabled BOOLEAN DEFAULT true,last_notified DOUBLE PRECISION DEFAULT 0,
 last_btc NUMERIC(30,12) DEFAULT 0,last_ltc NUMERIC(30,12) DEFAULT 0,
 last_usdt NUMERIC(30,12) DEFAULT 0);

CREATE TABLE referral_bonuses(
 id BIGSERIAL PRIMARY KEY,referrer_id BIGINT NOT NULL,referred_id BIGINT NOT NULL,
 order_id BIGINT,bonus_amount NUMERIC(30,12) NOT NULL DEFAULT 0,
 currency TEXT DEFAULT 'RUB',created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE reviews(
 id BIGSERIAL PRIMARY KEY,order_id BIGINT NOT NULL,user_id BIGINT NOT NULL,
 rating INTEGER,comment TEXT,status TEXT NOT NULL DEFAULT 'pending',
 created_at TIMESTAMPTZ DEFAULT now());
CREATE UNIQUE INDEX idx_reviews_order ON reviews(order_id);

CREATE TABLE risk_events(
 id BIGSERIAL PRIMARY KEY,client_ip TEXT,user_agent TEXT,telegram_id BIGINT,
 event_type TEXT,created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE user_vip_volume(
 user_id BIGINT PRIMARY KEY,total_rub NUMERIC(20,2) DEFAULT 0,
 updated_at TIMESTAMPTZ DEFAULT now());

-- Empty compatibility table, superseded by workers. Retain through cutover so
-- an overlooked read fails neither silently nor destructively; retire later.
CREATE TABLE worker_ids(
 user_id BIGINT PRIMARY KEY,added_at TIMESTAMPTZ DEFAULT now());

CREATE INDEX idx_admin_log_created ON admin_log(created_at);
CREATE INDEX idx_payout_queue_status ON payout_queue(status,created_at);
CREATE INDEX idx_payout_shadow_decided ON payout_shadow(decided_at);
CREATE INDEX idx_rate_subscriptions_enabled ON rate_subscriptions(enabled) WHERE enabled=true;
CREATE INDEX idx_referral_bonuses_referrer ON referral_bonuses(referrer_id,created_at);
CREATE INDEX idx_risk_events_created ON risk_events(created_at);
