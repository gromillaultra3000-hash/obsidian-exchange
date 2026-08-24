import hashlib
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
E=json.loads((ROOT/"docs/e0-3-relay-acl-envelope-rehearsal.v1.json").read_text())


def test_evidence_is_source_bound_nonproduction_and_truthfully_partial():
 assert E["status"]=="PASS_ROLE_ENVELOPE_FUNCTION_BODIES_INCOMPLETE"
 assert E["productionAuthorization"] is E["implementationDeployed"] is False
 for name,key in (("proposal","proposalSha256"),("runner","runnerSha256")):
  path=ROOT/E["inputs"][name]
  assert hashlib.sha256(path.read_bytes()).hexdigest()==E["inputs"][key]
 assert len(E["notProven"])==5
 assert E["environment"]["containerRemovedAfterRun"] is True


def test_rehearsal_covers_envelope_concurrency_denials_and_rollback():
 c=E["coverage"]
 assert c["connectionLimitAttempts"]==13
 assert c["connectionLimitAccepted"]==12 and c["connectionLimitDenied"]==1
 assert c["claimConcurrencyWorkers"]==c["moneyTransitionConcurrencyWorkers"]==12
 assert c["claimSingleWinner"] is c["moneyTransitionSingleWinner"] is True
 assert c["midTransactionFaultRollback"] is c["callerRollback"] is True
 assert c["exactExecutableFunctionCount"]==5
 assert c["directPrivilegeDenials"]==7 and c["maliciousInputDenials"]==5


def test_proposal_contains_fail_closed_role_and_function_controls():
 sql=(ROOT/E["inputs"]["proposal"]).read_text()
 for marker in (
  "CONNECTION LIMIT 12","NOLOGIN","NOINHERIT","SECURITY DEFINER",
  "SET search_path=pg_catalog","FOR UPDATE SKIP LOCKED",
  "REVOKE ALL ON ALL TABLES","REVOKE ALL ON ALL SEQUENCES",
  "REVOKE ALL ON ALL FUNCTIONS","GRANT EXECUTE ON FUNCTION",
 ):
  assert marker in sql
 assert sql.count("SECURITY DEFINER")==5
 assert sql.count("GRANT EXECUTE ON FUNCTION public.relay_rehearsal_")==5
