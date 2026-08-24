CREATE TABLE wallet_links(user_id BIGINT NOT NULL,chain TEXT NOT NULL,address TEXT NOT NULL,
 verified_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(user_id,chain));
CREATE TABLE wallet_send_intents(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,chain TEXT NOT NULL,
 sell_id BIGINT NOT NULL,from_address TEXT NOT NULL,to_address TEXT NOT NULL,
 amount NUMERIC(30,12) NOT NULL CHECK(amount>0),marker TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,
 signed_at TIMESTAMPTZ);
CREATE INDEX idx_wallet_send_sell ON wallet_send_intents(sell_id,id);
