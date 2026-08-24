-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal; never a production migration.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='obsidian_exchange_bot_owner') THEN
  CREATE ROLE obsidian_exchange_bot_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='obsidian_exchange_bot') THEN
  CREATE ROLE obsidian_exchange_bot LOGIN PASSWORD 'synthetic-rehearsal-only' CONNECTION LIMIT 10 NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
 END IF;
END $$;
ALTER ROLE obsidian_exchange_bot_owner NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE obsidian_exchange_bot LOGIN PASSWORD 'synthetic-rehearsal-only' CONNECTION LIMIT 10 NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE obsidian_exchange_bot SET statement_timeout='5s';
ALTER ROLE obsidian_exchange_bot SET lock_timeout='1s';
DO $$ BEGIN
 EXECUTE format('REVOKE CONNECT,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
 EXECUTE format('REVOKE ALL ON DATABASE %I FROM obsidian_exchange_bot',current_database());
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO obsidian_exchange_bot',current_database());
END $$;
REVOKE ALL ON SCHEMA public FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_owner;
GRANT USAGE ON SCHEMA public TO obsidian_exchange_bot,obsidian_exchange_bot_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_owner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_owner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_owner;

GRANT SELECT(user_id,reason,blocked_at) ON public.blocked_users TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,user_id,created_at,currency,rub_amount,status,crypto_address,paid_btc_tx,receipt_sent_at,updated_at,network) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,event) ON public.sent_notifications TO obsidian_exchange_bot_owner;
GRANT SELECT(currency,amount,updated_at) ON public.reserves TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b1_blocked_users(p_limit integer)
RETURNS TABLE(user_id bigint,reason text,blocked_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_limit'; END IF;
 RETURN QUERY SELECT b.user_id,b.reason,b.blocked_at FROM public.blocked_users b ORDER BY b.blocked_at DESC LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b1_customer_history(p_user_id bigint,p_limit integer)
RETURNS TABLE(order_id bigint,created_at timestamptz,currency text,rub_amount numeric,status text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_customer_history'; END IF;
 RETURN QUERY SELECT o.order_id,o.created_at,o.currency,o.rub_amount,o.status FROM public.orders o WHERE o.user_id=p_user_id ORDER BY o.order_id DESC LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b1_payout_candidates(p_hours integer,p_limit integer)
RETURNS TABLE(order_id bigint,user_id bigint,rub_amount numeric,currency text,network text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_hours<1 OR p_hours>168 OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_payout_candidates'; END IF;
 RETURN QUERY SELECT o.order_id,o.user_id,o.rub_amount,o.currency,o.network FROM public.orders o
  WHERE o.status='paid' AND COALESCE(o.updated_at,o.created_at)>=clock_timestamp()-(p_hours*interval '1 hour')
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s WHERE s.order_id=o.order_id AND s.event='payout_triggered')
  ORDER BY o.created_at LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b1_reserves_detailed()
RETURNS TABLE(currency text,amount numeric,updated_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT r.currency,r.amount,r.updated_at FROM public.reserves r ORDER BY r.currency LIMIT 100
$$;

ALTER FUNCTION public.bot_b1_blocked_users(integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b1_customer_history(bigint,integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b1_payout_candidates(integer,integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b1_reserves_detailed() OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b1_blocked_users(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.bot_b1_customer_history(bigint,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.bot_b1_payout_candidates(integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.bot_b1_reserves_detailed() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b1_blocked_users(integer) TO obsidian_exchange_bot;
GRANT EXECUTE ON FUNCTION public.bot_b1_customer_history(bigint,integer) TO obsidian_exchange_bot;
GRANT EXECUTE ON FUNCTION public.bot_b1_payout_candidates(integer,integer) TO obsidian_exchange_bot;
GRANT EXECUTE ON FUNCTION public.bot_b1_reserves_detailed() TO obsidian_exchange_bot;

DO $$ DECLARE unexpected bigint; BEGIN
 SELECT count(*) INTO unexpected FROM pg_auth_members m WHERE
  m.roleid IN(SELECT oid FROM pg_roles WHERE rolname IN('obsidian_exchange_bot','obsidian_exchange_bot_owner')) OR
  m.member IN(SELECT oid FROM pg_roles WHERE rolname IN('obsidian_exchange_bot','obsidian_exchange_bot_owner'));
 IF unexpected<>0 THEN RAISE EXCEPTION 'bot_role_membership_present'; END IF;
 IF has_database_privilege('obsidian_exchange_bot',current_database(),'TEMPORARY') OR has_schema_privilege('obsidian_exchange_bot','public','CREATE') THEN
  RAISE EXCEPTION 'bot_ambient_create_privilege';
 END IF;
END $$;
