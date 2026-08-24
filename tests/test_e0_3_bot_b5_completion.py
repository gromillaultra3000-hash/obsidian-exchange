import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DECOMP=json.loads((ROOT/'docs/e0-3-bot-b5-1-writer-decomposition.v1.json').read_text())
PLAN=json.loads((ROOT/'docs/e0-3-bot-acl-plan.v1.json').read_text())
EVIDENCE=[
 'docs/e0-3-bot-b5-2-residual-identity-support-config-writers-rehearsal.v1.json',
 'docs/e0-3-bot-b5-3-notification-queue-writers-rehearsal.v1.json',
 'docs/e0-3-bot-b5-4-order-creation-writer-rehearsal.v1.json',
 'docs/e0-3-bot-b5-5-automation-gift-writers-rehearsal.v1.json',
 'docs/e0-3-bot-b5-6-status-delivery-subset-rehearsal.v1.json',
 'docs/e0-3-bot-b5-7-ambiguity-safe-outbox-rehearsal.v1.json',
 'docs/e0-3-bot-b5-8-payout-intent-creation-rehearsal.v1.json',
 'docs/e0-3-bot-b5-9-sell-safe-lifecycle-rehearsal.v1.json',
 'docs/e0-3-bot-b5-10-chain-evidence-rehearsal.v1.json',
 'docs/e0-3-bot-b5-11-ledger-money-finalization-rehearsal.v1.json']

def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def test_b5_exact_method_set_is_complete_once():
 expected=[m for p in DECOMP['orderedPackages'] for m in p['methods']]
 observed=[]
 for path in EVIDENCE:
  d=json.loads((ROOT/path).read_text())
  observed+=d.get('methodCoverage',[])+d.get('supersedesLegacyMethods',[])
 assert len(expected)==39 and len(observed)==39
 assert len(set(observed))==39
 assert set(observed)==set(expected)

def test_evidence_is_proposal_only_and_hash_bound():
 for path in EVIDENCE:
  d=json.loads((ROOT/path).read_text())
  assert d['productionAuthorization'] is d['implementationDeployed'] is False
  assert 'PASS' in d['result']
  artifacts=[]
  if d.get('proposal'):artifacts.append((d['proposal'],d['proposalSha256']))
  artifacts += [(x['path'],x['sha256']) for x in d.get('proposals',[])]
  artifacts.append((d['test'],d['testSha256']))
  for rel,digest in artifacts:assert _sha(ROOT/rel)==digest

def test_all_b5_functions_are_owner_bound_execute_only():
 for number in range(47,58):
  matches=list((ROOT/'deploy/postgres/proposals').glob(f'{number:03d}_e0_bot_b5_*.sql'))
  assert len(matches)==1
  sql=matches[0].read_text()
  names=set(re.findall(r'CREATE OR REPLACE FUNCTION public\.([a-z0-9_]+)',sql))
  assert names
  for name in names:
   assert f'ALTER FUNCTION public.{name}' in sql
   assert f'public.{name}' in sql and 'REVOKE ALL ON FUNCTION' in sql
   assert 'SECURITY DEFINER SET search_path=pg_catalog' in sql
  for statement in sql.split(';'):
   if 'GRANT ' in statement and ' TO obsidian_exchange_bot' in statement and 'obsidian_exchange_bot_owner' not in statement:
    assert 'GRANT EXECUTE ON FUNCTION' in statement

def test_split_status_completion_has_dedicated_money_contracts():
 b56=json.loads((ROOT/EVIDENCE[4]).read_text())
 b511=json.loads((ROOT/EVIDENCE[-1]).read_text())
 assert b56['methodCoverage']==['status_notification_store.complete']
 assert set(b511['b5_6Resolution'])=={'paidAndSent','payoutTriggered','payoutHeld'}
 assert 'proposal 053' in b511['b5_6Resolution']['payoutTriggered']
 assert 'proposal 057' in b511['b5_6Resolution']['payoutHeld']

def test_plan_records_proposal_only_b5_completion():
 assert PLAN['status']=='B5_REHEARSED_PROPOSAL_ONLY'
 assert PLAN['productionAuthorization'] is PLAN['implementationDeployed'] is False
 assert PLAN['b5CompletionEvidence']=='docs/e0-3-bot-b5-completion.v1.json'
 b5=PLAN['rehearsalPackages'][4]
 assert b5['status']=='REHEARSED' and len(b5['subpackages'])==11
 assert all(p['status'] in {'VERIFIED','REHEARSED'} for p in b5['subpackages'])
