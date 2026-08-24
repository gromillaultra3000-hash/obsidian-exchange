-- E0.3 PROPOSAL ONLY. Completes B5.11 source provenance and reservations.
ALTER TABLE public.engagement_credit_ledger DROP CONSTRAINT engagement_credit_ledger_source_kind_check;
ALTER TABLE public.engagement_credit_ledger ADD CONSTRAINT engagement_credit_ledger_source_kind_check CHECK(source_kind IN('ORDER','SELL','SWAP','LEGACY'));

CREATE TABLE public.referral_credit_reservations(
 intent_id bigint NOT NULL REFERENCES public.referral_payout_intents(id),
 credit_id bigint NOT NULL REFERENCES public.engagement_credit_ledger(id),
 amount numeric(30,12) NOT NULL CHECK(amount::text<>'NaN' AND amount>0), consumed_at timestamptz,
 PRIMARY KEY(intent_id,credit_id)
);
CREATE TABLE public.swap_value_evidence(
 id bigserial PRIMARY KEY,evidence_id text NOT NULL UNIQUE,session_token text NOT NULL UNIQUE,
 user_id bigint NOT NULL CHECK(user_id>0),coin_from text NOT NULL,amount_from numeric(30,12) NOT NULL CHECK(amount_from::text<>'NaN' AND amount_from>0),
 rub_value numeric(20,2) NOT NULL CHECK(rub_value::text<>'NaN' AND rub_value>0),btc_rub_rate numeric(30,8) NOT NULL CHECK(btc_rub_rate::text<>'NaN' AND btc_rub_rate>0),
 commission_percent numeric(7,4) NOT NULL CHECK(commission_percent::text<>'NaN' AND commission_percent BETWEEN 0 AND 100),
 referral_percent numeric(7,4) NOT NULL CHECK(referral_percent::text<>'NaN' AND referral_percent BETWEEN 0 AND 100),
 result text NOT NULL CHECK(result='CONFIRMED'),observed_at timestamptz NOT NULL,consumed_at timestamptz
);
CREATE TABLE public.bot_sell_finalization_ledger(
 sell_id bigint PRIMARY KEY,user_id bigint NOT NULL,rub_amount numeric(20,2) NOT NULL CHECK(rub_amount::text<>'NaN' AND rub_amount>0),
 provider text NOT NULL CHECK(provider IN('vertu','manual')),payout_ref text NOT NULL CHECK(payout_ref<>''),
 evidence_id text NOT NULL UNIQUE,settled_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.bot_sell_finalization_outbox(
 id bigserial PRIMARY KEY,sell_id bigint NOT NULL UNIQUE,recipient_id bigint NOT NULL,rub_amount numeric(20,2) NOT NULL CHECK(rub_amount>0),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.payout_hold_evidence(
 id bigserial PRIMARY KEY,evidence_id text NOT NULL UNIQUE,order_id bigint NOT NULL,reason text NOT NULL,
 observed_at timestamptz NOT NULL,consumed_at timestamptz
);

GRANT SELECT(intent_id,credit_id,amount,consumed_at),INSERT(intent_id,credit_id,amount),UPDATE(consumed_at) ON public.referral_credit_reservations TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,idempotency_key,state,crypto_amount,currency,network,destination,txid),INSERT(id,user_id,idempotency_key,crypto_amount,currency,destination),UPDATE(state,updated_at) ON public.referral_payout_intents TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.referral_payout_intents_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(id,evidence_id,session_token,user_id,coin_from,amount_from,rub_value,btc_rub_rate,commission_percent,referral_percent,result,observed_at,consumed_at),UPDATE(consumed_at) ON public.swap_value_evidence TO obsidian_exchange_bot_owner;
GRANT SELECT(session_token,user_id,coin_from,amount_from,status),UPDATE(updated_at) ON public.swap_sessions TO obsidian_exchange_bot_owner;
GRANT SELECT(sell_id,user_id,rub_amount,provider,payout_ref,evidence_id),INSERT(sell_id,user_id,rub_amount,provider,payout_ref,evidence_id) ON public.bot_sell_finalization_ledger TO obsidian_exchange_bot_owner;
GRANT SELECT(sell_id,recipient_id,rub_amount),INSERT(sell_id,recipient_id,rub_amount) ON public.bot_sell_finalization_outbox TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.bot_sell_finalization_outbox_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(id,evidence_id,order_id,reason,observed_at,consumed_at),UPDATE(consumed_at) ON public.payout_hold_evidence TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b5_request_referral_payout(a_user_id bigint,a_destination text,a_minimum numeric)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;total numeric:=0;ident bigint;x record;free numeric;remaining numeric;
BEGIN
 a_destination=trim(a_destination);IF a_user_id IS NULL OR a_user_id<=0 OR a_destination IS NULL OR length(a_destination)<1 OR length(a_destination)>512 OR a_minimum IS NULL OR a_minimum::text IN('NaN','Infinity','-Infinity') OR a_minimum<=0 THEN RAISE EXCEPTION 'invalid_referral_request';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('referral_payout:'||a_user_id,0));
 SELECT id,user_id,idempotency_key,state,crypto_amount,currency,network,destination INTO p FROM public.referral_payout_intents WHERE user_id=a_user_id AND state IN('pending','processing','succeeded','review') FOR UPDATE;
 IF FOUND THEN RETURN jsonb_build_object('id',p.id,'user_id',p.user_id,'idempotency_key',p.idempotency_key,'state',p.state,'crypto_amount',p.crypto_amount,'currency',p.currency,'destination',p.destination);END IF;
 SELECT coalesce(sum(c.amount-coalesce((SELECT sum(r.amount) FROM public.referral_credit_reservations r WHERE r.credit_id=c.id),0)),0) INTO total FROM public.engagement_credit_ledger c WHERE c.credit_kind='REFERRAL_BTC' AND c.beneficiary_id=a_user_id;
 IF total<a_minimum THEN RAISE EXCEPTION 'referral_balance_below_minimum';END IF;
 SELECT nextval('public.referral_payout_intents_id_seq') INTO ident;
 INSERT INTO public.referral_payout_intents(id,user_id,idempotency_key,crypto_amount,currency,destination) VALUES(ident,a_user_id,'referral_'||a_user_id||'_'||ident,total,'BTC',a_destination) RETURNING id,user_id,idempotency_key,state,crypto_amount,currency,network,destination INTO p;
 remaining=total;
 FOR x IN SELECT c.id,c.amount-coalesce((SELECT sum(r.amount) FROM public.referral_credit_reservations r WHERE r.credit_id=c.id),0) AS free FROM public.engagement_credit_ledger c WHERE c.credit_kind='REFERRAL_BTC' AND c.beneficiary_id=a_user_id ORDER BY c.id LOOP
  free=least(x.free,remaining);IF free>0 THEN INSERT INTO public.referral_credit_reservations(intent_id,credit_id,amount) VALUES(ident,x.id,free);remaining=remaining-free;END IF;EXIT WHEN remaining=0;
 END LOOP;
 IF remaining<>0 THEN RAISE EXCEPTION 'referral_reservation_lost';END IF;
 RETURN jsonb_build_object('id',p.id,'user_id',p.user_id,'idempotency_key',p.idempotency_key,'state',p.state,'crypto_amount',p.crypto_amount,'currency',p.currency,'destination',p.destination);
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_finalize_referral_money(a_intent_id bigint) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;d record;reserved numeric;evid text;x record;
BEGIN IF a_intent_id IS NULL OR a_intent_id<=0 THEN RAISE EXCEPTION 'invalid_referral_finalization';END IF;
 SELECT id,user_id,state,crypto_amount,txid INTO p FROM public.referral_payout_intents WHERE id=a_intent_id FOR UPDATE;IF NOT FOUND THEN RETURN 'not_ready';END IF;
 SELECT evidence_id INTO evid FROM public.payout_chain_evidence WHERE debt_kind='REFERRAL' AND debt_id=a_intent_id AND result='CONFIRMED' AND txid=p.txid AND consumed_at IS NOT NULL;
 SELECT intent_id,user_id,crypto_amount,txid,evidence_id INTO d FROM public.referral_payout_debit_ledger WHERE intent_id=a_intent_id;IF FOUND THEN IF d.user_id=p.user_id AND d.crypto_amount=p.crypto_amount AND d.txid=p.txid AND d.evidence_id=evid THEN RETURN 'already_reconciled';END IF;RAISE EXCEPTION 'referral_reconciliation_replay_mismatch';END IF;
 PERFORM credit_id FROM public.referral_credit_reservations WHERE intent_id=a_intent_id AND consumed_at IS NULL ORDER BY credit_id FOR UPDATE;
 SELECT coalesce(sum(amount),0) INTO reserved FROM public.referral_credit_reservations WHERE intent_id=a_intent_id AND consumed_at IS NULL;
 IF p.state<>'succeeded' OR p.txid IS NULL OR evid IS NULL OR reserved<>p.crypto_amount THEN RETURN 'not_ready';END IF;
 FOR x IN SELECT r.amount,c.referred_id FROM public.referral_credit_reservations r JOIN public.engagement_credit_ledger c ON c.id=r.credit_id WHERE r.intent_id=a_intent_id AND r.consumed_at IS NULL ORDER BY r.credit_id LOOP
  UPDATE public.referrals SET total_bonus_btc=total_bonus_btc-x.amount WHERE referrer_id=p.user_id AND referred_id=x.referred_id AND total_bonus_btc>=x.amount;IF NOT FOUND THEN RAISE EXCEPTION 'reserved_projection_missing';END IF;
 END LOOP;
 UPDATE public.referral_credit_reservations SET consumed_at=clock_timestamp() WHERE intent_id=a_intent_id AND consumed_at IS NULL;
 INSERT INTO public.referral_payout_debit_ledger(intent_id,user_id,crypto_amount,txid,evidence_id) VALUES(p.id,p.user_id,p.crypto_amount,p.txid,evid);
 UPDATE public.referral_payout_intents SET state='reconciled',updated_at=clock_timestamp() WHERE id=p.id AND state='succeeded';IF NOT FOUND THEN RAISE EXCEPTION 'referral_transition_lost';END IF;
 INSERT INTO public.notification_outbox(topic,aggregate_id,recipient_id,payload) VALUES('referral_payout_sent',p.id::text,p.user_id,jsonb_build_object('intent_id',p.id,'txid',p.txid,'currency','BTC'));
 RETURN 'reconciled';END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_finalize_swap_referral(a_session_token text,a_evidence_id text) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE s record;e record;r record;bonus numeric(30,12);snap jsonb;
BEGIN a_session_token=trim(a_session_token);a_evidence_id=trim(a_evidence_id);IF a_session_token IS NULL OR length(a_session_token)<1 OR length(a_session_token)>128 OR a_evidence_id IS NULL OR length(a_evidence_id)<1 OR length(a_evidence_id)>128 THEN RAISE EXCEPTION 'invalid_swap_finalization';END IF;
 SELECT session_token,user_id,coin_from,amount_from,status INTO s FROM public.swap_sessions WHERE session_token=a_session_token FOR UPDATE;IF NOT FOUND OR lower(s.status)<>'finished' THEN RETURN 'not_ready';END IF;
 SELECT * INTO e FROM public.swap_value_evidence WHERE evidence_id=a_evidence_id AND session_token=a_session_token AND result='CONFIRMED' FOR UPDATE;
 IF NOT FOUND OR e.user_id<>s.user_id OR upper(e.coin_from)<>upper(s.coin_from) OR e.amount_from<>s.amount_from OR e.observed_at>clock_timestamp() THEN RETURN 'evidence_conflict';END IF;
 SELECT referrer_id,referred_id INTO r FROM public.referrals WHERE referred_id=s.user_id FOR UPDATE;IF NOT FOUND THEN RETURN 'no_referrer';END IF;PERFORM pg_advisory_xact_lock(hashtextextended('referral_payout:'||r.referrer_id,0));
 bonus=round((e.rub_value*e.commission_percent/100*e.referral_percent/100/e.btc_rub_rate)::numeric,12);IF bonus<=0 THEN RETURN 'zero_credit';END IF;
 snap=jsonb_build_object('evidence_id',e.evidence_id,'rub_value',e.rub_value,'btc_rub_rate',e.btc_rub_rate,'commission_percent',e.commission_percent,'referral_percent',e.referral_percent);
 IF EXISTS(SELECT 1 FROM public.engagement_credit_ledger c WHERE c.source_kind='SWAP' AND c.source_id=a_session_token AND c.credit_kind='REFERRAL_BTC') THEN IF e.consumed_at IS NOT NULL AND EXISTS(SELECT 1 FROM public.engagement_credit_ledger c WHERE c.source_kind='SWAP' AND c.source_id=a_session_token AND c.credit_kind='REFERRAL_BTC' AND c.beneficiary_id=r.referrer_id AND c.referred_id=s.user_id AND c.amount=bonus AND c.terms_snapshot=snap) THEN RETURN 'already_credited';END IF;RAISE EXCEPTION 'swap_credit_replay_mismatch';END IF;
 IF e.consumed_at IS NOT NULL THEN RETURN 'evidence_conflict';END IF;
 UPDATE public.swap_value_evidence SET consumed_at=clock_timestamp() WHERE id=e.id AND consumed_at IS NULL;
 INSERT INTO public.engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) VALUES('SWAP',a_session_token,'REFERRAL_BTC',r.referrer_id,s.user_id,bonus,snap);
 UPDATE public.referrals SET total_bonus_btc=total_bonus_btc+bonus,bonus_paid=false WHERE referrer_id=r.referrer_id AND referred_id=s.user_id;RETURN 'credited';END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_finalize_sell_money(a_sell_id bigint,a_evidence_id text) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE s record;e record;
BEGIN a_evidence_id=trim(a_evidence_id);IF a_sell_id IS NULL OR a_sell_id<=0 OR a_evidence_id IS NULL OR length(a_evidence_id)<1 OR length(a_evidence_id)>128 THEN RAISE EXCEPTION 'invalid_sell_finalization';END IF;
 SELECT id,user_id,currency,rub_amount,status,sbp_phone,payout_bank,payout_details,payout_name,payout_provider,payout_ref INTO s FROM public.sell_orders WHERE id=a_sell_id FOR UPDATE;IF NOT FOUND OR s.user_id<=0 THEN RETURN 'not_ready';END IF;
 SELECT * INTO e FROM public.sell_payment_evidence WHERE evidence_id=a_evidence_id AND sell_id=a_sell_id AND result='CONFIRMED' FOR UPDATE;
 IF NOT FOUND OR e.user_id<>s.user_id OR e.currency<>'RUB' OR e.destination_digest<>md5(jsonb_build_array(s.sbp_phone,s.payout_bank,s.payout_details,s.payout_name)::text) OR e.provider NOT IN('vertu','manual') OR e.provider<>s.payout_provider OR e.rub_amount<>s.rub_amount OR e.observed_at>clock_timestamp() THEN RETURN 'evidence_conflict';END IF;
 IF EXISTS(SELECT 1 FROM public.bot_sell_finalization_ledger l WHERE l.sell_id=a_sell_id) THEN IF e.consumed_at IS NOT NULL AND EXISTS(SELECT 1 FROM public.bot_sell_finalization_ledger l WHERE l.sell_id=a_sell_id AND l.user_id=s.user_id AND l.rub_amount=s.rub_amount AND l.provider=e.provider AND l.payout_ref=e.payout_ref AND l.evidence_id=e.evidence_id) AND EXISTS(SELECT 1 FROM public.engagement_credit_ledger c WHERE c.source_kind='SELL' AND c.source_id=a_sell_id::text AND c.credit_kind='VIP_RUB' AND c.beneficiary_id=s.user_id AND c.amount=s.rub_amount AND c.terms_snapshot=jsonb_build_object('evidence_id',a_evidence_id,'provider',e.provider)) AND EXISTS(SELECT 1 FROM public.bot_sell_finalization_outbox o WHERE o.sell_id=a_sell_id AND o.recipient_id=s.user_id AND o.rub_amount=s.rub_amount) THEN RETURN 'already_settled';END IF;RAISE EXCEPTION 'sell_settlement_replay_mismatch';END IF;
 IF s.status<>'paying' OR e.consumed_at IS NOT NULL THEN RETURN 'evidence_conflict';END IF;
 UPDATE public.sell_payment_evidence SET consumed_at=clock_timestamp() WHERE id=e.id AND consumed_at IS NULL;
 UPDATE public.sell_orders SET status='paid',payout_ref=e.payout_ref,updated_at=clock_timestamp() WHERE id=a_sell_id AND status='paying';IF NOT FOUND THEN RAISE EXCEPTION 'sell_transition_lost';END IF;
 INSERT INTO public.bot_sell_finalization_ledger(sell_id,user_id,rub_amount,provider,payout_ref,evidence_id) VALUES(a_sell_id,s.user_id,s.rub_amount,e.provider,e.payout_ref,e.evidence_id);
 INSERT INTO public.engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,amount,terms_snapshot) VALUES('SELL',a_sell_id::text,'VIP_RUB',s.user_id,s.rub_amount,jsonb_build_object('evidence_id',a_evidence_id,'provider',e.provider));
 INSERT INTO public.user_vip_volume(user_id,total_rub,updated_at) VALUES(s.user_id,s.rub_amount,clock_timestamp()) ON CONFLICT(user_id) DO UPDATE SET total_rub=public.user_vip_volume.total_rub+excluded.total_rub,updated_at=clock_timestamp();
 INSERT INTO public.bot_sell_finalization_outbox(sell_id,recipient_id,rub_amount) VALUES(a_sell_id,s.user_id,s.rub_amount);RETURN 'settled';END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_record_payout_hold(a_order_id bigint,a_evidence_id text) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e record;
BEGIN a_evidence_id=trim(a_evidence_id);IF a_order_id IS NULL OR a_order_id<=0 OR a_evidence_id IS NULL OR length(a_evidence_id)<1 OR length(a_evidence_id)>128 THEN RAISE EXCEPTION 'invalid_payout_hold';END IF;
 PERFORM 1 FROM public.payout_intents WHERE order_id=a_order_id AND state='review' FOR UPDATE;IF NOT FOUND THEN RETURN false;END IF;
 SELECT * INTO e FROM public.payout_hold_evidence WHERE evidence_id=a_evidence_id AND order_id=a_order_id AND consumed_at IS NULL AND observed_at<=clock_timestamp() FOR UPDATE;IF NOT FOUND THEN RETURN false;END IF;
 UPDATE public.payout_hold_evidence SET consumed_at=clock_timestamp() WHERE id=e.id AND consumed_at IS NULL;
 INSERT INTO public.payout_intent_audit(order_id,actor,action,from_state,to_state,evidence) VALUES(a_order_id,'payout-evidence-principal','hold','review','review',e.evidence_id);RETURN true;END $$;

ALTER FUNCTION public.bot_b5_request_referral_payout(bigint,text,numeric) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_finalize_referral_money(bigint) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_finalize_swap_referral(text,text) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_finalize_sell_money(bigint,text) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_record_payout_hold(bigint,text) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b5_request_referral_payout(bigint,text,numeric),public.bot_b5_finalize_referral_money(bigint),public.bot_b5_finalize_swap_referral(text,text),public.bot_b5_finalize_sell_money(bigint,text),public.bot_b5_record_payout_hold(bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b5_request_referral_payout(bigint,text,numeric),public.bot_b5_finalize_referral_money(bigint),public.bot_b5_finalize_swap_referral(text,text),public.bot_b5_finalize_sell_money(bigint,text),public.bot_b5_record_payout_hold(bigint,text) TO obsidian_exchange_bot;
