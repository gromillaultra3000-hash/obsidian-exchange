-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- P5B: six read contracts embedded in atomic mutation functions.

GRANT SELECT(id,web_user_id,subject,username) ON public.support_tickets TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.support_tickets TO obsidian_relay_owner;
GRANT INSERT(ticket_id,sender,message) ON public.support_messages TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.support_messages_id_seq TO obsidian_relay_owner;
GRANT SELECT(order_id,user_id,currency,rub_amount,status,created_at,paid_btc_tx)
 ON public.orders TO obsidian_relay_owner;
GRANT UPDATE(status,paid_btc_tx,updated_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(order_id) ON public.order_receipts TO obsidian_relay_owner;
GRANT SELECT(id,order_id,session_token,provider,provider_invoice_id,status,expires_at)
 ON public.payment_sessions TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.payment_sessions TO obsidian_relay_owner;
GRANT INSERT(order_id,event) ON public.sent_notifications TO obsidian_relay_owner;
GRANT INSERT(kind,order_id,session_token,provider,provider_invoice_id,user_id,currency,
 rub_amount,order_status,has_receipt,detail) ON public.order_lifecycle_work TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.order_lifecycle_work_id_seq TO obsidian_relay_owner;
GRANT SELECT(order_id,status) ON public.gift_vouchers TO obsidian_relay_owner;
GRANT UPDATE(status) ON public.gift_vouchers TO obsidian_relay_owner;
GRANT INSERT(order_id,provider,action,from_status,to_status,evidence)
 ON public.payment_transition_audit TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.payment_transition_audit_id_seq TO obsidian_relay_owner;
GRANT SELECT(order_id) ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT INSERT(order_id,recipient_id,payload) ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.payment_notification_outbox_id_seq TO obsidian_relay_owner;
GRANT SELECT(id,user_id,rub_amount,status,payout_provider,payout_ref,payout_status)
 ON public.sell_orders TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.sell_orders TO obsidian_relay_owner;
GRANT SELECT(sell_id) ON public.sell_settlement_ledger TO obsidian_relay_owner;
GRANT INSERT(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status)
 ON public.sell_settlement_ledger TO obsidian_relay_owner;
GRANT SELECT(user_id,total_rub) ON public.user_vip_volume TO obsidian_relay_owner;
GRANT INSERT(user_id,total_rub,updated_at) ON public.user_vip_volume TO obsidian_relay_owner;
GRANT UPDATE(total_rub,updated_at) ON public.user_vip_volume TO obsidian_relay_owner;
GRANT INSERT(sell_id,recipient_id,rub_amount) ON public.sell_settlement_outbox TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.sell_settlement_outbox_id_seq TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_support_user_reply(
 p_ticket_id bigint,p_web_user_id bigint,p_message text)
RETURNS TABLE(subject text,username text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_subject text;v_username text;
BEGIN
 IF p_ticket_id IS NULL OR p_ticket_id<=0 OR p_web_user_id IS NULL OR p_web_user_id<=0
    OR p_message IS NULL OR length(trim(p_message))<1 OR length(p_message)>4000 THEN
  RAISE EXCEPTION 'invalid_support_reply'; END IF;
 SELECT t.subject,t.username INTO v_subject,v_username FROM public.support_tickets t
  WHERE t.id=p_ticket_id AND t.web_user_id=p_web_user_id FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 INSERT INTO public.support_messages(ticket_id,sender,message)
  VALUES(p_ticket_id,'user',p_message);
 UPDATE public.support_tickets t SET status='open',updated_at=clock_timestamp()
  WHERE t.id=p_ticket_id;
 RETURN QUERY SELECT v_subject,v_username;
END $$;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_expire_due(p_limit smallint)
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r record;s record;v_count integer:=0;
BEGIN
 IF p_limit IS NULL OR p_limit<1 OR p_limit>1000 THEN RAISE EXCEPTION 'invalid_expiry_limit'; END IF;
 FOR r IN SELECT o.order_id,o.user_id,o.currency,o.rub_amount FROM public.orders o
  WHERE o.status='pending' AND o.created_at<CURRENT_TIMESTAMP-interval '2 hours'
   AND NOT EXISTS(SELECT 1 FROM public.order_receipts receipt WHERE receipt.order_id=o.order_id)
   AND NOT EXISTS(SELECT 1 FROM public.payment_sessions ps WHERE ps.order_id=o.order_id
    AND ps.status IN('invoice_created','awaiting_payment') AND ps.expires_at>CURRENT_TIMESTAMP)
  ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT p_limit
 LOOP
  UPDATE public.orders SET status='expired',updated_at=clock_timestamp()
   WHERE order_id=r.order_id AND status='pending';
  IF NOT FOUND THEN CONTINUE; END IF;
  v_count:=v_count+1;
  IF r.user_id>0 THEN
   INSERT INTO public.sent_notifications(order_id,event) VALUES(r.order_id,'order_expired')
    ON CONFLICT DO NOTHING;
   IF FOUND THEN INSERT INTO public.order_lifecycle_work(kind,order_id,user_id,currency,
     rub_amount,order_status) VALUES('order_expired_notify',r.order_id,r.user_id,
     r.currency,r.rub_amount,'expired') ON CONFLICT DO NOTHING; END IF;
  END IF;
  FOR s IN SELECT ps.session_token,ps.provider,ps.provider_invoice_id
   FROM public.payment_sessions ps WHERE ps.order_id=r.order_id
    AND left(ps.provider,6)='brabus' AND ps.provider_invoice_id IS NOT NULL
  LOOP INSERT INTO public.order_lifecycle_work(kind,order_id,session_token,provider,
    provider_invoice_id,order_status) VALUES('provider_cancel',r.order_id,s.session_token,
    s.provider,s.provider_invoice_id,'expired') ON CONFLICT DO NOTHING; END LOOP;
 END LOOP;
 RETURN v_count;
END $$;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_fail_session(
 p_order_id bigint,p_session_token text,p_provider text,p_detail text)
RETURNS TABLE(action text,order_id bigint,claimed boolean)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r record;v_claimed boolean:=false;
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR p_session_token IS NULL
   OR length(trim(p_session_token))<1 OR length(p_session_token)>256
   OR p_provider IS NULL OR length(p_provider)>80
   OR p_detail IS NULL OR length(p_detail)>500 THEN RAISE EXCEPTION 'invalid_failed_session'; END IF;
 UPDATE public.payment_sessions ps SET status='failed',updated_at=clock_timestamp()
  WHERE ps.order_id=p_order_id AND ps.session_token=trim(p_session_token)
   AND ps.status IN('invoice_created','awaiting_payment');
 IF NOT FOUND THEN RETURN QUERY SELECT 'conflict'::text,p_order_id,NULL::boolean;RETURN;END IF;
 SELECT o.user_id,o.rub_amount,o.currency,o.status,
  EXISTS(SELECT 1 FROM public.order_receipts receipt WHERE receipt.order_id=o.order_id) has_receipt
  INTO r FROM public.orders o WHERE o.order_id=p_order_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'failed_session_order_missing'; END IF;
 INSERT INTO public.sent_notifications(order_id,event) VALUES(p_order_id,'session_dead')
  ON CONFLICT DO NOTHING;v_claimed:=FOUND;
 IF v_claimed THEN
  INSERT INTO public.order_lifecycle_work(kind,order_id,session_token,provider,user_id,
   currency,rub_amount,order_status,has_receipt,detail)
   VALUES('session_dead_admin',p_order_id,trim(p_session_token),p_provider,r.user_id,
    r.currency,r.rub_amount,r.status,r.has_receipt,p_detail) ON CONFLICT DO NOTHING;
  IF r.user_id>0 AND r.status NOT IN('paid','sent') THEN
   INSERT INTO public.order_lifecycle_work(kind,order_id,session_token,provider,user_id,
    currency,rub_amount,order_status,has_receipt,detail)
    VALUES('session_dead_customer',p_order_id,trim(p_session_token),p_provider,r.user_id,
     r.currency,r.rub_amount,r.status,r.has_receipt,p_detail) ON CONFLICT DO NOTHING;
  END IF;
 END IF;
 RETURN QUERY SELECT 'failed'::text,p_order_id,v_claimed;
END $$;

CREATE OR REPLACE FUNCTION public.relay_order_mark_sent(p_order_id bigint,p_txid text)
RETURNS TABLE(action text,order_id bigint,txid text,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r record;v text;raw bytea;
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 THEN RAISE EXCEPTION 'invalid_order_id'; END IF;
 SELECT o.currency,o.status,o.paid_btc_tx INTO r FROM public.orders o
  WHERE o.order_id=p_order_id FOR UPDATE;
 IF NOT FOUND THEN RETURN QUERY SELECT 'missing'::text,p_order_id,NULL::text,NULL::text;RETURN;END IF;
 v:=trim(COALESCE(p_txid,''));
 IF v~'^(0x)?[0-9a-fA-F]{64}$' THEN NULL;
 ELSIF upper(r.currency)='TON' THEN
  BEGIN raw:=decode(translate(v,'-_','+/')||repeat('=',(4-(length(v)%4))%4),'base64');
   IF octet_length(raw)=32 THEN v:=encode(raw,'hex');ELSE v:='';END IF;
  EXCEPTION WHEN OTHERS THEN v:='';END;
 ELSE v:=''; END IF;
 IF v='' OR lower(v) IN('manual','manual-reconciled-20260719','pending','none','null','-')
    OR lower(v) LIKE 'http://%' OR lower(v) LIKE 'https://%' THEN
  RETURN QUERY SELECT 'invalid_txid'::text,p_order_id,NULL::text,NULL::text;RETURN;END IF;
 IF r.status<>'paid' OR COALESCE(r.paid_btc_tx,'')<>'' THEN
  RETURN QUERY SELECT 'status_conflict'::text,p_order_id,NULL::text,r.status;RETURN;END IF;
 UPDATE public.orders SET status='sent',paid_btc_tx=v,updated_at=clock_timestamp()
  WHERE orders.order_id=p_order_id AND orders.status='paid' AND COALESCE(orders.paid_btc_tx,'')='';
 IF NOT FOUND THEN RAISE EXCEPTION 'order_sent_transition_lost'; END IF;
 RETURN QUERY SELECT 'transitioned'::text,p_order_id,v,'sent'::text;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_mark_paid(
 p_order_id bigint,p_provider text,p_evidence text,p_session_token text)
RETURNS TABLE(action text,order_id bigint,user_id bigint,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r record;
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR p_provider IS NULL
   OR length(trim(p_provider))<1 OR length(p_provider)>80 OR p_evidence IS NULL
   OR (p_session_token IS NOT NULL AND length(p_session_token)>256) THEN
  RAISE EXCEPTION 'invalid_payment_transition'; END IF;
 SELECT o.status,o.user_id INTO r FROM public.orders o WHERE o.order_id=p_order_id FOR UPDATE;
 IF NOT FOUND THEN RETURN QUERY SELECT 'missing'::text,p_order_id,NULL::bigint,NULL::text;RETURN;END IF;
 IF r.status='paid' THEN RETURN QUERY SELECT 'already_paid'::text,p_order_id,r.user_id,'paid'::text;RETURN;END IF;
 IF r.status<>'pending' THEN RETURN QUERY SELECT 'status_conflict'::text,p_order_id,r.user_id,r.status;RETURN;END IF;
 UPDATE public.orders SET status='paid',updated_at=clock_timestamp() WHERE orders.order_id=p_order_id;
 IF COALESCE(trim(p_session_token),'')<>'' THEN
  UPDATE public.payment_sessions ps SET status='paid',updated_at=clock_timestamp()
   WHERE ps.order_id=p_order_id AND ps.session_token=trim(p_session_token)
    AND ps.status NOT IN('failed','expired');
 ELSE UPDATE public.payment_sessions ps SET status='paid',updated_at=clock_timestamp()
  WHERE ps.id=(SELECT candidate.id FROM public.payment_sessions candidate
   WHERE candidate.order_id=p_order_id AND left(candidate.provider,length(trim(p_provider)))=trim(p_provider)
    AND candidate.status NOT IN('failed','expired') ORDER BY candidate.id DESC LIMIT 1); END IF;
 UPDATE public.gift_vouchers SET status='paid' WHERE gift_vouchers.order_id=p_order_id AND gift_vouchers.status='pending';
 INSERT INTO public.payment_transition_audit(order_id,provider,action,from_status,to_status,evidence)
  VALUES(p_order_id,trim(p_provider),'confirm','pending','paid',left(p_evidence,160));
 IF r.user_id>0 THEN INSERT INTO public.payment_notification_outbox(order_id,recipient_id,payload)
  VALUES(p_order_id,r.user_id,jsonb_build_object('order_id',p_order_id))
  ON CONFLICT ON CONSTRAINT payment_notification_outbox_order_id_key DO NOTHING;END IF;
 RETURN QUERY SELECT 'transitioned'::text,p_order_id,r.user_id,'paid'::text;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_settle_vertu(p_sell_id bigint,p_payout_ref text)
RETURNS TABLE(action text,sell_id bigint,user_id bigint,rub_amount numeric(20,2),
 payout_ref text,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r record;v_ref text;
BEGIN
 v_ref:=trim(COALESCE(p_payout_ref,''));
 IF p_sell_id IS NULL OR p_sell_id<=0 OR length(v_ref)<1 OR length(p_payout_ref)>255 THEN
  RAISE EXCEPTION 'invalid_vertu_settlement';END IF;
 SELECT s.user_id,s.rub_amount,s.status,s.payout_provider,s.payout_ref,s.payout_status
  INTO r FROM public.sell_orders s WHERE s.id=p_sell_id FOR UPDATE;
 IF NOT FOUND THEN RETURN QUERY SELECT 'missing'::text,p_sell_id,NULL::bigint,NULL::numeric,NULL::text,NULL::text;RETURN;END IF;
 IF EXISTS(SELECT 1 FROM public.sell_settlement_ledger l WHERE l.sell_id=p_sell_id) THEN
  RETURN QUERY SELECT 'already_settled'::text,p_sell_id,r.user_id,r.rub_amount,r.payout_ref,r.status;RETURN;END IF;
 IF r.status<>'paying' THEN RETURN QUERY SELECT 'status_conflict'::text,p_sell_id,r.user_id,r.rub_amount,r.payout_ref,r.status;RETURN;END IF;
 IF r.payout_provider<>'vertu' OR COALESCE(r.payout_ref,'')<>v_ref OR lower(COALESCE(r.payout_status,''))<>'paid' THEN
  RETURN QUERY SELECT 'evidence_conflict'::text,p_sell_id,r.user_id,r.rub_amount,r.payout_ref,r.status;RETURN;END IF;
 IF r.user_id<=0 OR r.rub_amount IS NULL OR r.rub_amount<=0 THEN
  RETURN QUERY SELECT 'invalid_ledger_data'::text,p_sell_id,r.user_id,r.rub_amount,r.payout_ref,r.status;RETURN;END IF;
 UPDATE public.sell_orders SET status='paid',updated_at=clock_timestamp()
  WHERE sell_orders.id=p_sell_id AND sell_orders.status='paying'
   AND sell_orders.payout_provider='vertu' AND sell_orders.payout_ref=v_ref
   AND lower(sell_orders.payout_status)='paid';
 IF NOT FOUND THEN RAISE EXCEPTION 'sell_settlement_transition_lost';END IF;
 INSERT INTO public.sell_settlement_ledger(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status)
  VALUES(p_sell_id,r.user_id,r.rub_amount,'vertu',v_ref,'paid');
 INSERT INTO public.user_vip_volume(user_id,total_rub,updated_at) VALUES(r.user_id,r.rub_amount,clock_timestamp())
  ON CONFLICT ON CONSTRAINT user_vip_volume_pkey DO UPDATE
   SET total_rub=public.user_vip_volume.total_rub+excluded.total_rub,
   updated_at=clock_timestamp();
 INSERT INTO public.sell_settlement_outbox(sell_id,recipient_id,rub_amount)
  VALUES(p_sell_id,r.user_id,r.rub_amount);
 RETURN QUERY SELECT 'settled'::text,p_sell_id,r.user_id,r.rub_amount,v_ref,'paid'::text;
END $$;

ALTER FUNCTION public.relay_support_user_reply(bigint,bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_lifecycle_expire_due(smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_lifecycle_fail_session(bigint,text,text,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_order_mark_sent(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_mark_paid(bigint,text,text,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_settle_vertu(bigint,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_support_user_reply(bigint,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_lifecycle_expire_due(smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_lifecycle_fail_session(bigint,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_order_mark_sent(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_mark_paid(bigint,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_settle_vertu(bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_support_user_reply(bigint,bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_expire_due(smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_fail_session(bigint,text,text,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_order_mark_sent(bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_mark_paid(bigint,text,text,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_settle_vertu(bigint,text) TO obsidian_relay;
