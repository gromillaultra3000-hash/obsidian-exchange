\set ON_ERROR_STOP on
BEGIN;
INSERT INTO payout_intents(order_id,idempotency_key,source,rub_amount,crypto_amount,
 currency,destination) VALUES(101,'payout_101','rehearsal',1000,0.001,'BTC','dest');
SELECT id FROM claim_next_order_payout() \gset order_
DO $$ BEGIN
 IF (SELECT state FROM payout_intents WHERE order_id=101) <> 'processing' THEN
  RAISE EXCEPTION 'order claim failed';
 END IF;
 IF EXISTS(SELECT 1 FROM claim_next_order_payout()) THEN
  RAISE EXCEPTION 'order double claim';
 END IF;
END $$;
UPDATE payout_intents SET state='succeeded',txid=repeat('a',64),finished_at=now()
 WHERE id=:order_id AND state='processing';

INSERT INTO referral_payout_intents(user_id,idempotency_key,crypto_amount,destination)
 VALUES(7,'referral_7_1',0.002,'refdest');
-- Partial unique index is the reservation boundary.
DO $$ BEGIN
 BEGIN
  INSERT INTO referral_payout_intents(user_id,idempotency_key,crypto_amount,destination)
   VALUES(7,'referral_7_2',0.002,'other');
  RAISE EXCEPTION 'active referral duplicate accepted';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
END $$;
SELECT id FROM claim_next_referral_payout() \gset ref_
UPDATE referral_payout_intents SET state='review',error_code='TimeoutError'
 WHERE id=:ref_id AND state='processing';
UPDATE referral_payout_intents SET state='pending',error_code=NULL,claimed_at=NULL
 WHERE id=:ref_id AND state='review';
SELECT id FROM claim_next_referral_payout() \gset retry_
DO $$ BEGIN
 IF (SELECT count(*) FROM referral_payout_intents
     WHERE user_id=7 AND state='processing' AND attempts=2) <> 1 THEN
  RAISE EXCEPTION 'referral retry changed debt';
 END IF;
END $$;
ROLLBACK;
