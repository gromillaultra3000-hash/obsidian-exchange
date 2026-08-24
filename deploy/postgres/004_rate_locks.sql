CREATE TABLE rate_locks(
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,currency TEXT NOT NULL,
 locked_rate NUMERIC(30,12) NOT NULL,fee_rub NUMERIC(20,2) NOT NULL DEFAULT 0,
 locked_until TIMESTAMPTZ NOT NULL,used BOOLEAN NOT NULL DEFAULT false,
 order_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_rate_locks_active ON rate_locks(user_id,currency,locked_until) WHERE used=false;
