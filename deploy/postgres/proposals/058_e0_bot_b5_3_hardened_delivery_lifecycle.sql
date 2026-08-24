-- E0.3 PROPOSAL ONLY. Hardened B5.3 delivery lifecycle for disposable rehearsal.
-- Roles and credentials are provisioned separately; this file never creates a LOGIN.
BEGIN;
DO $$ BEGIN
 IF to_regrole('obsidian_exchange_bot_delivery_owner') IS NULL
    OR to_regrole('obsidian_exchange_bot_delivery') IS NULL
    OR to_regrole('obsidian_exchange_bot_transport_owner') IS NULL
    OR to_regrole('obsidian_exchange_bot_transport') IS NULL THEN
  RAISE EXCEPTION 'b53_delivery_roles_missing';
 END IF;
 IF EXISTS(SELECT 1 FROM public.bot_notification_jobs WHERE state<>'pending' OR attempts>=5 OR kind='montera_admin') THEN
  RAISE EXCEPTION 'legacy_jobs_require_expand_backfill_or_manual_reconciliation';
 END IF;
END $$;

ALTER TABLE public.bot_notification_jobs
 ADD COLUMN recipient_id bigint,
 ADD COLUMN attempt_token uuid,
 ADD COLUMN manual_reason_code text,
 ADD COLUMN max_attempts smallint NOT NULL DEFAULT 5;

UPDATE public.bot_notification_jobs
 SET recipient_id=(payload->>'user_id')::bigint
 WHERE recipient_id IS NULL AND kind<>'montera_admin'
   AND payload ? 'user_id' AND (payload->>'user_id') ~ '^[1-9][0-9]*$';

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.bot_notification_jobs WHERE recipient_id IS NULL) THEN
  RAISE EXCEPTION 'legacy_recipient_snapshot_required';
 END IF;
END $$;

ALTER TABLE public.bot_notification_jobs
 ALTER COLUMN recipient_id SET NOT NULL,
 DROP CONSTRAINT bot_notification_jobs_state_check,
 ADD CONSTRAINT bot_notification_jobs_state_check
  CHECK(state IN('pending','sending','sent','manual')),
 ADD CONSTRAINT bot_notification_jobs_recipient_check CHECK(recipient_id>0),
 ADD CONSTRAINT bot_notification_jobs_max_attempts_check CHECK(max_attempts BETWEEN 1 AND 20),
 ADD CONSTRAINT bot_notification_jobs_lifecycle_check CHECK(
  (state='pending' AND attempts<max_attempts AND attempt_token IS NULL AND claimed_at IS NULL AND sent_at IS NULL AND manual_reason_code IS NULL)
  OR (state='sending' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NULL AND manual_reason_code IS NULL AND attempts>=1)
  OR (state='sent' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NOT NULL AND manual_reason_code IS NULL AND attempts>=1)
  OR (state='manual' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NULL AND manual_reason_code IS NOT NULL AND attempts>=1)
 );

CREATE TABLE public.bot_notification_delivery_attempts(
 job_id bigint NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 attempt_no integer NOT NULL CHECK(attempt_no>0),
 attempt_token uuid NOT NULL,
 recipient_id bigint NOT NULL CHECK(recipient_id>0),
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
 claimed_at timestamptz NOT NULL,
 claimant_principal text NOT NULL CHECK(length(claimant_principal) BETWEEN 1 AND 128),
 terminal_outcome text CHECK(terminal_outcome IN('ACCEPTED','NOT_STARTED','UNCERTAIN')),
 terminal_evidence_id uuid,
 PRIMARY KEY(job_id,attempt_no),
 UNIQUE(attempt_token),
 UNIQUE(job_id,attempt_token,recipient_id)
);

CREATE TABLE public.bot_notification_delivery_evidence(
 evidence_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 job_id bigint NOT NULL,
 attempt_no integer NOT NULL,
 attempt_token uuid NOT NULL,
 recipient_id bigint NOT NULL CHECK(recipient_id>0),
 provider text NOT NULL CHECK(provider='TELEGRAM'),
 channel text NOT NULL CHECK(channel='BOT_API'),
 outcome text NOT NULL CHECK(outcome IN('ACCEPTED','NOT_STARTED','UNCERTAIN')),
 provider_request_id text,
 provider_message_id text,
 reason_code text,
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 observed_at timestamptz NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 recorder_principal text NOT NULL CHECK(length(recorder_principal) BETWEEN 1 AND 128),
 consumed_at timestamptz,
 consumed_transition text CHECK(consumed_transition IN('SENT','RETRY','MANUAL')),
 FOREIGN KEY(job_id,attempt_no) REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_no) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,attempt_token,recipient_id) REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_token,recipient_id) ON DELETE RESTRICT,
 UNIQUE(job_id,attempt_token,evidence_id),
 CHECK(provider_request_id IS NULL OR length(provider_request_id) BETWEEN 1 AND 200),
 CHECK(provider_message_id IS NULL OR length(provider_message_id) BETWEEN 1 AND 200),
 CHECK(reason_code IS NULL OR reason_code IN('PROVIDER_REJECTED_PRE_SUBMIT','TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN')),
 CHECK(
  (outcome='ACCEPTED' AND reason_code IS NULL AND provider_message_id IS NOT NULL AND provider_request_id IS NOT NULL)
  OR (outcome='NOT_STARTED' AND reason_code='PROVIDER_REJECTED_PRE_SUBMIT' AND provider_message_id IS NULL AND provider_request_id IS NULL)
  OR (outcome='UNCERTAIN' AND reason_code IN('TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN'))
 ),
 CHECK((consumed_at IS NULL)=(consumed_transition IS NULL))
);
ALTER TABLE public.bot_notification_delivery_attempts ADD CONSTRAINT bot_notification_attempt_terminal_evidence_fk
 FOREIGN KEY(terminal_evidence_id) REFERENCES public.bot_notification_delivery_evidence(evidence_id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX bot_notification_evidence_provider_message_unique
 ON public.bot_notification_delivery_evidence(provider,channel,provider_message_id)
 WHERE provider_message_id IS NOT NULL;
CREATE UNIQUE INDEX bot_notification_evidence_provider_request_unique
 ON public.bot_notification_delivery_evidence(provider,channel,provider_request_id)
 WHERE provider_request_id IS NOT NULL;

GRANT USAGE ON SCHEMA public TO obsidian_exchange_bot_delivery_owner,
 obsidian_exchange_bot_delivery,obsidian_exchange_bot_transport_owner,
 obsidian_exchange_bot_transport;
GRANT SELECT(id,kind,dedupe_key,payload,state,attempts,recipient_id,attempt_token,max_attempts),
 UPDATE(state,attempts,claimed_at,sent_at,updated_at,attempt_token,manual_reason_code)
 ON public.bot_notification_jobs TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT,INSERT ON public.bot_notification_delivery_attempts TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT,UPDATE(consumed_at,consumed_transition) ON public.bot_notification_delivery_evidence TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT(id,state,attempts,recipient_id,attempt_token) ON public.bot_notification_jobs TO obsidian_exchange_bot_transport_owner;
GRANT SELECT,UPDATE(terminal_outcome,terminal_evidence_id) ON public.bot_notification_delivery_attempts TO obsidian_exchange_bot_transport_owner;
GRANT INSERT,SELECT ON public.bot_notification_delivery_evidence TO obsidian_exchange_bot_transport_owner;

CREATE FUNCTION public.bot_b53_delivery_claim(a_kind text)
RETURNS TABLE(id bigint,kind text,dedupe_key text,payload jsonb,attempts integer,recipient_id bigint,attempt_token uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_token uuid;v_claimed timestamptz;
BEGIN
 IF a_kind IS NOT NULL AND a_kind NOT IN('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo') THEN RAISE EXCEPTION 'invalid_notification_kind'; END IF;
 SELECT j.id,j.kind,j.dedupe_key,j.payload,j.attempts,j.recipient_id INTO v
 FROM public.bot_notification_jobs j WHERE j.state='pending' AND j.attempts<j.max_attempts
 AND (a_kind IS NULL OR j.kind=a_kind) ORDER BY j.attempts,j.id FOR UPDATE SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN; END IF;
 v_token=pg_catalog.gen_random_uuid();v_claimed=clock_timestamp();
 UPDATE public.bot_notification_jobs j SET state='sending',attempts=j.attempts+1,
  claimed_at=v_claimed,updated_at=v_claimed,attempt_token=v_token,manual_reason_code=NULL
  WHERE j.id=v.id AND j.state='pending';
 IF NOT FOUND THEN RAISE EXCEPTION 'notification_claim_lost'; END IF;
 INSERT INTO public.bot_notification_delivery_attempts(job_id,attempt_no,attempt_token,recipient_id,payload_sha256,claimed_at,claimant_principal)
 VALUES(v.id,v.attempts+1,v_token,v.recipient_id,
  encode(pg_catalog.sha256(pg_catalog.convert_to(v.payload::text,'UTF8')),'hex'),v_claimed,session_user);
 RETURN QUERY SELECT v.id,v.kind,v.dedupe_key,v.payload,v.attempts+1,v.recipient_id,v_token;
END $$;

CREATE FUNCTION public.bot_b53_transport_record_evidence(
 a_job_id bigint,a_token uuid,a_outcome text,a_provider_request_id text,
 a_provider_message_id text,a_reason_code text,a_response_sha256 text,a_observed_at timestamptz)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_existing record;v_evidence uuid;
BEGIN
 IF a_job_id IS NULL OR a_job_id<=0 OR a_token IS NULL OR a_response_sha256 !~ '^[0-9a-f]{64}$'
 OR a_observed_at IS NULL OR a_observed_at<clock_timestamp()-interval '15 minutes'
 OR a_observed_at>clock_timestamp()+interval '1 minute' THEN RAISE EXCEPTION 'invalid_delivery_evidence'; END IF;
 SELECT a.attempt_no,a.recipient_id,a.claimed_at,a.terminal_evidence_id INTO v
 FROM public.bot_notification_delivery_attempts a JOIN public.bot_notification_jobs j ON j.id=a.job_id
 WHERE a.job_id=a_job_id AND a.attempt_token=a_token AND j.state='sending' AND j.attempt_token=a_token
 FOR UPDATE OF a;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF a_observed_at<v.claimed_at-interval '1 second' THEN RAISE EXCEPTION 'evidence_precedes_attempt'; END IF;
 IF v.terminal_evidence_id IS NOT NULL THEN
  SELECT * INTO v_existing FROM public.bot_notification_delivery_evidence e WHERE e.evidence_id=v.terminal_evidence_id;
  IF v_existing.outcome=a_outcome AND v_existing.provider_request_id IS NOT DISTINCT FROM a_provider_request_id
   AND v_existing.provider_message_id IS NOT DISTINCT FROM a_provider_message_id
   AND v_existing.reason_code IS NOT DISTINCT FROM a_reason_code
   AND v_existing.response_sha256=a_response_sha256 AND v_existing.observed_at=a_observed_at THEN
   RETURN v.terminal_evidence_id;
  END IF;
  RAISE EXCEPTION 'conflicting_delivery_evidence';
 END IF;
 INSERT INTO public.bot_notification_delivery_evidence(job_id,attempt_no,attempt_token,recipient_id,outcome,
  provider,channel,provider_request_id,provider_message_id,reason_code,response_sha256,observed_at,recorder_principal)
 VALUES(a_job_id,v.attempt_no,a_token,v.recipient_id,a_outcome,'TELEGRAM','BOT_API',a_provider_request_id,a_provider_message_id,
  a_reason_code,a_response_sha256,a_observed_at,session_user) RETURNING evidence_id INTO v_evidence;
 UPDATE public.bot_notification_delivery_attempts SET terminal_outcome=a_outcome,terminal_evidence_id=v_evidence
 WHERE job_id=a_job_id AND attempt_no=v.attempt_no AND terminal_evidence_id IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'terminal_evidence_assignment_lost'; END IF;
 RETURN v_evidence;
END $$;

CREATE FUNCTION public.bot_b53_delivery_mark_sent(a_job_id bigint,a_token uuid,a_evidence_id uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;
BEGIN
 SELECT e.evidence_id INTO v FROM public.bot_notification_delivery_evidence e
 JOIN public.bot_notification_delivery_attempts a ON a.job_id=e.job_id AND a.attempt_no=e.attempt_no
 WHERE e.evidence_id=a_evidence_id AND e.job_id=a_job_id AND e.attempt_token=a_token
 AND a.terminal_evidence_id=e.evidence_id AND e.outcome='ACCEPTED' AND e.consumed_at IS NULL FOR UPDATE OF e;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE public.bot_notification_jobs SET state='sent',sent_at=clock_timestamp(),updated_at=clock_timestamp()
 WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE public.bot_notification_delivery_evidence SET consumed_at=clock_timestamp(),consumed_transition='SENT'
 WHERE evidence_id=a_evidence_id AND consumed_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'evidence_consume_lost'; END IF;RETURN true;
END $$;

CREATE FUNCTION public.bot_b53_delivery_retry_pre_submit(a_job_id bigint,a_token uuid,a_evidence_id uuid)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_transition text;
BEGIN
 SELECT e.evidence_id,j.attempts,j.max_attempts INTO v FROM public.bot_notification_delivery_evidence e
 JOIN public.bot_notification_jobs j ON j.id=e.job_id
 JOIN public.bot_notification_delivery_attempts a ON a.job_id=e.job_id AND a.attempt_no=e.attempt_no
 WHERE e.evidence_id=a_evidence_id AND e.job_id=a_job_id AND e.attempt_token=a_token
 AND a.terminal_evidence_id=e.evidence_id AND e.outcome='NOT_STARTED' AND e.consumed_at IS NULL
 AND j.state='sending' AND j.attempt_token=a_token
 FOR UPDATE OF e,j;
 IF NOT FOUND THEN RETURN 'NOOP'; END IF;
 IF v.attempts>=v.max_attempts THEN
  UPDATE public.bot_notification_jobs SET state='manual',manual_reason_code='MAX_ATTEMPTS',updated_at=clock_timestamp()
  WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;v_transition='MANUAL';
 ELSE
  UPDATE public.bot_notification_jobs SET state='pending',claimed_at=NULL,attempt_token=NULL,updated_at=clock_timestamp()
  WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;v_transition='RETRY';
 END IF;
 UPDATE public.bot_notification_delivery_evidence SET consumed_at=clock_timestamp(),consumed_transition=v_transition
 WHERE evidence_id=a_evidence_id AND consumed_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'evidence_consume_lost'; END IF;RETURN v_transition;
END $$;

CREATE FUNCTION public.bot_b53_delivery_mark_manual(a_job_id bigint,a_token uuid,a_evidence_id uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;
BEGIN
 SELECT e.evidence_id,e.reason_code INTO v FROM public.bot_notification_delivery_evidence e
 JOIN public.bot_notification_delivery_attempts a ON a.job_id=e.job_id AND a.attempt_no=e.attempt_no
 WHERE e.evidence_id=a_evidence_id AND e.job_id=a_job_id AND e.attempt_token=a_token
 AND a.terminal_evidence_id=e.evidence_id AND e.outcome='UNCERTAIN' AND e.consumed_at IS NULL FOR UPDATE OF e;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE public.bot_notification_jobs SET state='manual',manual_reason_code=v.reason_code,updated_at=clock_timestamp()
 WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE public.bot_notification_delivery_evidence SET consumed_at=clock_timestamp(),consumed_transition='MANUAL'
 WHERE evidence_id=a_evidence_id AND consumed_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'evidence_consume_lost'; END IF;RETURN true;
END $$;

ALTER FUNCTION public.bot_b53_delivery_claim(text) OWNER TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamptz) OWNER TO obsidian_exchange_bot_transport_owner;
ALTER FUNCTION public.bot_b53_delivery_mark_sent(bigint,uuid,uuid) OWNER TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b53_delivery_retry_pre_submit(bigint,uuid,uuid) OWNER TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b53_delivery_mark_manual(bigint,uuid,uuid) OWNER TO obsidian_exchange_bot_delivery_owner;
REVOKE ALL ON FUNCTION public.bot_b53_delivery_claim(text),
 public.bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamptz),
 public.bot_b53_delivery_mark_sent(bigint,uuid,uuid),
 public.bot_b53_delivery_retry_pre_submit(bigint,uuid,uuid),
 public.bot_b53_delivery_mark_manual(bigint,uuid,uuid) FROM PUBLIC,obsidian_exchange_bot;
GRANT EXECUTE ON FUNCTION public.bot_b53_delivery_claim(text),
 public.bot_b53_delivery_mark_sent(bigint,uuid,uuid),
 public.bot_b53_delivery_retry_pre_submit(bigint,uuid,uuid),
 public.bot_b53_delivery_mark_manual(bigint,uuid,uuid) TO obsidian_exchange_bot_delivery;
GRANT EXECUTE ON FUNCTION public.bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamptz)
 TO obsidian_exchange_bot_transport;

DO $$ BEGIN
 IF to_regprocedure('public.bot_b5_notification_claim(text)') IS NOT NULL THEN
  REVOKE EXECUTE ON FUNCTION public.bot_b5_notification_claim(text),
   public.bot_b5_notification_mark_sent(bigint),public.bot_b5_notification_retry(bigint)
   FROM obsidian_exchange_bot;
 END IF;
END $$;
COMMIT;
