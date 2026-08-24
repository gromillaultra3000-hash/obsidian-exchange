CREATE TABLE promo_codes(id BIGSERIAL PRIMARY KEY,code TEXT NOT NULL UNIQUE,
 discount_percent NUMERIC(8,4) NOT NULL CHECK(discount_percent>=0),max_uses INTEGER NOT NULL CHECK(max_uses>0),
 uses_count INTEGER NOT NULL DEFAULT 0 CHECK(uses_count>=0 AND uses_count<=max_uses),valid_until TIMESTAMPTZ NOT NULL,
 is_active BOOLEAN NOT NULL DEFAULT true,created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE promo_uses(code_id BIGINT NOT NULL REFERENCES promo_codes(id),user_id BIGINT NOT NULL,
 order_id BIGINT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(code_id,user_id));
CREATE TABLE sent_notifications(order_id BIGINT NOT NULL,event TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(order_id,event));
