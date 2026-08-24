-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- Five P3 bodies replacing order_id-only Relay reads with owner/token correlation.

GRANT SELECT(order_id,user_id,username,currency,rub_amount,crypto_address,status,created_at,
 paid_btc_tx,updated_at,web_user_id,rub_volume_counted,verification_requested,
 montera_invoice_id,receipt_deadline,receipt_sent_at,network,agreed_rate,
 agreed_crypto_amount,agreed_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,session_token,order_id,amount,status,provider,provider_invoice_id,
 provider_payload,qr_payload,created_at,expires_at)
 ON public.payment_sessions TO obsidian_relay_owner;
GRANT SELECT(order_id) ON public.order_receipts TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_order_authorized_snapshot(
 p_order_id bigint,p_user_id bigint,p_session_token text)
RETURNS TABLE(order_id bigint,user_id bigint,username text,currency text,
 rub_amount numeric(20,2),crypto_address text,status text,created_at timestamptz,
 paid_btc_tx text,updated_at timestamptz,web_user_id bigint,rub_volume_counted boolean,
 verification_requested text,montera_invoice_id text,receipt_deadline timestamptz,
 receipt_sent_at timestamptz,network text,agreed_rate numeric(30,12),
 agreed_crypto_amount numeric(30,12),agreed_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR (p_user_id IS NULL AND p_session_token IS NULL)
    OR (p_user_id IS NOT NULL AND p_user_id<=0)
    OR (p_session_token IS NOT NULL AND
        (length(trim(p_session_token))<1 OR length(p_session_token)>256)) THEN
  RAISE EXCEPTION 'invalid_order_authority'; END IF;
 RETURN QUERY SELECT o.order_id,o.user_id,o.username,o.currency,o.rub_amount,
  o.crypto_address,o.status,o.created_at,o.paid_btc_tx,o.updated_at,o.web_user_id,
  o.rub_volume_counted,o.verification_requested,o.montera_invoice_id,
  o.receipt_deadline,o.receipt_sent_at,o.network,o.agreed_rate,
  o.agreed_crypto_amount,o.agreed_at FROM public.orders o WHERE o.order_id=p_order_id
  AND (o.user_id=p_user_id OR EXISTS(SELECT 1 FROM public.payment_sessions proof
   WHERE proof.order_id=o.order_id AND proof.session_token=p_session_token)) LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_session_get_by_token(p_session_token text)
RETURNS TABLE(amount numeric(20,2),order_id bigint,status text,provider_payload text,
 qr_payload text,expires_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_session_token IS NULL OR length(trim(p_session_token))<1
    OR length(p_session_token)>256 THEN RAISE EXCEPTION 'invalid_session_token'; END IF;
 RETURN QUERY SELECT ps.amount,ps.order_id,ps.status,ps.provider_payload,ps.qr_payload,
  ps.expires_at FROM public.payment_sessions ps
  WHERE ps.session_token=p_session_token LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_session_latest_for_authorized_order(
 p_order_id bigint,p_user_id bigint,p_session_token text)
RETURNS TABLE(session_token text,status text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR (p_user_id IS NULL AND p_session_token IS NULL)
    OR (p_user_id IS NOT NULL AND p_user_id<=0)
    OR (p_session_token IS NOT NULL AND
        (length(trim(p_session_token))<1 OR length(p_session_token)>256)) THEN
  RAISE EXCEPTION 'invalid_order_authority'; END IF;
 RETURN QUERY SELECT ps.session_token,ps.status FROM public.payment_sessions ps
  JOIN public.orders o ON o.order_id=ps.order_id WHERE ps.order_id=p_order_id
  AND (o.user_id=p_user_id OR EXISTS(SELECT 1 FROM public.payment_sessions proof
   WHERE proof.order_id=o.order_id AND proof.session_token=p_session_token))
  ORDER BY ps.id DESC LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_session_latest_active_for_authorized_order(
 p_order_id bigint,p_user_id bigint,p_session_token text)
RETURNS TABLE(session_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR (p_user_id IS NULL AND p_session_token IS NULL)
    OR (p_user_id IS NOT NULL AND p_user_id<=0)
    OR (p_session_token IS NOT NULL AND
        (length(trim(p_session_token))<1 OR length(p_session_token)>256)) THEN
  RAISE EXCEPTION 'invalid_order_authority'; END IF;
 RETURN QUERY SELECT ps.session_token FROM public.payment_sessions ps
  JOIN public.orders o ON o.order_id=ps.order_id WHERE ps.order_id=p_order_id
  AND ps.session_token IS NOT NULL AND ps.status NOT IN('failed','expired')
  AND (o.user_id=p_user_id OR EXISTS(SELECT 1 FROM public.payment_sessions proof
   WHERE proof.order_id=o.order_id AND proof.session_token=p_session_token))
  ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_session_latest_provider_invoice_for_authorized_order(
 p_order_id bigint,p_provider text,p_prefix boolean,p_user_id bigint,p_session_token text)
RETURNS TABLE(provider_invoice_id text,provider text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR p_provider IS NULL
    OR p_provider NOT IN ('brabus','vertu') OR p_prefix IS NULL
    OR (p_prefix AND p_provider<>'brabus')
    OR (p_user_id IS NULL AND p_session_token IS NULL)
    OR (p_user_id IS NOT NULL AND p_user_id<=0)
    OR (p_session_token IS NOT NULL AND
        (length(trim(p_session_token))<1 OR length(p_session_token)>256)) THEN
  RAISE EXCEPTION 'invalid_provider_invoice_authority'; END IF;
 RETURN QUERY SELECT ps.provider_invoice_id,ps.provider FROM public.payment_sessions ps
  JOIN public.orders o ON o.order_id=ps.order_id WHERE ps.order_id=p_order_id
  AND ((NOT p_prefix AND ps.provider=p_provider)
       OR (p_prefix AND ps.provider LIKE (p_provider || ':%')))
  AND ps.provider_invoice_id IS NOT NULL
  AND (o.user_id=p_user_id OR EXISTS(SELECT 1 FROM public.payment_sessions proof
   WHERE proof.order_id=o.order_id AND proof.session_token=p_session_token))
  ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_receipt_authorized_state(
 p_order_id bigint,p_user_id bigint,p_session_token text)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_sent timestamptz;
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR (p_user_id IS NULL AND p_session_token IS NULL)
    OR (p_user_id IS NOT NULL AND p_user_id<=0)
    OR (p_session_token IS NOT NULL AND
        (length(trim(p_session_token))<1 OR length(p_session_token)>256)) THEN
  RAISE EXCEPTION 'invalid_order_authority'; END IF;
 SELECT o.receipt_sent_at INTO v_sent FROM public.order_receipts r
  JOIN public.orders o ON o.order_id=r.order_id WHERE r.order_id=p_order_id
  AND (o.user_id=p_user_id OR EXISTS(SELECT 1 FROM public.payment_sessions proof
   WHERE proof.order_id=o.order_id AND proof.session_token=p_session_token)) LIMIT 1;
 IF NOT FOUND THEN RETURN ''; END IF;
 RETURN CASE WHEN v_sent IS NULL THEN 'stored' ELSE 'sent' END;
END $$;

ALTER FUNCTION public.relay_order_authorized_snapshot(bigint,bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_session_get_by_token(text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_session_latest_for_authorized_order(bigint,bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_session_latest_active_for_authorized_order(bigint,bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_session_latest_provider_invoice_for_authorized_order(bigint,text,boolean,bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_receipt_authorized_state(bigint,bigint,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_order_authorized_snapshot(bigint,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_session_get_by_token(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_session_latest_for_authorized_order(bigint,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_session_latest_active_for_authorized_order(bigint,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_session_latest_provider_invoice_for_authorized_order(bigint,text,boolean,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_receipt_authorized_state(bigint,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_order_authorized_snapshot(bigint,bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_session_get_by_token(text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_session_latest_for_authorized_order(bigint,bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_session_latest_active_for_authorized_order(bigint,bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_session_latest_provider_invoice_for_authorized_order(bigint,text,boolean,bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_receipt_authorized_state(bigint,bigint,text) TO obsidian_relay;
