-- E0.3 PROPOSAL ONLY. Server-time, policy-bound, per-recipient B5.3 producers.
-- Apply only after proposals 048 and 058 in a clean disposable rehearsal.
BEGIN;
DO $$ BEGIN
 IF to_regrole('obsidian_exchange_bot_background_owner') IS NULL
    OR to_regrole('obsidian_exchange_bot_background') IS NULL THEN
  RAISE EXCEPTION 'b59_background_roles_missing';
 END IF;
 IF EXISTS(SELECT 1 FROM public.bot_notification_jobs) THEN
  RAISE EXCEPTION 'existing_notification_jobs_require_expand_backfill';
 END IF;
END $$;

CREATE TABLE public.bot_notification_policy_versions(
 policy_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 version bigint UNIQUE NOT NULL CHECK(version>0),
 policy_sha256 text UNIQUE NOT NULL CHECK(policy_sha256 ~ '^[0-9a-f]{64}$'),
 approval_evidence_sha256 text NOT NULL CHECK(approval_evidence_sha256 ~ '^[0-9a-f]{64}$'),
 effective_from timestamptz NOT NULL,
 effective_until timestamptz NOT NULL,
 recall_enabled boolean NOT NULL,
 montera_enabled boolean NOT NULL,
 abandoned_enabled boolean NOT NULL,
 payout_delay_enabled boolean NOT NULL,
 payout_warn_minutes integer NOT NULL CHECK(payout_warn_minutes BETWEEN 0 AND 10080),
 winback_enabled boolean NOT NULL,
 winback_discount numeric NOT NULL CHECK(winback_discount::text NOT IN('NaN','Infinity','-Infinity') AND winback_discount>0 AND winback_discount<=20),
 winback_valid_hours integer NOT NULL CHECK(winback_valid_hours BETWEEN 1 AND 720),
 max_attempts smallint NOT NULL CHECK(max_attempts BETWEEN 1 AND 20),
 admin_recipient_ids bigint[] NOT NULL,
 approved_by bigint NOT NULL CHECK(approved_by>0),
 approved_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(effective_until>effective_from),
 CHECK(effective_from>=approved_at),
 CHECK(approved_at<=created_at+interval '1 minute'),
 CHECK(cardinality(admin_recipient_ids) BETWEEN 1 AND 8),
 CHECK(array_position(admin_recipient_ids,NULL) IS NULL),
 UNIQUE(policy_id,version)
);

CREATE FUNCTION public.bot_b59_policy_guard() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_id bigint;v_previous bigint:=0;v_digest text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'notification_policy_immutable'; END IF;
 FOREACH v_id IN ARRAY NEW.admin_recipient_ids LOOP
  IF v_id<=v_previous THEN RAISE EXCEPTION 'admin_recipients_not_strictly_sorted_unique_positive'; END IF;
  v_previous=v_id;
 END LOOP;
 v_digest=encode(pg_catalog.sha256(pg_catalog.convert_to(jsonb_build_object(
  'version',NEW.version,'effective_from',NEW.effective_from,'effective_until',NEW.effective_until,
  'recall_enabled',NEW.recall_enabled,'montera_enabled',NEW.montera_enabled,
  'abandoned_enabled',NEW.abandoned_enabled,'payout_delay_enabled',NEW.payout_delay_enabled,
  'payout_warn_minutes',NEW.payout_warn_minutes,'winback_enabled',NEW.winback_enabled,
  'winback_discount',NEW.winback_discount,'winback_valid_hours',NEW.winback_valid_hours,
  'max_attempts',NEW.max_attempts,'admin_recipient_ids',NEW.admin_recipient_ids,
  'approved_by',NEW.approved_by,'approved_at',NEW.approved_at
 )::text,'UTF8')),'hex');
 IF NEW.policy_sha256 IS NOT NULL AND NEW.policy_sha256<>v_digest THEN RAISE EXCEPTION 'policy_digest_mismatch'; END IF;
 NEW.policy_sha256=v_digest;
 RETURN NEW;
END $$;
CREATE TRIGGER bot_notification_policy_immutable BEFORE INSERT OR UPDATE OR DELETE
 ON public.bot_notification_policy_versions FOR EACH ROW EXECUTE FUNCTION public.bot_b59_policy_guard();

CREATE TABLE public.bot_notification_policy_current(
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 policy_id uuid NOT NULL REFERENCES public.bot_notification_policy_versions(policy_id) ON DELETE RESTRICT,
 policy_version bigint NOT NULL,
 activated_by bigint NOT NULL CHECK(activated_by>0),
 activated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(policy_id,policy_version) REFERENCES public.bot_notification_policy_versions(policy_id,version) ON DELETE RESTRICT
);

ALTER TABLE public.bot_notification_jobs
 ADD COLUMN policy_id uuid,
 ADD COLUMN policy_version bigint,
 ADD COLUMN eligibility_at timestamptz;
ALTER TABLE public.bot_notification_jobs
 ALTER COLUMN policy_id SET NOT NULL,
 ALTER COLUMN policy_version SET NOT NULL,
 ALTER COLUMN eligibility_at SET NOT NULL,
 ADD CONSTRAINT bot_notification_jobs_policy_fk FOREIGN KEY(policy_id)
  REFERENCES public.bot_notification_policy_versions(policy_id) ON DELETE RESTRICT,
 ADD CONSTRAINT bot_notification_jobs_policy_version_fk FOREIGN KEY(policy_id,policy_version)
  REFERENCES public.bot_notification_policy_versions(policy_id,version) ON DELETE RESTRICT,
 ADD CONSTRAINT bot_notification_jobs_policy_version_check CHECK(policy_version>0);

GRANT USAGE ON SCHEMA public TO obsidian_exchange_bot_background_owner,obsidian_exchange_bot_background;
GRANT SELECT(policy_id,version,effective_from,effective_until,recall_enabled,montera_enabled,
 abandoned_enabled,payout_delay_enabled,payout_warn_minutes,winback_enabled,winback_discount,
 winback_valid_hours,max_attempts,admin_recipient_ids) ON public.bot_notification_policy_versions
 TO obsidian_exchange_bot_background_owner;
GRANT SELECT(singleton,policy_id,policy_version) ON public.bot_notification_policy_current TO obsidian_exchange_bot_background_owner;
GRANT SELECT(order_id,user_id,rub_amount,currency,status,created_at,montera_invoice_id,receipt_sent_at,
 receipt_deadline,paid_btc_tx,updated_at) ON public.orders TO obsidian_exchange_bot_background_owner;
GRANT UPDATE(order_id) ON public.orders TO obsidian_exchange_bot_background_owner;
GRANT SELECT(id,order_id,status,session_token) ON public.payment_sessions TO obsidian_exchange_bot_background_owner;
GRANT SELECT(order_id) ON public.order_receipts TO obsidian_exchange_bot_background_owner;
GRANT SELECT(order_id,event),INSERT(order_id,event) ON public.sent_notifications TO obsidian_exchange_bot_background_owner;
GRANT SELECT(user_id) ON public.blocked_users TO obsidian_exchange_bot_background_owner;
GRANT SELECT(id),INSERT(code,discount_percent,max_uses,valid_until,is_active) ON public.promo_codes TO obsidian_exchange_bot_background_owner;
GRANT USAGE ON SEQUENCE public.promo_codes_id_seq TO obsidian_exchange_bot_background_owner;
GRANT INSERT(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
 ON public.bot_notification_jobs TO obsidian_exchange_bot_background_owner;
GRANT USAGE ON SEQUENCE public.bot_notification_jobs_id_seq TO obsidian_exchange_bot_background_owner;

CREATE FUNCTION public.bot_b59_queue_due_abandoned(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;r record;v_now timestamptz:=clock_timestamp();n integer:=0;lim integer;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_queue_limit'; END IF;lim=least(a_limit,1000);
 SELECT v.policy_id,v.version,v.max_attempts INTO p FROM public.bot_notification_policy_current c JOIN public.bot_notification_policy_versions v ON v.policy_id=c.policy_id
 WHERE c.singleton AND v.abandoned_enabled AND v_now>=v.effective_from AND v_now<v.effective_until;
 IF NOT FOUND THEN RETURN 0; END IF;
 FOR r IN SELECT o.order_id,o.user_id,o.rub_amount,o.currency,(SELECT ps.session_token FROM public.payment_sessions ps WHERE ps.order_id=o.order_id AND ps.status NOT IN('failed','expired') ORDER BY ps.id DESC LIMIT 1) session_token
  FROM public.orders o WHERE o.user_id>0 AND o.status='pending' AND o.created_at BETWEEN v_now-interval '13 minutes' AND v_now-interval '8 minutes'
  AND NOT EXISTS(SELECT 1 FROM public.order_receipts x WHERE x.order_id=o.order_id)
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s WHERE s.order_id=o.order_id AND s.event='pay_reminder')
  ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT lim LOOP
  INSERT INTO public.sent_notifications(order_id,event) VALUES(r.order_id,'pay_reminder') ON CONFLICT DO NOTHING;IF NOT FOUND THEN CONTINUE;END IF;
  INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
   VALUES('pay_reminder',r.order_id::text,jsonb_build_object('order_id',r.order_id,'user_id',r.user_id,'rub_amount',r.rub_amount,'currency',r.currency,'session_token',r.session_token,'policy_id',p.policy_id,'policy_version',p.version),r.user_id,p.policy_id,p.version,v_now,p.max_attempts);n=n+1;
 END LOOP;RETURN n;
END $$;

CREATE FUNCTION public.bot_b59_queue_due_montera(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;r record;v_admin bigint;v_now timestamptz:=clock_timestamp();n integer:=0;lim integer;v_payload jsonb;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_queue_limit'; END IF;lim=least(a_limit,1000);
 SELECT v.policy_id,v.version,v.max_attempts,v.admin_recipient_ids INTO p FROM public.bot_notification_policy_current c JOIN public.bot_notification_policy_versions v ON v.policy_id=c.policy_id
 WHERE c.singleton AND v.montera_enabled AND v_now>=v.effective_from AND v_now<v.effective_until;
 IF NOT FOUND THEN RETURN 0; END IF;
 FOR r IN SELECT o.order_id,o.user_id,o.montera_invoice_id,EXISTS(SELECT 1 FROM public.order_receipts x WHERE x.order_id=o.order_id) has_file
  FROM public.orders o WHERE o.user_id>0 AND o.status='pending' AND o.receipt_sent_at IS NULL
  AND o.receipt_deadline BETWEEN v_now+interval '8 minutes' AND v_now+interval '12 minutes'
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s WHERE s.order_id=o.order_id AND s.event='receipt_reminder')
  ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT lim LOOP
  INSERT INTO public.sent_notifications(order_id,event) VALUES(r.order_id,'receipt_reminder') ON CONFLICT DO NOTHING;IF NOT FOUND THEN CONTINUE;END IF;
  v_payload=jsonb_build_object('order_id',r.order_id,'user_id',r.user_id,'invoice_id',r.montera_invoice_id,'has_file',r.has_file,'policy_id',p.policy_id,'policy_version',p.version);
  INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
   VALUES('montera_customer',r.order_id::text,v_payload,r.user_id,p.policy_id,p.version,v_now,p.max_attempts);
  FOREACH v_admin IN ARRAY p.admin_recipient_ids LOOP
   INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
    VALUES('montera_admin',r.order_id::text||':'||v_admin::text,v_payload,v_admin,p.policy_id,p.version,v_now,p.max_attempts);
  END LOOP;n=n+1;
 END LOOP;RETURN n;
END $$;

CREATE FUNCTION public.bot_b59_queue_due_payout_delays(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;r record;v_now timestamptz:=clock_timestamp();n integer:=0;lim integer;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_queue_limit'; END IF;lim=least(a_limit,1000);
 SELECT v.policy_id,v.version,v.max_attempts,v.payout_warn_minutes INTO p FROM public.bot_notification_policy_current c JOIN public.bot_notification_policy_versions v ON v.policy_id=c.policy_id
 WHERE c.singleton AND v.payout_delay_enabled AND v_now>=v.effective_from AND v_now<v.effective_until;
 IF NOT FOUND THEN RETURN 0; END IF;
 FOR r IN SELECT o.order_id,o.user_id,o.currency FROM public.orders o WHERE o.user_id>0 AND o.status='paid'
  AND coalesce(o.paid_btc_tx,'')='' AND coalesce(o.updated_at,o.created_at)<=v_now-(p.payout_warn_minutes*interval '1 minute')
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s WHERE s.order_id=o.order_id AND s.event='payout_delayed')
  ORDER BY coalesce(o.updated_at,o.created_at),o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT lim LOOP
  INSERT INTO public.sent_notifications(order_id,event) VALUES(r.order_id,'payout_delayed') ON CONFLICT DO NOTHING;IF NOT FOUND THEN CONTINUE;END IF;
  INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
   VALUES('payout_delayed',r.order_id::text,jsonb_build_object('order_id',r.order_id,'user_id',r.user_id,'currency',r.currency,'policy_id',p.policy_id,'policy_version',p.version),r.user_id,p.policy_id,p.version,v_now,p.max_attempts);n=n+1;
 END LOOP;RETURN n;
END $$;

CREATE FUNCTION public.bot_b59_queue_due_recalls(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;r record;v_now timestamptz:=clock_timestamp();n integer:=0;lim integer;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_queue_limit'; END IF;lim=least(a_limit,1000);
 SELECT v.policy_id,v.version,v.max_attempts INTO p FROM public.bot_notification_policy_current c JOIN public.bot_notification_policy_versions v ON v.policy_id=c.policy_id
 WHERE c.singleton AND v.recall_enabled AND v_now>=v.effective_from AND v_now<v.effective_until;
 IF NOT FOUND THEN RETURN 0; END IF;
 FOR r IN SELECT DISTINCT o.user_id FROM public.orders o WHERE o.user_id>0 AND o.status='sent'
  AND NOT EXISTS(SELECT 1 FROM public.orders recent WHERE recent.user_id=o.user_id AND recent.created_at>v_now-interval '14 days')
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s WHERE s.order_id=o.user_id AND s.event='recall')
  ORDER BY o.user_id LIMIT lim LOOP
  INSERT INTO public.sent_notifications(order_id,event) VALUES(r.user_id,'recall') ON CONFLICT DO NOTHING;IF NOT FOUND THEN CONTINUE;END IF;
  INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
   VALUES('recall',r.user_id::text,jsonb_build_object('user_id',r.user_id,'policy_id',p.policy_id,'policy_version',p.version),r.user_id,p.policy_id,p.version,v_now,p.max_attempts);n=n+1;
 END LOOP;RETURN n;
END $$;

CREATE FUNCTION public.bot_b59_queue_due_winbacks(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;r record;v_now timestamptz:=clock_timestamp();n integer:=0;lim integer;v_code text;v_promo bigint;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_queue_limit'; END IF;lim=least(a_limit,1000);
 SELECT v.policy_id,v.version,v.max_attempts,v.winback_discount,v.winback_valid_hours INTO p FROM public.bot_notification_policy_current c JOIN public.bot_notification_policy_versions v ON v.policy_id=c.policy_id
 WHERE c.singleton AND v.winback_enabled AND v_now>=v.effective_from AND v_now<v.effective_until;
 IF NOT FOUND THEN RETURN 0; END IF;
 FOR r IN SELECT max(o.order_id) order_id,o.user_id FROM public.orders o WHERE o.user_id>0 AND o.status='expired'
  AND o.updated_at BETWEEN v_now-interval '48 hours' AND v_now-interval '1 hour'
  AND NOT EXISTS(SELECT 1 FROM public.orders paid WHERE paid.user_id=o.user_id AND paid.status IN('paid','sent'))
  AND NOT EXISTS(SELECT 1 FROM public.order_receipts x JOIN public.orders ro ON ro.order_id=x.order_id WHERE ro.user_id=o.user_id)
  AND NOT EXISTS(SELECT 1 FROM public.sent_notifications s JOIN public.orders mo ON mo.order_id=s.order_id WHERE mo.user_id=o.user_id AND s.event='winback_promo')
  AND NOT EXISTS(SELECT 1 FROM public.blocked_users b WHERE b.user_id=o.user_id)
  GROUP BY o.user_id ORDER BY o.user_id LIMIT lim LOOP
  INSERT INTO public.sent_notifications(order_id,event) VALUES(r.order_id,'winback_promo') ON CONFLICT DO NOTHING;IF NOT FOUND THEN CONTINUE;END IF;
  v_code='BACK'||trunc(p.winback_discount)::text||'-'||upper(substr(replace(pg_catalog.gen_random_uuid()::text,'-',''),1,8));
  INSERT INTO public.promo_codes(code,discount_percent,max_uses,valid_until,is_active)
   VALUES(v_code,p.winback_discount,1,v_now+(p.winback_valid_hours*interval '1 hour'),true) RETURNING id INTO v_promo;
  INSERT INTO public.bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)
   VALUES('winback_promo',r.order_id::text,jsonb_build_object('order_id',r.order_id,'user_id',r.user_id,'code',v_code,'code_id',v_promo,'discount',p.winback_discount,'valid_hours',p.winback_valid_hours,'valid_until',v_now+(p.winback_valid_hours*interval '1 hour'),'policy_id',p.policy_id,'policy_version',p.version),r.user_id,p.policy_id,p.version,v_now,p.max_attempts);n=n+1;
 END LOOP;RETURN n;
END $$;

ALTER FUNCTION public.bot_b59_policy_guard() OWNER TO obsidian_exchange_bot_background_owner;
ALTER FUNCTION public.bot_b59_queue_due_abandoned(integer) OWNER TO obsidian_exchange_bot_background_owner;
ALTER FUNCTION public.bot_b59_queue_due_montera(integer) OWNER TO obsidian_exchange_bot_background_owner;
ALTER FUNCTION public.bot_b59_queue_due_payout_delays(integer) OWNER TO obsidian_exchange_bot_background_owner;
ALTER FUNCTION public.bot_b59_queue_due_recalls(integer) OWNER TO obsidian_exchange_bot_background_owner;
ALTER FUNCTION public.bot_b59_queue_due_winbacks(integer) OWNER TO obsidian_exchange_bot_background_owner;
REVOKE ALL ON FUNCTION public.bot_b59_policy_guard(),public.bot_b59_queue_due_abandoned(integer),
 public.bot_b59_queue_due_montera(integer),public.bot_b59_queue_due_payout_delays(integer),
 public.bot_b59_queue_due_recalls(integer),public.bot_b59_queue_due_winbacks(integer)
 FROM PUBLIC,obsidian_exchange_bot;
GRANT EXECUTE ON FUNCTION public.bot_b59_queue_due_abandoned(integer),
 public.bot_b59_queue_due_montera(integer),public.bot_b59_queue_due_payout_delays(integer),
 public.bot_b59_queue_due_recalls(integer),public.bot_b59_queue_due_winbacks(integer)
 TO obsidian_exchange_bot_background;
REVOKE EXECUTE ON FUNCTION public.bot_b5_queue_due_abandoned(timestamptz,integer),
 public.bot_b5_queue_due_montera(timestamptz,integer),
 public.bot_b5_queue_due_payout_delays(integer,timestamptz,integer),
 public.bot_b5_queue_due_recalls(timestamptz,integer),
 public.bot_b5_queue_due_winbacks(numeric,integer,timestamptz,integer)
 FROM obsidian_exchange_bot;
COMMIT;
