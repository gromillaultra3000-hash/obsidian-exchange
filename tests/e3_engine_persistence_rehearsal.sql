\set ON_ERROR_STOP on

SELECT e3_append_paper_evidence(
 'ENGINE_EVIDENCE','peb_first','sandbox_1',0,repeat('a',64),repeat('0',64),
 '{"schemaVersion":"paper-engine-evidence-bundle.v1"}'::jsonb
) AS first_append \gset
\if :first_append
\else
 \quit 11
\endif

SELECT NOT e3_append_paper_evidence(
 'ENGINE_EVIDENCE','peb_first','sandbox_1',0,repeat('a',64),repeat('0',64),
 '{"schemaVersion":"paper-engine-evidence-bundle.v1"}'::jsonb
) AS exact_retry \gset
\if :exact_retry
\else
 \quit 12
\endif

SELECT e3_append_paper_evidence(
 'ENGINE_EVIDENCE','peb_second','sandbox_1',1,repeat('b',64),repeat('a',64),
 '{"schemaVersion":"paper-engine-evidence-bundle.v1","sequence":1}'::jsonb
) AS next_append \gset
\if :next_append
\else
 \quit 13
\endif

DO $$
BEGIN
 BEGIN
  PERFORM e3_append_paper_evidence(
   'ENGINE_EVIDENCE','peb_gap','sandbox_1',3,repeat('c',64),repeat('b',64),'{}');
  RAISE EXCEPTION 'sequence gap unexpectedly accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='sequence gap unexpectedly accepted' THEN RAISE; END IF;
 END;
 BEGIN
  PERFORM e3_append_paper_evidence(
   'ENGINE_EVIDENCE','peb_second','sandbox_1',1,repeat('f',64),repeat('a',64),'{}');
  RAISE EXCEPTION 'idempotency drift unexpectedly accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='idempotency drift unexpectedly accepted' THEN RAISE; END IF;
 END;
 BEGIN
  UPDATE e3_paper_evidence SET payload='{}' WHERE document_id='peb_first';
  RAISE EXCEPTION 'mutation unexpectedly accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='mutation unexpectedly accepted' THEN RAISE; END IF;
 END;
END$$;

SELECT sequence=1 AND document_id='peb_second' AND document_hash=repeat('b',64)
 AS correct_head
FROM e3_paper_evidence_heads
WHERE contract_kind='ENGINE_EVIDENCE' AND account_id='sandbox_1' \gset
\if :correct_head
\else
 \quit 14
\endif
