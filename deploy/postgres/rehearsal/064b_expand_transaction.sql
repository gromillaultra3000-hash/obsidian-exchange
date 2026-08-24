-- REHEARSAL ONLY: E0.3/B5.3/064B EXPAND on a disposable PostgreSQL clone.
-- NOT A PRODUCTION MIGRATION. No roles, credentials, grants, backfill, producer
-- fence, dispatcher fence, state cutover, or customer-data mutation belongs here.
-- The old runtime remains valid because every job-side v2 column is nullable and
-- the legacy state CHECK is retained unchanged.

BEGIN;

ALTER TABLE public.bot_notification_jobs
  ADD COLUMN lifecycle_version smallint,
  ADD COLUMN recipient_id bigint,
  ADD COLUMN attempt_token uuid,
  ADD COLUMN manual_reason_code text,
  ADD COLUMN max_attempts smallint;

ALTER TABLE public.bot_notification_jobs
  ADD CONSTRAINT bot_notification_jobs_lifecycle_version_v2_check
    CHECK (lifecycle_version IS NULL OR lifecycle_version = 2) NOT VALID,
  ADD CONSTRAINT bot_notification_jobs_v2_shape_check
    CHECK (
      lifecycle_version IS NULL
      OR (
        recipient_id IS NOT NULL
        AND recipient_id > 0
        AND max_attempts BETWEEN 1 AND 20
        AND (
          (state = 'pending' AND attempt_token IS NULL AND claimed_at IS NULL
             AND sent_at IS NULL AND manual_reason_code IS NULL)
          OR (state = 'sending' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL
             AND sent_at IS NULL AND manual_reason_code IS NULL AND attempts >= 1)
          OR (state = 'sent' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL
             AND sent_at IS NOT NULL AND manual_reason_code IS NULL AND attempts >= 1)
        )
      )
    ) NOT VALID;

CREATE TABLE public.bot_notification_delivery_attempts(
  job_id bigint NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  attempt_token uuid NOT NULL,
  recipient_id bigint NOT NULL CHECK (recipient_id > 0),
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  claimed_at timestamptz NOT NULL,
  claimant_principal text NOT NULL CHECK (length(claimant_principal) BETWEEN 1 AND 128),
  terminal_outcome text CHECK (terminal_outcome IN ('ACCEPTED','NOT_STARTED','UNCERTAIN')),
  terminal_evidence_id uuid,
  PRIMARY KEY (job_id,attempt_no),
  UNIQUE (attempt_token),
  UNIQUE (job_id,attempt_token,recipient_id)
);

CREATE TABLE public.bot_notification_delivery_evidence(
  evidence_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
  job_id bigint NOT NULL,
  attempt_no integer NOT NULL,
  attempt_token uuid NOT NULL,
  recipient_id bigint NOT NULL CHECK (recipient_id > 0),
  provider text NOT NULL CHECK (provider = 'TELEGRAM'),
  channel text NOT NULL CHECK (channel = 'BOT_API'),
  outcome text NOT NULL CHECK (outcome IN ('ACCEPTED','NOT_STARTED','UNCERTAIN')),
  provider_request_id text,
  provider_message_id text,
  reason_code text,
  response_sha256 text NOT NULL CHECK (response_sha256 ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  recorder_principal text NOT NULL CHECK (length(recorder_principal) BETWEEN 1 AND 128),
  consumed_at timestamptz,
  consumed_transition text CHECK (consumed_transition IN ('SENT','RETRY','MANUAL')),
  FOREIGN KEY (job_id,attempt_no)
    REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_no) ON DELETE RESTRICT,
  FOREIGN KEY (job_id,attempt_token,recipient_id)
    REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_token,recipient_id)
    ON DELETE RESTRICT,
  UNIQUE (job_id,attempt_token,evidence_id),
  CHECK (provider_request_id IS NULL OR length(provider_request_id) BETWEEN 1 AND 200),
  CHECK (provider_message_id IS NULL OR length(provider_message_id) BETWEEN 1 AND 200),
  CHECK (reason_code IS NULL OR reason_code IN
    ('PROVIDER_REJECTED_PRE_SUBMIT','TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN')),
  CHECK (
    (outcome = 'ACCEPTED' AND reason_code IS NULL
      AND provider_message_id IS NOT NULL AND provider_request_id IS NOT NULL)
    OR (outcome = 'NOT_STARTED' AND reason_code = 'PROVIDER_REJECTED_PRE_SUBMIT'
      AND provider_message_id IS NULL AND provider_request_id IS NULL)
    OR (outcome = 'UNCERTAIN' AND reason_code IN ('TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN'))
  ),
  CHECK ((consumed_at IS NULL) = (consumed_transition IS NULL))
);

ALTER TABLE public.bot_notification_delivery_attempts
  ADD CONSTRAINT bot_notification_attempt_terminal_evidence_v2_fk
  FOREIGN KEY (terminal_evidence_id)
  REFERENCES public.bot_notification_delivery_evidence(evidence_id) ON DELETE RESTRICT;

-- Versioned functions are created but deliberately not granted to any runtime
-- identity. Producer/dispatcher fencing and execution authorization belong to
-- later phases (064C/064D), not EXPAND.
CREATE FUNCTION public.bot_b53_v2_delivery_claim(a_kind text)
RETURNS TABLE(
  id bigint, kind text, dedupe_key text, payload jsonb, attempts integer,
  recipient_id bigint, attempt_token uuid
)
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = public, pg_catalog AS $$
DECLARE
  v_job record;
  v_token uuid;
  v_claimed timestamptz;
BEGIN
  IF a_kind IS NOT NULL AND a_kind NOT IN
    ('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo')
  THEN
    RAISE EXCEPTION 'invalid_notification_kind';
  END IF;

  SELECT j.id,j.kind,j.dedupe_key,j.payload,j.attempts,j.recipient_id,j.max_attempts
    INTO v_job
  FROM public.bot_notification_jobs AS j
  WHERE j.lifecycle_version = 2
    AND j.state = 'pending'
    AND j.attempts < j.max_attempts
    AND (a_kind IS NULL OR j.kind = a_kind)
  ORDER BY j.attempts,j.id
  FOR UPDATE SKIP LOCKED
  LIMIT 1;
  IF NOT FOUND THEN
    RETURN;
  END IF;

  v_token = pg_catalog.gen_random_uuid();
  v_claimed = clock_timestamp();
  UPDATE public.bot_notification_jobs AS j
  SET state = 'sending', attempts = j.attempts + 1, claimed_at = v_claimed,
      updated_at = v_claimed, attempt_token = v_token
  WHERE j.id = v_job.id AND j.lifecycle_version = 2 AND j.state = 'pending';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'notification_v2_claim_lost';
  END IF;

  INSERT INTO public.bot_notification_delivery_attempts(
    job_id,attempt_no,attempt_token,recipient_id,payload_sha256,claimed_at,claimant_principal
  ) VALUES (
    v_job.id,v_job.attempts + 1,v_token,v_job.recipient_id,
    encode(pg_catalog.sha256(pg_catalog.convert_to(v_job.payload::text,'UTF8')),'hex'),
    v_claimed,session_user
  );

  RETURN QUERY SELECT v_job.id,v_job.kind,v_job.dedupe_key,v_job.payload,
    v_job.attempts + 1,v_job.recipient_id,v_token;
END
$$;

CREATE FUNCTION public.bot_b53_v2_transport_record_evidence(
  a_job_id bigint, a_token uuid, a_outcome text, a_provider_request_id text,
  a_provider_message_id text, a_reason_code text, a_response_sha256 text,
  a_observed_at timestamptz
)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = public, pg_catalog AS $$
DECLARE
  v_attempt record;
  v_evidence uuid;
BEGIN
  IF a_job_id IS NULL OR a_job_id <= 0 OR a_token IS NULL
     OR a_response_sha256 !~ '^[0-9a-f]{64}$' OR a_observed_at IS NULL
  THEN
    RAISE EXCEPTION 'invalid_delivery_evidence';
  END IF;

  SELECT a.attempt_no,a.recipient_id,a.claimed_at INTO v_attempt
  FROM public.bot_notification_delivery_attempts AS a
  JOIN public.bot_notification_jobs AS j ON j.id = a.job_id
  WHERE a.job_id = a_job_id AND a.attempt_token = a_token
    AND j.lifecycle_version = 2 AND j.state = 'sending' AND j.attempt_token = a_token
  FOR UPDATE OF a;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  IF a_observed_at < v_attempt.claimed_at - interval '1 second' THEN
    RAISE EXCEPTION 'evidence_precedes_attempt';
  END IF;

  INSERT INTO public.bot_notification_delivery_evidence(
    job_id,attempt_no,attempt_token,recipient_id,outcome,provider,channel,
    provider_request_id,provider_message_id,reason_code,response_sha256,observed_at,recorder_principal
  ) VALUES (
    a_job_id,v_attempt.attempt_no,a_token,v_attempt.recipient_id,a_outcome,'TELEGRAM','BOT_API',
    a_provider_request_id,a_provider_message_id,a_reason_code,a_response_sha256,a_observed_at,session_user
  ) RETURNING evidence_id INTO v_evidence;

  UPDATE public.bot_notification_delivery_attempts
  SET terminal_outcome = a_outcome, terminal_evidence_id = v_evidence
  WHERE job_id = a_job_id AND attempt_no = v_attempt.attempt_no
    AND terminal_evidence_id IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'terminal_evidence_assignment_lost';
  END IF;
  RETURN v_evidence;
END
$$;

REVOKE ALL ON FUNCTION public.bot_b53_v2_delivery_claim(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.bot_b53_v2_transport_record_evidence(
  bigint,uuid,text,text,text,text,text,timestamptz
) FROM PUBLIC;

COMMIT;
