-- E0.3 PROPOSAL ONLY. Truthful client correlation and ACCEPTED reconciliation.
BEGIN;
DO $$ BEGIN
 IF to_regrole('obsidian_exchange_bot_notification_reconciler_owner') IS NULL
 OR to_regrole('obsidian_exchange_bot_notification_reconciler') IS NULL THEN
  RAISE EXCEPTION 'b62_reconciler_roles_missing';END IF;
 IF EXISTS(SELECT 1 FROM public.bot_notification_delivery_evidence) THEN
  RAISE EXCEPTION 'existing_delivery_evidence_requires_expand_backfill';END IF;
END$$;

ALTER TABLE public.bot_notification_submit_authorizations
 ADD CONSTRAINT bot_notification_submit_authorization_tuple_unique
 UNIQUE(job_id,attempt_token,client_correlation_id);
ALTER TABLE public.bot_notification_delivery_evidence
 ADD COLUMN client_correlation_id uuid NOT NULL,
 ADD CONSTRAINT bot_notification_evidence_submit_authorization_fk
  FOREIGN KEY(job_id,attempt_token,client_correlation_id)
  REFERENCES public.bot_notification_submit_authorizations(job_id,attempt_token,client_correlation_id)
  ON DELETE RESTRICT;
DO $$ DECLARE c text;v_count integer;BEGIN
 SELECT count(*),min(conname) INTO v_count,c FROM pg_constraint
 WHERE conrelid='public.bot_notification_delivery_evidence'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%outcome%ACCEPTED%provider_request_id%';
 IF v_count<>1 THEN RAISE EXCEPTION 'b62_old_evidence_outcome_constraint_count:%',v_count;END IF;
 EXECUTE format('ALTER TABLE public.bot_notification_delivery_evidence DROP CONSTRAINT %I',c);
END$$;
ALTER TABLE public.bot_notification_delivery_evidence ADD CONSTRAINT bot_notification_evidence_outcome_v62_check CHECK(
 (outcome='ACCEPTED' AND reason_code IS NULL AND provider_message_id IS NOT NULL AND provider_request_id IS NULL)
 OR (outcome='NOT_STARTED' AND reason_code='PROVIDER_REJECTED_PRE_SUBMIT' AND provider_message_id IS NULL AND provider_request_id IS NULL)
 OR (outcome='UNCERTAIN' AND reason_code IN('TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN'))
);

CREATE TABLE public.bot_notification_accepted_reconciliations(
 reconciliation_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 job_id bigint UNIQUE NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 attempt_token uuid UNIQUE NOT NULL,
 evidence_id uuid UNIQUE NOT NULL REFERENCES public.bot_notification_delivery_evidence(evidence_id) ON DELETE RESTRICT,
 reconciled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 reconciler_principal text NOT NULL CHECK(length(reconciler_principal) BETWEEN 1 AND 128)
);
CREATE FUNCTION public.bot_b62_append_only_guard() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog AS $$BEGIN RAISE EXCEPTION 'b62_append_only';END$$;
CREATE TRIGGER bot_b62_reconciliation_immutable BEFORE UPDATE OR DELETE
 ON public.bot_notification_accepted_reconciliations FOR EACH ROW EXECUTE FUNCTION public.bot_b62_append_only_guard();

CREATE FUNCTION public.bot_b62_transport_record_evidence(
 a_job_id bigint,a_token uuid,a_client_correlation_id uuid,a_outcome text,a_provider_request_id text,
 a_provider_message_id text,a_reason_code text,a_response_sha256 text,a_observed_at timestamptz)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_existing record;v_evidence uuid;v_now timestamptz:=clock_timestamp();
BEGIN
 IF a_job_id IS NULL OR a_job_id<=0 OR a_token IS NULL OR a_client_correlation_id IS NULL
 OR a_response_sha256!~'^[0-9a-f]{64}$' OR a_observed_at IS NULL
 OR a_observed_at<v_now-interval '15 minutes' OR a_observed_at>v_now+interval '1 minute'
 THEN RAISE EXCEPTION 'invalid_delivery_evidence';END IF;
 SELECT a.attempt_no,a.recipient_id,a.claimed_at,a.terminal_evidence_id INTO v
 FROM public.bot_notification_delivery_attempts a
 JOIN public.bot_notification_jobs j ON j.id=a.job_id
 JOIN public.bot_notification_submit_authorizations s ON s.job_id=a.job_id AND s.attempt_token=a.attempt_token
 WHERE a.job_id=a_job_id AND a.attempt_token=a_token
 AND s.client_correlation_id=a_client_correlation_id
 AND j.state='sending' AND j.attempt_token=a_token FOR UPDATE OF a;
 IF NOT FOUND THEN RETURN NULL;END IF;
 IF a_observed_at<v.claimed_at-interval '1 second' THEN RAISE EXCEPTION 'evidence_precedes_attempt';END IF;
 IF v.terminal_evidence_id IS NOT NULL THEN
  SELECT * INTO v_existing FROM public.bot_notification_delivery_evidence WHERE evidence_id=v.terminal_evidence_id;
  IF v_existing.client_correlation_id=a_client_correlation_id AND v_existing.outcome=a_outcome
   AND v_existing.provider_request_id IS NOT DISTINCT FROM a_provider_request_id
   AND v_existing.provider_message_id IS NOT DISTINCT FROM a_provider_message_id
   AND v_existing.reason_code IS NOT DISTINCT FROM a_reason_code
   AND v_existing.response_sha256=a_response_sha256 AND v_existing.observed_at=a_observed_at
  THEN RETURN v.terminal_evidence_id;END IF;
  RAISE EXCEPTION 'conflicting_delivery_evidence';
 END IF;
 INSERT INTO public.bot_notification_delivery_evidence(job_id,attempt_no,attempt_token,recipient_id,
  client_correlation_id,outcome,provider,channel,provider_request_id,provider_message_id,reason_code,
  response_sha256,observed_at,recorder_principal)
 VALUES(a_job_id,v.attempt_no,a_token,v.recipient_id,a_client_correlation_id,a_outcome,'TELEGRAM','BOT_API',
  a_provider_request_id,a_provider_message_id,a_reason_code,a_response_sha256,a_observed_at,session_user)
 RETURNING evidence_id INTO v_evidence;
 UPDATE public.bot_notification_delivery_attempts SET terminal_outcome=a_outcome,terminal_evidence_id=v_evidence
 WHERE job_id=a_job_id AND attempt_no=v.attempt_no AND terminal_evidence_id IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'terminal_evidence_assignment_lost';END IF;RETURN v_evidence;
END$$;

CREATE FUNCTION public.bot_b62_consume_accepted(a_job_id bigint,a_token uuid,a_evidence_id uuid)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e record;j record;
BEGIN
 SELECT id,state,attempt_token INTO j FROM public.bot_notification_jobs WHERE id=a_job_id FOR UPDATE;
 IF NOT FOUND OR j.attempt_token<>a_token THEN RETURN 'NOOP';END IF;
 SELECT x.evidence_id,x.outcome,x.consumed_transition,a.terminal_evidence_id INTO e
 FROM public.bot_notification_delivery_attempts a JOIN public.bot_notification_delivery_evidence x
  ON x.evidence_id=a.terminal_evidence_id
 WHERE a.job_id=a_job_id AND a.attempt_token=a_token AND x.evidence_id=a_evidence_id FOR UPDATE OF x;
 IF NOT FOUND OR e.outcome<>'ACCEPTED' THEN RETURN 'NOOP';END IF;
 IF j.state='sent' AND e.consumed_transition='SENT' THEN RETURN 'ALREADY_SENT';END IF;
 IF j.state<>'sending' OR e.consumed_transition IS NOT NULL THEN RETURN 'NOOP';END IF;
 UPDATE public.bot_notification_jobs SET state='sent',sent_at=clock_timestamp(),updated_at=clock_timestamp()
  WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;
 IF NOT FOUND THEN RETURN 'NOOP';END IF;
 UPDATE public.bot_notification_delivery_evidence SET consumed_at=clock_timestamp(),consumed_transition='SENT'
  WHERE evidence_id=a_evidence_id AND consumed_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'accepted_evidence_consume_lost';END IF;
 INSERT INTO public.bot_notification_accepted_reconciliations(job_id,attempt_token,evidence_id,reconciler_principal)
 VALUES(a_job_id,a_token,a_evidence_id,session_user);RETURN 'SENT';
END$$;

CREATE FUNCTION public.bot_b62_reconcile_accepted(a_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e record;n integer:=0;lim integer;v_result text;
BEGIN
 IF a_limit IS NULL OR a_limit<1 THEN RAISE EXCEPTION 'invalid_reconcile_limit';END IF;lim=least(a_limit,1000);
 FOR e IN SELECT x.evidence_id,x.job_id,x.attempt_token FROM public.bot_notification_delivery_evidence x
  JOIN public.bot_notification_delivery_attempts a ON a.terminal_evidence_id=x.evidence_id
  JOIN public.bot_notification_jobs j ON j.id=x.job_id AND j.attempt_token=x.attempt_token
  WHERE x.outcome='ACCEPTED' AND x.consumed_at IS NULL AND j.state='sending'
  ORDER BY x.recorded_at,x.evidence_id LIMIT lim LOOP
  v_result=public.bot_b62_consume_accepted(e.job_id,e.attempt_token,e.evidence_id);
  IF v_result='SENT' THEN n=n+1;END IF;
 END LOOP;RETURN n;
END$$;

GRANT USAGE ON SCHEMA public TO obsidian_exchange_bot_notification_reconciler_owner,
 obsidian_exchange_bot_notification_reconciler;
GRANT SELECT(id,state,attempt_token),UPDATE(state,sent_at,updated_at) ON public.bot_notification_jobs
 TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT SELECT ON public.bot_notification_delivery_attempts TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT SELECT,UPDATE(consumed_at,consumed_transition) ON public.bot_notification_delivery_evidence
 TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT INSERT ON public.bot_notification_accepted_reconciliations TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT SELECT ON public.bot_notification_submit_authorizations TO obsidian_exchange_bot_transport_owner;
GRANT INSERT(client_correlation_id) ON public.bot_notification_delivery_evidence TO obsidian_exchange_bot_transport_owner;
ALTER FUNCTION public.bot_b62_append_only_guard() OWNER TO obsidian_exchange_bot_notification_reconciler_owner;
ALTER FUNCTION public.bot_b62_transport_record_evidence(bigint,uuid,uuid,text,text,text,text,text,timestamptz)
 OWNER TO obsidian_exchange_bot_transport_owner;
ALTER FUNCTION public.bot_b62_consume_accepted(bigint,uuid,uuid) OWNER TO obsidian_exchange_bot_notification_reconciler_owner;
ALTER FUNCTION public.bot_b62_reconcile_accepted(integer) OWNER TO obsidian_exchange_bot_notification_reconciler_owner;
REVOKE ALL ON FUNCTION public.bot_b62_append_only_guard(),
 public.bot_b62_transport_record_evidence(bigint,uuid,uuid,text,text,text,text,text,timestamptz),
 public.bot_b62_consume_accepted(bigint,uuid,uuid),
 public.bot_b62_reconcile_accepted(integer)
 FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_background,obsidian_exchange_bot_delivery,
 obsidian_exchange_bot_transport,obsidian_exchange_bot_policy_approver,obsidian_exchange_bot_reconciler;
GRANT EXECUTE ON FUNCTION public.bot_b62_transport_record_evidence(bigint,uuid,uuid,text,text,text,text,text,timestamptz)
 TO obsidian_exchange_bot_transport;
GRANT EXECUTE ON FUNCTION public.bot_b62_reconcile_accepted(integer)
 TO obsidian_exchange_bot_notification_reconciler;
GRANT EXECUTE ON FUNCTION public.bot_b62_consume_accepted(bigint,uuid,uuid)
 TO obsidian_exchange_bot_delivery,obsidian_exchange_bot_notification_reconciler;
REVOKE EXECUTE ON FUNCTION public.bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamptz)
 FROM obsidian_exchange_bot_transport;
REVOKE EXECUTE ON FUNCTION public.bot_b53_delivery_mark_sent(bigint,uuid,uuid)
 FROM obsidian_exchange_bot_delivery;
COMMIT;
