CREATE TABLE sell_orders(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,currency TEXT NOT NULL,
 crypto_amount NUMERIC(30,12) NOT NULL CHECK(crypto_amount>0),rub_amount NUMERIC(20,2) NOT NULL CHECK(rub_amount>0),
 sbp_phone TEXT NOT NULL DEFAULT '',receive_address TEXT NOT NULL,tx_hash TEXT,status TEXT NOT NULL DEFAULT 'pending'
 CHECK(status IN('pending','paying','paid','rejected','cancelled')),payout_method TEXT,payout_bank TEXT,
 payout_details TEXT,payout_name TEXT,payout_provider TEXT,payout_ref TEXT,payout_status TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_sell_status ON sell_orders(status,updated_at);
CREATE UNIQUE INDEX idx_sell_payout_ref ON sell_orders(payout_provider,payout_ref) WHERE payout_ref IS NOT NULL AND payout_ref<>'';
