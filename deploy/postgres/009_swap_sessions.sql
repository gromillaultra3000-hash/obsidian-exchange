CREATE TABLE swap_sessions(
 id BIGSERIAL PRIMARY KEY,session_token TEXT NOT NULL UNIQUE,user_id BIGINT NOT NULL,
 coin_from TEXT NOT NULL,coin_to TEXT NOT NULL,amount_from NUMERIC(30,12) NOT NULL CHECK(amount_from>0),
 address_to TEXT NOT NULL,trocador_id TEXT,trocador_url TEXT,status TEXT NOT NULL DEFAULT 'created',
 web_user_id BIGINT,provider TEXT NOT NULL DEFAULT 'trocador',deposit_address TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_swap_external ON swap_sessions(trocador_id);
CREATE INDEX idx_swap_status ON swap_sessions(status,updated_at);
