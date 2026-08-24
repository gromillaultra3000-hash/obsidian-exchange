-- E0.3 PROPOSAL ONLY. Apply after 035-037 in disposable PostgreSQL 17 only.
GRANT SELECT(order_id,user_id,username,currency,rub_amount,crypto_address,status,created_at,paid_btc_tx,updated_at,web_user_id,rub_volume_counted,verification_requested,montera_invoice_id,receipt_deadline,receipt_sent_at,network,agreed_rate,agreed_crypto_amount,agreed_at) ON public.orders TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b2_agreed_quote(p_order_id bigint)
RETURNS TABLE(agreed_rate numeric,agreed_crypto_amount numeric)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_order_id<=0 THEN RAISE EXCEPTION 'invalid_order'; END IF;
 RETURN QUERY SELECT o.agreed_rate,o.agreed_crypto_amount FROM public.orders o WHERE o.order_id=p_order_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'order_not_found'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_order_snapshot(p_order_id bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r jsonb; BEGIN
 IF p_order_id<=0 THEN RAISE EXCEPTION 'invalid_order'; END IF;
 SELECT jsonb_build_object('order_id',o.order_id,'user_id',o.user_id,'username',o.username,'currency',o.currency,'rub_amount',o.rub_amount,'crypto_address',o.crypto_address,'status',o.status,'created_at',o.created_at,'paid_btc_tx',o.paid_btc_tx,'updated_at',o.updated_at,'web_user_id',o.web_user_id,'rub_volume_counted',o.rub_volume_counted,'verification_requested',o.verification_requested,'montera_invoice_id',o.montera_invoice_id,'receipt_deadline',o.receipt_deadline,'receipt_sent_at',o.receipt_sent_at,'network',o.network,'agreed_rate',o.agreed_rate,'agreed_crypto_amount',o.agreed_crypto_amount,'agreed_at',o.agreed_at) INTO r FROM public.orders o WHERE o.order_id=p_order_id;
 RETURN r;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_customer_history(p_user_id bigint,p_limit integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_history'; END IF;
 RETURN COALESCE((SELECT jsonb_agg(to_jsonb(q) ORDER BY q.order_id DESC) FROM (SELECT o.order_id,o.created_at,o.currency,o.rub_amount,o.status,o.crypto_address,o.paid_btc_tx,o.receipt_sent_at FROM public.orders o WHERE o.user_id=p_user_id ORDER BY o.order_id DESC LIMIT p_limit) q),'[]'::jsonb);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_latest_customer_order_id(p_user_id bigint) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN (SELECT o.order_id FROM public.orders o WHERE o.user_id=p_user_id ORDER BY o.created_at DESC,o.order_id DESC LIMIT 1);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_customer_aggregates(p_user_id bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r jsonb; BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 SELECT jsonb_build_object('total',count(*),'completed',count(*) FILTER(WHERE o.status='sent'),'volume',COALESCE(sum(o.rub_amount) FILTER(WHERE o.status='sent'),0),'first_at',min(o.created_at),'favorite_currency',(SELECT f.currency FROM public.orders f WHERE f.user_id=p_user_id AND f.status='sent' GROUP BY f.currency ORDER BY count(*) DESC,f.currency LIMIT 1)) INTO r FROM public.orders o WHERE o.user_id=p_user_id;
 RETURN r;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_provider_success_count(p_user_id bigint) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN (SELECT count(*) FROM public.orders o WHERE o.user_id=p_user_id AND o.status IN('paid','sent','completed'));
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_find_customer(p_query text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r jsonb; BEGIN
 p_query=trim(p_query); IF p_query='' OR length(p_query)>64 THEN RAISE EXCEPTION 'invalid_query'; END IF;
 IF p_query~'^[0-9]+$' THEN
  IF length(p_query)>19 OR p_query::numeric>9223372036854775807 THEN RAISE EXCEPTION 'invalid_query'; END IF;
  SELECT jsonb_build_object('user_id',min(o.user_id),'username',min(o.username),'total',count(*),'sent_cnt',count(*) FILTER(WHERE o.status='sent'),'volume',COALESCE(sum(o.rub_amount) FILTER(WHERE o.status='sent'),0)) INTO r FROM public.orders o WHERE o.user_id=p_query::bigint HAVING count(*)>0;
 ELSE
  SELECT jsonb_build_object('user_id',min(o.user_id),'username',min(o.username),'total',count(*),'sent_cnt',count(*) FILTER(WHERE o.status='sent'),'volume',COALESCE(sum(o.rub_amount) FILTER(WHERE o.status='sent'),0)) INTO r FROM public.orders o WHERE o.username=p_query HAVING count(*)>0;
 END IF; RETURN r;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_operator_dashboard(p_limit integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_limit'; END IF;
 RETURN jsonb_build_object('pending',COALESCE((SELECT jsonb_agg(to_jsonb(q) ORDER BY q.created_at DESC,q.order_id DESC) FROM (SELECT o.order_id,o.username,o.user_id,o.rub_amount,o.currency,o.created_at FROM public.orders o WHERE o.status='pending' ORDER BY o.created_at DESC,o.order_id DESC LIMIT p_limit) q),'[]'::jsonb),'paid_count',(SELECT count(*) FROM public.orders o WHERE o.status='paid'));
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_active_customer_ids(p_days integer,p_limit integer) RETURNS TABLE(user_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_days<1 OR p_days>365 OR p_limit<1 OR p_limit>1000 THEN RAISE EXCEPTION 'invalid_activity_window'; END IF;
 RETURN QUERY SELECT o.user_id FROM public.orders o WHERE o.user_id>0 AND o.created_at>=statement_timestamp()-(p_days*interval '1 day') GROUP BY o.user_id ORDER BY max(o.created_at) DESC,o.user_id LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_export_recent(p_limit integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_limit<1 OR p_limit>10000 THEN RAISE EXCEPTION 'invalid_export_limit'; END IF;
 RETURN COALESCE((SELECT jsonb_agg(to_jsonb(q) ORDER BY q.order_id) FROM (SELECT o.order_id,o.user_id,o.username,o.currency,o.rub_amount,o.crypto_address,o.status,o.created_at,o.paid_btc_tx,o.updated_at,o.web_user_id,o.rub_volume_counted,o.verification_requested,o.montera_invoice_id,o.receipt_deadline,o.receipt_sent_at,o.network,o.agreed_rate,o.agreed_crypto_amount,o.agreed_at FROM public.orders o ORDER BY o.order_id DESC LIMIT p_limit) q),'[]'::jsonb);
END $$;

ALTER FUNCTION public.bot_b2_agreed_quote(bigint) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_order_snapshot(bigint) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_customer_history(bigint,integer) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_latest_customer_order_id(bigint) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_customer_aggregates(bigint) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_provider_success_count(bigint) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_find_customer(text) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_operator_dashboard(integer) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_active_customer_ids(integer,integer) OWNER TO obsidian_exchange_bot_owner; ALTER FUNCTION public.bot_b2_export_recent(integer) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b2_agreed_quote(bigint),public.bot_b2_order_snapshot(bigint),public.bot_b2_customer_history(bigint,integer),public.bot_b2_latest_customer_order_id(bigint),public.bot_b2_customer_aggregates(bigint),public.bot_b2_provider_success_count(bigint),public.bot_b2_find_customer(text),public.bot_b2_operator_dashboard(integer),public.bot_b2_active_customer_ids(integer,integer),public.bot_b2_export_recent(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b2_agreed_quote(bigint),public.bot_b2_order_snapshot(bigint),public.bot_b2_customer_history(bigint,integer),public.bot_b2_latest_customer_order_id(bigint),public.bot_b2_customer_aggregates(bigint),public.bot_b2_provider_success_count(bigint),public.bot_b2_find_customer(text),public.bot_b2_operator_dashboard(integer),public.bot_b2_active_customer_ids(integer,integer),public.bot_b2_export_recent(integer) TO obsidian_exchange_bot;
