-- REHEARSAL ONLY. Run with autocommit; CREATE INDEX CONCURRENTLY cannot run in
-- a transaction. This file intentionally contains no production role/grant work.
CREATE INDEX CONCURRENTLY bot_notification_jobs_v2_pending_idx
  ON public.bot_notification_jobs(lifecycle_version,state,attempts,id)
  WHERE lifecycle_version = 2 AND state = 'pending';
CREATE UNIQUE INDEX CONCURRENTLY bot_notification_evidence_v2_provider_message_unique
  ON public.bot_notification_delivery_evidence(provider,channel,recipient_id,provider_message_id)
  WHERE provider_message_id IS NOT NULL;
CREATE UNIQUE INDEX CONCURRENTLY bot_notification_evidence_v2_provider_request_unique
  ON public.bot_notification_delivery_evidence(provider,channel,recipient_id,provider_request_id)
  WHERE provider_request_id IS NOT NULL;
