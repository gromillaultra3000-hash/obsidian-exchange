-- Dormant E3 paper evidence persistence. Not applied by production cutover.
CREATE TABLE e3_paper_evidence(
 contract_kind TEXT NOT NULL CHECK(contract_kind IN
  ('INTENT_STATE','DAILY_USAGE','ADMISSION_CONTROL','PNL_JOURNAL','ENGINE_EVIDENCE')),
 document_id TEXT NOT NULL,
 account_id TEXT NOT NULL,
 sequence BIGINT NOT NULL CHECK(sequence>=0),
 document_hash TEXT NOT NULL,
 previous_document_hash TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(contract_kind,document_id),
 UNIQUE(contract_kind,document_hash),
 CHECK(octet_length(payload::text)<=1048576)
);

CREATE TABLE e3_paper_evidence_heads(
 contract_kind TEXT NOT NULL,
 account_id TEXT NOT NULL,
 sequence BIGINT NOT NULL CHECK(sequence>=0),
 document_id TEXT NOT NULL,
 document_hash TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(contract_kind,account_id),
 FOREIGN KEY(contract_kind,document_id)
  REFERENCES e3_paper_evidence(contract_kind,document_id),
 FOREIGN KEY(contract_kind,document_hash)
  REFERENCES e3_paper_evidence(contract_kind,document_hash)
);

CREATE OR REPLACE FUNCTION e3_reject_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'e3 paper evidence is append-only';
END$$;

CREATE TRIGGER e3_paper_evidence_no_update
BEFORE UPDATE OR DELETE ON e3_paper_evidence
FOR EACH ROW EXECUTE FUNCTION e3_reject_evidence_mutation();

CREATE OR REPLACE FUNCTION e3_append_paper_evidence(
 p_kind TEXT,p_document_id TEXT,p_account_id TEXT,p_sequence BIGINT,
 p_document_hash TEXT,p_previous_hash TEXT,p_payload JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE existing e3_paper_evidence%ROWTYPE;
DECLARE head e3_paper_evidence_heads%ROWTYPE;
BEGIN
 IF p_kind NOT IN ('INTENT_STATE','DAILY_USAGE','ADMISSION_CONTROL','PNL_JOURNAL','ENGINE_EVIDENCE')
    OR p_sequence<0 OR jsonb_typeof(p_payload)<>'object'
    OR octet_length(p_payload::text)>1048576 THEN
  RAISE EXCEPTION 'invalid e3 paper evidence';
 END IF;
 SELECT * INTO head FROM e3_paper_evidence_heads
  WHERE contract_kind=p_kind AND account_id=p_account_id FOR UPDATE;
 IF FOUND AND head.document_id=p_document_id AND head.document_hash=p_document_hash
    AND head.sequence=p_sequence THEN RETURN FALSE; END IF;
 IF (NOT FOUND AND (p_sequence<>0 OR p_previous_hash<>repeat('0',64)))
    OR (FOUND AND (p_sequence<>head.sequence+1 OR p_previous_hash<>head.document_hash)) THEN
  RAISE EXCEPTION 'e3 paper evidence continuity conflict';
 END IF;
 INSERT INTO e3_paper_evidence(contract_kind,document_id,account_id,sequence,
  document_hash,previous_document_hash,payload)
 VALUES(p_kind,p_document_id,p_account_id,p_sequence,p_document_hash,
  p_previous_hash,p_payload) ON CONFLICT(contract_kind,document_id) DO NOTHING;
 SELECT * INTO existing FROM e3_paper_evidence
  WHERE contract_kind=p_kind AND document_id=p_document_id;
 IF existing.account_id<>p_account_id OR existing.sequence<>p_sequence
    OR existing.document_hash<>p_document_hash
    OR existing.previous_document_hash<>p_previous_hash
    OR existing.payload<>p_payload THEN
  RAISE EXCEPTION 'e3 paper evidence idempotency drift';
 END IF;
 INSERT INTO e3_paper_evidence_heads(contract_kind,account_id,sequence,
  document_id,document_hash) VALUES(p_kind,p_account_id,p_sequence,
  p_document_id,p_document_hash)
 ON CONFLICT(contract_kind,account_id) DO UPDATE SET
  sequence=EXCLUDED.sequence,document_id=EXCLUDED.document_id,
  document_hash=EXCLUDED.document_hash,updated_at=now();
 RETURN TRUE;
END$$;

REVOKE UPDATE,DELETE,TRUNCATE ON e3_paper_evidence FROM PUBLIC;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON e3_paper_evidence_heads FROM PUBLIC;
REVOKE ALL ON FUNCTION e3_reject_evidence_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION e3_append_paper_evidence(
 TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,JSONB
) FROM PUBLIC;
