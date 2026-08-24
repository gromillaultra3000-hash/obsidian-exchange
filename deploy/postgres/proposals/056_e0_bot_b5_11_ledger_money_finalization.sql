-- E0.3 PROPOSAL ONLY. Source-bound money finalization; never a generic additive API.
CREATE TABLE public.order_value_terms(
 order_id bigint PRIMARY KEY, terms_id text NOT NULL UNIQUE,
 commission_percent numeric(7,4) NOT NULL CHECK(commission_percent::text<>'NaN' AND commission_percent>=0 AND commission_percent<=100),
 referral_percent numeric(7,4) NOT NULL CHECK(referral_percent::text<>'NaN' AND referral_percent>=0 AND referral_percent<=100),
 btc_rub_rate numeric(30,8) NOT NULL CHECK(btc_rub_rate::text<>'NaN' AND btc_rub_rate>0),
 captured_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.engagement_credit_ledger(
 id bigserial PRIMARY KEY, source_kind text NOT NULL CHECK(source_kind IN('ORDER','SELL')),
 source_id text NOT NULL, credit_kind text NOT NULL CHECK(credit_kind IN('VIP_RUB','REFERRAL_BTC')),
 beneficiary_id bigint NOT NULL CHECK(beneficiary_id>0), referred_id bigint,
 amount numeric(30,12) NOT NULL CHECK(amount::text<>'NaN' AND amount>0), terms_snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(source_kind,source_id,credit_kind)
);
CREATE TABLE public.referral_payout_debit_ledger(
 intent_id bigint PRIMARY KEY REFERENCES public.referral_payout_intents(id),
 user_id bigint NOT NULL, crypto_amount numeric(30,12) NOT NULL CHECK(crypto_amount::text<>'NaN' AND crypto_amount>0),
 txid text NOT NULL, evidence_id text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.sell_payment_evidence(
 id bigserial PRIMARY KEY, evidence_id text NOT NULL UNIQUE, sell_id bigint NOT NULL UNIQUE,
 user_id bigint NOT NULL CHECK(user_id>0),provider text NOT NULL, payout_ref text NOT NULL,
 destination_digest text NOT NULL CHECK(destination_digest~'^[0-9a-f]{32}$'),currency text NOT NULL CHECK(currency='RUB'),
 rub_amount numeric(20,2) NOT NULL CHECK(rub_amount::text<>'NaN' AND rub_amount>0),
 result text NOT NULL CHECK(result='CONFIRMED'), observed_at timestamptz NOT NULL,
 consumed_at timestamptz,UNIQUE(provider,payout_ref)
);

GRANT SELECT(order_id,terms_id,commission_percent,referral_percent,btc_rub_rate,captured_at) ON public.order_value_terms TO obsidian_exchange_bot_owner;
GRANT SELECT(id,source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot),INSERT(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) ON public.engagement_credit_ledger TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.engagement_credit_ledger_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(intent_id,user_id,crypto_amount,txid,evidence_id),INSERT(intent_id,user_id,crypto_amount,txid,evidence_id) ON public.referral_payout_debit_ledger TO obsidian_exchange_bot_owner;
GRANT SELECT(id,evidence_id,sell_id,user_id,provider,payout_ref,destination_digest,currency,rub_amount,result,observed_at,consumed_at),UPDATE(consumed_at) ON public.sell_payment_evidence TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,user_id,rub_amount,status,paid_btc_tx),UPDATE(status,paid_btc_tx,updated_at) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(id,order_id,state,txid,currency,network),UPDATE(state,updated_at) ON public.payout_intents TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,state,crypto_amount,txid),UPDATE(state,updated_at) ON public.referral_payout_intents TO obsidian_exchange_bot_owner;
GRANT SELECT(referrer_id,referred_id,total_bonus_btc),UPDATE(total_bonus_btc,bonus_paid) ON public.referrals TO obsidian_exchange_bot_owner;
GRANT SELECT(user_id,total_rub),INSERT(user_id,total_rub,updated_at),UPDATE(total_rub,updated_at) ON public.user_vip_volume TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,intent_id,txid,referral_btc,vip_rub),INSERT(order_id,intent_id,txid,referral_btc,vip_rub) ON public.payout_reconciliations TO obsidian_exchange_bot_owner;
GRANT SELECT(topic,aggregate_id,recipient_id,payload),INSERT(topic,aggregate_id,recipient_id,payload) ON public.notification_outbox TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.notification_outbox_id_seq TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,currency,rub_amount,status,sbp_phone,payout_bank,payout_details,payout_name,payout_provider,payout_ref),UPDATE(status,payout_provider,payout_ref,updated_at) ON public.sell_orders TO obsidian_exchange_bot_owner;
GRANT SELECT(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status),INSERT(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status) ON public.sell_settlement_ledger TO obsidian_exchange_bot_owner;
GRANT SELECT(sell_id,recipient_id,rub_amount),INSERT(sell_id,recipient_id,rub_amount) ON public.sell_settlement_outbox TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.sell_settlement_outbox_id_seq TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b5_finalize_order_money(a_order_id bigint,a_terms_id text)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE o record;p record;t record;r record;rec record;bonus numeric(30,12):=0; snap jsonb;
BEGIN
 a_terms_id=trim(a_terms_id); IF a_order_id IS NULL OR a_order_id<=0 OR a_terms_id IS NULL OR length(a_terms_id)<1 OR length(a_terms_id)>128 THEN RAISE EXCEPTION 'invalid_order_finalization';END IF;
 SELECT order_id,user_id,rub_amount,status,paid_btc_tx INTO o FROM public.orders WHERE order_id=a_order_id FOR UPDATE;
 IF NOT FOUND THEN RETURN 'not_ready';END IF;
 SELECT id,state,txid,currency,network INTO p FROM public.payout_intents WHERE order_id=a_order_id FOR UPDATE;
 SELECT * INTO t FROM public.order_value_terms WHERE order_id=a_order_id AND terms_id=a_terms_id;
 SELECT order_id,intent_id,txid,referral_btc,vip_rub INTO rec FROM public.payout_reconciliations WHERE order_id=a_order_id;
 snap=jsonb_build_object('terms_id',t.terms_id,'commission_percent',t.commission_percent,'referral_percent',t.referral_percent,'btc_rub_rate',t.btc_rub_rate);
 SELECT referrer_id,referred_id INTO r FROM public.referrals WHERE referred_id=o.user_id FOR UPDATE;
 IF FOUND THEN PERFORM pg_advisory_xact_lock(hashtextextended('referral_payout:'||r.referrer_id,0));bonus=round((o.rub_amount*t.commission_percent/100*t.referral_percent/100/t.btc_rub_rate)::numeric,12);END IF;
 IF rec.order_id IS NOT NULL THEN IF o.status='sent' AND o.paid_btc_tx=rec.txid AND p.id=rec.intent_id AND p.txid=rec.txid AND rec.vip_rub=o.rub_amount AND rec.referral_btc=bonus AND EXISTS(SELECT 1 FROM public.engagement_credit_ledger c WHERE c.source_kind='ORDER' AND c.source_id=a_order_id::text AND c.credit_kind='VIP_RUB' AND c.beneficiary_id=o.user_id AND c.amount=o.rub_amount AND c.terms_snapshot=snap) AND (bonus=0 OR EXISTS(SELECT 1 FROM public.engagement_credit_ledger c WHERE c.source_kind='ORDER' AND c.source_id=a_order_id::text AND c.credit_kind='REFERRAL_BTC' AND c.beneficiary_id=r.referrer_id AND c.referred_id=o.user_id AND c.amount=bonus AND c.terms_snapshot=snap)) AND EXISTS(SELECT 1 FROM public.notification_outbox n WHERE n.topic='payout_sent' AND n.aggregate_id=a_order_id::text AND n.recipient_id=o.user_id AND n.payload->>'txid'=p.txid) THEN RETURN 'already_reconciled';END IF;RAISE EXCEPTION 'order_reconciliation_replay_mismatch';END IF;
 IF t.terms_id IS NULL OR o.status<>'paid' OR o.rub_amount::text='NaN' OR o.rub_amount<=0 OR p.state<>'succeeded' OR p.txid IS NULL THEN RETURN 'not_ready';END IF;
 IF NOT EXISTS(SELECT 1 FROM public.payout_chain_evidence e WHERE e.debt_kind='ORDER' AND e.debt_id=a_order_id AND e.result='CONFIRMED' AND e.txid=p.txid AND e.consumed_at IS NOT NULL) THEN RETURN 'evidence_conflict';END IF;
 UPDATE public.orders SET status='sent',paid_btc_tx=p.txid,updated_at=clock_timestamp() WHERE order_id=a_order_id AND status='paid'; IF NOT FOUND THEN RAISE EXCEPTION 'order_transition_lost';END IF;
 INSERT INTO public.engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,amount,terms_snapshot) VALUES('ORDER',a_order_id::text,'VIP_RUB',o.user_id,o.rub_amount,snap);
 INSERT INTO public.user_vip_volume(user_id,total_rub,updated_at) VALUES(o.user_id,o.rub_amount,clock_timestamp()) ON CONFLICT(user_id) DO UPDATE SET total_rub=public.user_vip_volume.total_rub+excluded.total_rub,updated_at=clock_timestamp();
 IF bonus>0 THEN INSERT INTO public.engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) VALUES('ORDER',a_order_id::text,'REFERRAL_BTC',r.referrer_id,o.user_id,bonus,snap); UPDATE public.referrals SET total_bonus_btc=total_bonus_btc+bonus,bonus_paid=false WHERE referrer_id=r.referrer_id AND referred_id=o.user_id;END IF;
 INSERT INTO public.payout_reconciliations(order_id,intent_id,txid,referral_btc,vip_rub) VALUES(a_order_id,p.id,p.txid,bonus,o.rub_amount);
 INSERT INTO public.notification_outbox(topic,aggregate_id,recipient_id,payload) VALUES('payout_sent',a_order_id::text,o.user_id,jsonb_build_object('order_id',a_order_id,'txid',p.txid,'currency',p.currency,'network',p.network));
 RETURN 'reconciled';
END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_finalize_referral_money(a_intent_id bigint) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;d record;available numeric;remaining numeric;x record;take numeric;evid text;
BEGIN IF a_intent_id IS NULL OR a_intent_id<=0 THEN RAISE EXCEPTION 'invalid_referral_finalization';END IF;
 SELECT id,user_id,state,crypto_amount,txid INTO p FROM public.referral_payout_intents WHERE id=a_intent_id FOR UPDATE;IF NOT FOUND THEN RETURN 'not_ready';END IF;
 SELECT evidence_id INTO evid FROM public.payout_chain_evidence WHERE debt_kind='REFERRAL' AND debt_id=a_intent_id AND result='CONFIRMED' AND txid=p.txid AND consumed_at IS NOT NULL;
 SELECT intent_id,user_id,crypto_amount,txid,evidence_id INTO d FROM public.referral_payout_debit_ledger WHERE intent_id=a_intent_id;IF FOUND THEN IF d.user_id=p.user_id AND d.crypto_amount=p.crypto_amount AND d.txid=p.txid AND d.evidence_id=evid THEN RETURN 'already_reconciled';END IF;RAISE EXCEPTION 'referral_reconciliation_replay_mismatch';END IF;
 IF p.state<>'succeeded' OR p.txid IS NULL OR evid IS NULL THEN RETURN 'not_ready';END IF;
 PERFORM referred_id FROM public.referrals WHERE referrer_id=p.user_id ORDER BY referred_id FOR UPDATE;
 SELECT coalesce(sum(total_bonus_btc),0) INTO available FROM public.referrals WHERE referrer_id=p.user_id;IF available<p.crypto_amount THEN RAISE EXCEPTION 'reserved_balance_missing';END IF;
 remaining=p.crypto_amount;FOR x IN SELECT referred_id,total_bonus_btc FROM public.referrals WHERE referrer_id=p.user_id AND total_bonus_btc>0 ORDER BY referred_id LOOP take=least(x.total_bonus_btc,remaining);UPDATE public.referrals SET total_bonus_btc=total_bonus_btc-take WHERE referrer_id=p.user_id AND referred_id=x.referred_id;remaining=remaining-take;EXIT WHEN remaining=0;END LOOP;
 INSERT INTO public.referral_payout_debit_ledger(intent_id,user_id,crypto_amount,txid,evidence_id) VALUES(p.id,p.user_id,p.crypto_amount,p.txid,evid);
 UPDATE public.referral_payout_intents SET state='reconciled',updated_at=clock_timestamp() WHERE id=p.id AND state='succeeded';IF NOT FOUND THEN RAISE EXCEPTION 'referral_transition_lost';END IF;
 INSERT INTO public.notification_outbox(topic,aggregate_id,recipient_id,payload) VALUES('referral_payout_sent',p.id::text,p.user_id,jsonb_build_object('intent_id',p.id,'txid',p.txid,'currency','BTC'));
 RETURN 'reconciled';END $$;

CREATE OR REPLACE FUNCTION public.bot_b5_sell_record_processing(a_sell_id bigint,a_provider text) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN a_provider=lower(trim(a_provider));IF a_sell_id IS NULL OR a_sell_id<=0 OR a_provider NOT IN('vertu','manual') THEN RAISE EXCEPTION 'invalid_sell_processing';END IF;UPDATE public.sell_orders SET payout_provider=a_provider,updated_at=clock_timestamp() WHERE id=a_sell_id AND status='paying';RETURN FOUND;END $$;
CREATE OR REPLACE FUNCTION public.bot_b5_finalize_sell_money(a_sell_id bigint,a_evidence_id text) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE s record;e record;
BEGIN a_evidence_id=trim(a_evidence_id);IF a_sell_id IS NULL OR a_sell_id<=0 OR a_evidence_id IS NULL OR length(a_evidence_id)<1 OR length(a_evidence_id)>128 THEN RAISE EXCEPTION 'invalid_sell_finalization';END IF;
 SELECT id,user_id,rub_amount,status,payout_provider,payout_ref INTO s FROM public.sell_orders WHERE id=a_sell_id FOR UPDATE;IF NOT FOUND THEN RETURN 'not_ready';END IF;IF EXISTS(SELECT 1 FROM public.sell_settlement_ledger WHERE sell_id=a_sell_id) THEN RETURN 'already_settled';END IF;
 SELECT * INTO e FROM public.sell_payment_evidence WHERE evidence_id=a_evidence_id AND sell_id=a_sell_id AND result='CONFIRMED' AND consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND OR s.status<>'paying' OR e.provider<>'vertu' OR e.provider<>s.payout_provider OR e.rub_amount<>s.rub_amount OR e.observed_at>clock_timestamp() THEN RETURN 'evidence_conflict';END IF;
 UPDATE public.sell_payment_evidence SET consumed_at=clock_timestamp() WHERE id=e.id AND consumed_at IS NULL;
 UPDATE public.sell_orders SET status='paid',payout_ref=e.payout_ref,updated_at=clock_timestamp() WHERE id=a_sell_id AND status='paying';IF NOT FOUND THEN RAISE EXCEPTION 'sell_transition_lost';END IF;
 INSERT INTO public.sell_settlement_ledger(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status) VALUES(a_sell_id,s.user_id,s.rub_amount,'vertu',e.payout_ref,'paid');
 INSERT INTO public.engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,amount,terms_snapshot) VALUES('SELL',a_sell_id::text,'VIP_RUB',s.user_id,s.rub_amount,jsonb_build_object('evidence_id',a_evidence_id,'provider',e.provider));
 INSERT INTO public.user_vip_volume(user_id,total_rub,updated_at) VALUES(s.user_id,s.rub_amount,clock_timestamp()) ON CONFLICT(user_id) DO UPDATE SET total_rub=public.user_vip_volume.total_rub+excluded.total_rub,updated_at=clock_timestamp();
 INSERT INTO public.sell_settlement_outbox(sell_id,recipient_id,rub_amount) VALUES(a_sell_id,s.user_id,s.rub_amount);RETURN 'settled';END $$;

ALTER FUNCTION public.bot_b5_finalize_order_money(bigint,text) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_finalize_referral_money(bigint) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_sell_record_processing(bigint,text) OWNER TO obsidian_exchange_bot_owner;ALTER FUNCTION public.bot_b5_finalize_sell_money(bigint,text) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b5_finalize_order_money(bigint,text),public.bot_b5_finalize_referral_money(bigint),public.bot_b5_sell_record_processing(bigint,text),public.bot_b5_finalize_sell_money(bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b5_finalize_order_money(bigint,text),public.bot_b5_finalize_referral_money(bigint),public.bot_b5_sell_record_processing(bigint,text),public.bot_b5_finalize_sell_money(bigint,text) TO obsidian_exchange_bot;
