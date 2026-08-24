-- E0.3 PROPOSAL ONLY. Derive payout debt from authoritative locked rows.
GRANT SELECT(order_id,status,rub_amount,agreed_crypto_amount,currency,network,crypto_address) ON public.orders TO obsidian_exchange_bot_owner;
GRANT UPDATE(order_id) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(id,order_id,idempotency_key,state,source,requested_by,rub_amount,crypto_amount,currency,network,destination),INSERT(order_id,idempotency_key,source,requested_by,rub_amount,crypto_amount,currency,network,destination) ON public.payout_intents TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.payout_intents_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(referrer_id,referred_id,total_bonus_btc),UPDATE(total_bonus_btc) ON public.referrals TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,idempotency_key,state,crypto_amount,currency,network,destination),INSERT(id,user_id,idempotency_key,crypto_amount,currency,destination) ON public.referral_payout_intents TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.referral_payout_intents_id_seq TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b5_create_order_payout_intent(a_order_id bigint) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE o record;p record;BEGIN
 IF a_order_id IS NULL OR a_order_id<=0 THEN RAISE EXCEPTION 'invalid_order_id';END IF;
 SELECT order_id,status,rub_amount,agreed_crypto_amount,currency,network,crypto_address INTO o FROM public.orders WHERE order_id=a_order_id FOR UPDATE;
 IF NOT FOUND OR o.status<>'paid' OR o.rub_amount<=0 OR o.agreed_crypto_amount IS NULL OR o.agreed_crypto_amount<=0 OR o.crypto_address IS NULL OR length(trim(o.crypto_address))<1 THEN RAISE EXCEPTION 'authoritative_order_not_payable';END IF;
 INSERT INTO public.payout_intents(order_id,idempotency_key,source,requested_by,rub_amount,crypto_amount,currency,network,destination) VALUES(o.order_id,'payout_'||o.order_id,'exchange-bot','exchange-bot',o.rub_amount,o.agreed_crypto_amount,upper(o.currency),CASE WHEN o.network IS NULL THEN NULL ELSE upper(o.network) END,o.crypto_address) ON CONFLICT DO NOTHING;
 SELECT id,order_id,idempotency_key,state,source,requested_by,rub_amount,crypto_amount,currency,network,destination INTO p FROM public.payout_intents WHERE order_id=o.order_id;
 IF NOT FOUND OR p.idempotency_key<>'payout_'||o.order_id OR p.source<>'exchange-bot' OR p.requested_by<>'exchange-bot' OR p.rub_amount<>o.rub_amount OR p.crypto_amount<>o.agreed_crypto_amount OR p.currency<>upper(o.currency) OR p.network IS DISTINCT FROM (CASE WHEN o.network IS NULL THEN NULL ELSE upper(o.network) END) OR p.destination<>o.crypto_address THEN RAISE EXCEPTION 'payout_intent_payload_mismatch';END IF;
 RETURN jsonb_build_object('id',p.id,'order_id',p.order_id,'idempotency_key',p.idempotency_key,'state',p.state,'rub_amount',p.rub_amount,'crypto_amount',p.crypto_amount,'currency',p.currency,'network',p.network,'destination',p.destination);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b5_request_referral_payout(a_user_id bigint,a_destination text,a_minimum numeric) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE p record;total numeric;ident bigint;BEGIN
 a_destination=trim(a_destination);IF a_user_id IS NULL OR a_user_id<=0 OR a_destination IS NULL OR length(a_destination)<1 OR length(a_destination)>512 OR a_minimum IS NULL OR a_minimum::text IN('NaN','Infinity','-Infinity') OR a_minimum<=0 THEN RAISE EXCEPTION 'invalid_referral_request';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('referral_payout:'||a_user_id,0));
 SELECT id,user_id,idempotency_key,state,crypto_amount,currency,network,destination INTO p FROM public.referral_payout_intents WHERE user_id=a_user_id AND state IN('pending','processing','succeeded','review');
 IF FOUND THEN RETURN jsonb_build_object('id',p.id,'user_id',p.user_id,'idempotency_key',p.idempotency_key,'state',p.state,'crypto_amount',p.crypto_amount,'currency',p.currency,'destination',p.destination);END IF;
 PERFORM referred_id FROM public.referrals WHERE referrer_id=a_user_id ORDER BY referred_id FOR UPDATE;
 SELECT coalesce(sum(total_bonus_btc),0) INTO total FROM public.referrals WHERE referrer_id=a_user_id;
 IF total<a_minimum THEN RAISE EXCEPTION 'referral_balance_below_minimum';END IF;
 SELECT nextval('public.referral_payout_intents_id_seq') INTO ident;
 INSERT INTO public.referral_payout_intents(id,user_id,idempotency_key,crypto_amount,currency,destination) VALUES(ident,a_user_id,'referral_'||a_user_id||'_'||ident,total,'BTC',a_destination) RETURNING id,user_id,idempotency_key,state,crypto_amount,currency,network,destination INTO p;
 RETURN jsonb_build_object('id',p.id,'user_id',p.user_id,'idempotency_key',p.idempotency_key,'state',p.state,'crypto_amount',p.crypto_amount,'currency',p.currency,'destination',p.destination);
END $$;
ALTER FUNCTION public.bot_b5_create_order_payout_intent(bigint) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_request_referral_payout(bigint,text,numeric) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b5_create_order_payout_intent(bigint),public.bot_b5_request_referral_payout(bigint,text,numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b5_create_order_payout_intent(bigint),public.bot_b5_request_referral_payout(bigint,text,numeric) TO obsidian_exchange_bot;
