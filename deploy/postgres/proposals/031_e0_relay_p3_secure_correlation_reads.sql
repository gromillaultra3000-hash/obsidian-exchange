-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- Three P3 bodies whose authorization/correlation is enforceable in SQL.

GRANT SELECT(order_id,user_id,currency,rub_amount,crypto_address,network,status,created_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,session_token,order_id,status,created_at) ON public.payment_sessions TO obsidian_relay_owner;
GRANT SELECT(session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id,trocador_url,status,provider,deposit_address) ON public.swap_sessions TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_order_recent_duplicate(
 p_user_id bigint,p_currency text,p_rub_amount numeric,p_destination text,
 p_network text,p_default_network text,p_seconds smallint)
RETURNS TABLE(order_id bigint,session_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id IS NULL OR p_user_id<=0
    OR p_currency IS NULL OR p_currency NOT IN ('BTC','LTC','USDT','ETH','XRP','TON','XMR')
    OR p_rub_amount IS NULL OR p_rub_amount<=0
    OR p_destination IS NULL OR length(trim(p_destination))<1 OR length(p_destination)>256
    OR p_network IS NULL OR p_network NOT IN ('MAINNET','TRC20','ERC20','XRPL','TON','MONERO')
    OR p_default_network IS NULL OR p_default_network NOT IN ('MAINNET','TRC20','ERC20','XRPL','TON','MONERO')
    OR p_seconds IS NULL OR p_seconds<1 OR p_seconds>300 THEN RAISE EXCEPTION 'invalid_recent_duplicate_query'; END IF;
 RETURN QUERY SELECT o.order_id,(SELECT ps.session_token FROM public.payment_sessions ps
   WHERE ps.order_id=o.order_id AND ps.status NOT IN ('failed','expired')
   ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1)
 FROM public.orders o WHERE o.user_id=p_user_id AND o.currency=p_currency
   AND o.rub_amount=p_rub_amount AND o.crypto_address=p_destination
   AND COALESCE(o.network,p_default_network)=p_network AND o.status='pending'
   AND o.created_at>transaction_timestamp()-(p_seconds*interval '1 second')
 ORDER BY o.created_at DESC,o.order_id DESC LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_session_token_matches_order(
 p_order_id bigint,p_session_token text)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR p_session_token IS NULL
    OR length(trim(p_session_token))<1 OR length(p_session_token)>256 THEN
  RAISE EXCEPTION 'invalid_payment_session_correlation'; END IF;
 RETURN EXISTS(SELECT 1 FROM public.payment_sessions ps
  WHERE ps.order_id=p_order_id AND ps.session_token=p_session_token);
END $$;

CREATE OR REPLACE FUNCTION public.relay_swap_get_by_token(p_session_token text)
RETURNS TABLE(session_token text,user_id bigint,coin_from text,coin_to text,
 amount_from numeric(30,12),address_to text,external_id text,external_url text,
 status text,provider text,deposit_address text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_session_token IS NULL OR length(trim(p_session_token))<1 OR length(p_session_token)>256 THEN
  RAISE EXCEPTION 'invalid_swap_token'; END IF;
 RETURN QUERY SELECT s.session_token,s.user_id,s.coin_from,s.coin_to,
  s.amount_from::numeric(30,12),s.address_to,s.trocador_id,s.trocador_url,
  s.status,s.provider,s.deposit_address FROM public.swap_sessions s
  WHERE s.session_token=p_session_token LIMIT 1;
END $$;

ALTER FUNCTION public.relay_order_recent_duplicate(bigint,text,numeric,text,text,text,smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_session_token_matches_order(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_swap_get_by_token(text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_order_recent_duplicate(bigint,text,numeric,text,text,text,smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_session_token_matches_order(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_swap_get_by_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_order_recent_duplicate(bigint,text,numeric,text,text,text,smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_session_token_matches_order(bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_swap_get_by_token(text) TO obsidian_relay;
