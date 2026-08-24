-- REHEARSAL ONLY: rollback is legal only before the first v2 submit.
-- No destructive down-migration is defined after v2 data exists; repair-forward
-- is required there. This file fails closed if v2 rows or attempts are present.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.bot_notification_jobs WHERE lifecycle_version = 2
  ) OR EXISTS (
    SELECT 1 FROM public.bot_notification_delivery_attempts
  ) OR EXISTS (
    SELECT 1 FROM public.bot_notification_delivery_evidence
  ) THEN
    RAISE EXCEPTION '064b_rollback_forbidden_after_v2_submit';
  END IF;
END
$$;

DROP FUNCTION public.bot_b53_v2_transport_record_evidence(
  bigint,uuid,text,text,text,text,text,timestamptz
);
DROP FUNCTION public.bot_b53_v2_delivery_claim(text);

ALTER TABLE public.bot_notification_delivery_attempts
  DROP CONSTRAINT bot_notification_attempt_terminal_evidence_v2_fk;

DROP TABLE public.bot_notification_delivery_evidence;
DROP TABLE public.bot_notification_delivery_attempts;

ALTER TABLE public.bot_notification_jobs
  DROP CONSTRAINT bot_notification_jobs_v2_shape_check,
  DROP CONSTRAINT bot_notification_jobs_lifecycle_version_v2_check,
  DROP COLUMN max_attempts,
  DROP COLUMN manual_reason_code,
  DROP COLUMN attempt_token,
  DROP COLUMN recipient_id,
  DROP COLUMN lifecycle_version;

COMMIT;
