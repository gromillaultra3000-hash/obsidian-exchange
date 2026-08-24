CREATE TABLE bot_users(user_id BIGINT PRIMARY KEY,username TEXT,first_name TEXT,last_name TEXT,
 first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
 broadcast_enabled BOOLEAN NOT NULL DEFAULT true);
CREATE TABLE referrals(referrer_id BIGINT NOT NULL,referred_id BIGINT NOT NULL UNIQUE,
 bonus_paid BOOLEAN NOT NULL DEFAULT false,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 total_bonus_btc NUMERIC(30,12) NOT NULL DEFAULT 0,PRIMARY KEY(referrer_id,referred_id),
 CHECK(referrer_id<>referred_id));
CREATE INDEX idx_referrals_referrer ON referrals(referrer_id);
CREATE TABLE referral_addresses(user_id BIGINT PRIMARY KEY,currency TEXT NOT NULL,address TEXT NOT NULL);
