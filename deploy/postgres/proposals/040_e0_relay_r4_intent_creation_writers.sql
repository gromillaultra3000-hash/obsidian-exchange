-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- R4: bounded creation of immutable-initial-state order, sell and swap intents.

GRANT INSERT(user_id,username,currency,rub_amount,crypto_address,status,web_user_id,
 network,agreed_rate,agreed_crypto_amount,agreed_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(order_id) ON public.orders TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.orders_order_id_seq TO obsidian_relay_owner;
GRANT INSERT(user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,
 payout_method,payout_bank,payout_details,payout_name) ON public.sell_orders TO obsidian_relay_owner;
GRANT SELECT(id) ON public.sell_orders TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.sell_orders_id_seq TO obsidian_relay_owner;
GRANT INSERT(session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id,
 trocador_url,status,web_user_id,provider,deposit_address) ON public.swap_sessions TO obsidian_relay_owner;
GRANT SELECT(id) ON public.swap_sessions TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.swap_sessions_id_seq TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_order_create(p_user_id bigint,p_username text,
 p_currency text,p_rub_amount numeric,p_destination text,p_web_user_id bigint,p_network text,
 p_agreed_rate numeric,p_agreed_crypto_amount numeric)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_id bigint;
BEGIN
 IF p_user_id IS NULL OR p_user_id=0 OR p_currency IS NULL OR length(trim(p_currency))<1
  OR length(p_currency)>16 OR p_rub_amount IS NULL OR p_rub_amount<=0
  OR p_destination IS NULL OR length(trim(p_destination))<1 OR length(p_destination)>256
  OR (p_username IS NOT NULL AND length(p_username)>64)
  OR (p_network IS NOT NULL AND length(p_network)>32)
  OR p_agreed_rate IS NULL OR p_agreed_rate<=0
  OR p_agreed_crypto_amount IS NULL OR p_agreed_crypto_amount<=0
  OR (p_web_user_id IS NOT NULL AND p_web_user_id<=0) THEN RAISE EXCEPTION 'invalid_order_create';END IF;
 INSERT INTO public.orders(user_id,username,currency,rub_amount,crypto_address,status,
  web_user_id,network,agreed_rate,agreed_crypto_amount,agreed_at)
 VALUES(p_user_id,NULLIF(trim(COALESCE(p_username,'')),''),upper(trim(p_currency)),
  p_rub_amount,trim(p_destination),'pending',p_web_user_id,NULLIF(trim(COALESCE(p_network,'')),''),
  p_agreed_rate,p_agreed_crypto_amount,clock_timestamp()) RETURNING order_id INTO v_id;
 RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_create(p_user_id bigint,p_currency text,
 p_crypto_amount numeric,p_rub_amount numeric,p_sbp_phone text,p_receive_address text,
 p_payout_method text,p_payout_bank text,p_payout_details text,p_payout_name text)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_id bigint;
BEGIN
 IF p_user_id IS NULL OR p_user_id<=0 OR p_currency IS NULL OR length(trim(p_currency))<1
  OR length(p_currency)>16 OR p_crypto_amount IS NULL OR p_crypto_amount<=0
  OR p_rub_amount IS NULL OR p_rub_amount<=0 OR p_receive_address IS NULL
  OR length(trim(p_receive_address))<1 OR length(p_receive_address)>256
  OR length(COALESCE(p_sbp_phone,''))>32 OR length(COALESCE(p_payout_method,''))>32
  OR length(COALESCE(p_payout_bank,''))>120 OR length(COALESCE(p_payout_details,''))>500
  OR length(COALESCE(p_payout_name,''))>200 THEN RAISE EXCEPTION 'invalid_sell_create';END IF;
 INSERT INTO public.sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,
  receive_address,status,payout_method,payout_bank,payout_details,payout_name)
 VALUES(p_user_id,upper(trim(p_currency)),p_crypto_amount,p_rub_amount,
  COALESCE(p_sbp_phone,''),trim(p_receive_address),'pending',NULLIF(trim(COALESCE(p_payout_method,'')),''),
  NULLIF(trim(COALESCE(p_payout_bank,'')),''),NULLIF(trim(COALESCE(p_payout_details,'')),''),
  NULLIF(trim(COALESCE(p_payout_name,'')),'')) RETURNING id INTO v_id;
 RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION public.relay_swap_create(p_token text,p_user_id bigint,
 p_coin_from text,p_coin_to text,p_amount_from numeric,p_address_to text,p_external_id text,
 p_external_url text,p_status text,p_web_user_id bigint,p_provider text,p_deposit_address text)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_id bigint;
BEGIN
 IF p_token IS NULL OR length(trim(p_token))<16 OR length(p_token)>256 OR p_user_id IS NULL OR p_user_id=0
  OR p_coin_from IS NULL OR length(trim(p_coin_from))<1 OR length(p_coin_from)>16
  OR p_coin_to IS NULL OR length(trim(p_coin_to))<1 OR length(p_coin_to)>16
  OR upper(trim(p_coin_from))=upper(trim(p_coin_to)) OR p_amount_from IS NULL OR p_amount_from<=0
  OR p_address_to IS NULL OR length(trim(p_address_to))<1 OR length(p_address_to)>256
  OR p_external_id IS NULL OR length(trim(p_external_id))<1 OR length(p_external_id)>256
  OR p_external_url IS NULL OR length(p_external_url)>500
  OR p_status NOT IN('created','waiting') OR p_provider NOT IN('swapuz','trocador')
  OR p_deposit_address IS NULL OR length(trim(p_deposit_address))<1 OR length(p_deposit_address)>256
  OR (p_web_user_id IS NOT NULL AND p_web_user_id<=0) THEN RAISE EXCEPTION 'invalid_swap_create';END IF;
 INSERT INTO public.swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,
  trocador_id,trocador_url,status,web_user_id,provider,deposit_address)
 VALUES(trim(p_token),p_user_id,upper(trim(p_coin_from)),upper(trim(p_coin_to)),p_amount_from,
  trim(p_address_to),trim(p_external_id),p_external_url,p_status,p_web_user_id,p_provider,
  trim(p_deposit_address)) RETURNING id INTO v_id;
 RETURN v_id;
END $$;

ALTER FUNCTION public.relay_order_create(bigint,text,text,numeric,text,bigint,text,numeric,numeric) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_create(bigint,text,numeric,numeric,text,text,text,text,text,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_swap_create(text,bigint,text,text,numeric,text,text,text,text,bigint,text,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_order_create(bigint,text,text,numeric,text,bigint,text,numeric,numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_create(bigint,text,numeric,numeric,text,text,text,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_swap_create(text,bigint,text,text,numeric,text,text,text,text,bigint,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_order_create(bigint,text,text,numeric,text,bigint,text,numeric,numeric) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_create(bigint,text,numeric,numeric,text,text,text,text,text,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_swap_create(text,bigint,text,text,numeric,text,text,text,text,bigint,text,text) TO obsidian_relay;
