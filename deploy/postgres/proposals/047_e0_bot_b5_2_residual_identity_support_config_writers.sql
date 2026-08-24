-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal after role envelope.
GRANT SELECT(referred_id),INSERT(referrer_id,referred_id) ON public.referrals TO obsidian_exchange_bot_owner;
GRANT SELECT(user_id,username,first_name,last_name,last_seen),INSERT(user_id,username,first_name,last_name,last_seen),UPDATE(username,first_name,last_name,last_seen) ON public.bot_users TO obsidian_exchange_bot_owner;
GRANT SELECT(id,code),INSERT(code,discount_percent,max_uses,valid_until) ON public.promo_codes TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.promo_codes_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(provider),UPDATE(failed_count,is_healthy,status,blocker) ON public.provider_health TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,subject),UPDATE(status,updated_at) ON public.support_tickets TO obsidian_exchange_bot_owner;
GRANT SELECT(ticket_id),INSERT(ticket_id,sender,message) ON public.support_messages TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.support_messages_id_seq TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b5_create_promo(a_code text,a_discount numeric,a_max_uses integer,a_valid_until timestamptz) RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE promo_id bigint;
BEGIN
 a_code=upper(trim(a_code));
 IF a_code IS NULL OR length(a_code)<1 OR length(a_code)>32 OR a_code !~ '^[A-Z0-9_-]+$' OR a_discount IS NULL OR a_discount::text IN('NaN','Infinity','-Infinity') OR a_discount<0 OR a_discount>100 OR a_max_uses IS NULL OR a_max_uses<1 OR a_max_uses>1000000 OR a_valid_until IS NULL OR a_valid_until<=clock_timestamp() OR a_valid_until>clock_timestamp()+interval '2 years' THEN RAISE EXCEPTION 'invalid_promo'; END IF;
 INSERT INTO public.promo_codes(code,discount_percent,max_uses,valid_until) VALUES(a_code,a_discount,a_max_uses,a_valid_until) RETURNING id INTO promo_id;
 RETURN promo_id;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_reset_provider(a_provider text) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 a_provider=trim(a_provider);
 IF a_provider IS NULL OR length(a_provider)<1 OR length(a_provider)>100 THEN RAISE EXCEPTION 'invalid_provider'; END IF;
 UPDATE public.provider_health SET failed_count=0,is_healthy=true,status='READY',blocker='' WHERE provider=a_provider;
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_admin_reply(a_ticket_id bigint,a_message text) RETURNS TABLE(user_id bigint,subject text) LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_ticket_id IS NULL OR a_ticket_id<=0 OR a_message IS NULL OR length(trim(a_message))<1 OR length(a_message)>4000 THEN RAISE EXCEPTION 'invalid_admin_reply'; END IF;
 RETURN QUERY WITH locked AS (SELECT t.id,t.user_id,t.subject FROM public.support_tickets t WHERE t.id=a_ticket_id FOR UPDATE),
 inserted AS (INSERT INTO public.support_messages(ticket_id,sender,message) SELECT id,'admin',a_message FROM locked RETURNING ticket_id),
 updated AS (UPDATE public.support_tickets t SET status='answered',updated_at=clock_timestamp() FROM inserted i WHERE t.id=i.ticket_id RETURNING t.user_id,t.subject)
 SELECT u.user_id,u.subject FROM updated u;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_claim_referrer(a_referred_id bigint,a_referrer_id bigint) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_referred_id IS NULL OR a_referred_id<=0 OR a_referrer_id IS NULL OR a_referrer_id<=0 OR a_referred_id=a_referrer_id THEN RAISE EXCEPTION 'invalid_referrer_claim'; END IF;
 INSERT INTO public.referrals(referrer_id,referred_id) VALUES(a_referrer_id,a_referred_id) ON CONFLICT(referred_id) DO NOTHING;
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_upsert_user(a_user_id bigint,a_username text,a_first_name text,a_last_name text) RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_user_id IS NULL OR a_user_id<=0 OR (a_username IS NOT NULL AND length(a_username)>64) OR (a_first_name IS NOT NULL AND length(a_first_name)>128) OR (a_last_name IS NOT NULL AND length(a_last_name)>128) THEN RAISE EXCEPTION 'invalid_bot_user'; END IF;
 INSERT INTO public.bot_users(user_id,username,first_name,last_name,last_seen) VALUES(a_user_id,a_username,a_first_name,a_last_name,clock_timestamp()) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,last_seen=excluded.last_seen;
END $$;

ALTER FUNCTION public.bot_b5_create_promo(text,numeric,integer,timestamptz) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b5_reset_provider(text) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b5_admin_reply(bigint,text) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b5_claim_referrer(bigint,bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b5_upsert_user(bigint,text,text,text) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b5_create_promo(text,numeric,integer,timestamptz),public.bot_b5_reset_provider(text),public.bot_b5_admin_reply(bigint,text),public.bot_b5_claim_referrer(bigint,bigint),public.bot_b5_upsert_user(bigint,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b5_create_promo(text,numeric,integer,timestamptz),public.bot_b5_reset_provider(text),public.bot_b5_admin_reply(bigint,text),public.bot_b5_claim_referrer(bigint,bigint),public.bot_b5_upsert_user(bigint,text,text,text) TO obsidian_exchange_bot;
