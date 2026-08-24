import importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/'docs/e0-3-bot-acl-plan.v1.json').read_text())
MATRIX=json.loads((ROOT/'docs/e0-3-bot-method-capability-matrix.v1.json').read_text())
spec=importlib.util.spec_from_file_location('bot_matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
BOT_MATRIX=importlib.util.module_from_spec(spec);spec.loader.exec_module(BOT_MATRIX)

def test_plan_is_proposal_only_and_covers_all_verified_packages():
 assert PLAN['status']=='B5_REHEARSED_PROPOSAL_ONLY'
 assert PLAN['productionAuthorization'] is PLAN['implementationDeployed'] is False
 packages=[json.loads((ROOT/path).read_text()) for path in PLAN['capabilityPackages']]
 assert len(packages)==16 and sum(len(p['capabilities']) for p in packages)==119
 assert all(not p.get('blockers',[]) for p in packages)
 assert PLAN['authorization']['methodCount']==MATRIX['counts']['uniqueMethods']==135
 relay={x['id'] for path,key in [('docs/e0-3-relay-read-matrix.v1.json','reads'),('docs/e0-3-relay-writer-matrix.v1.json','writers')] for x in json.loads((ROOT/path).read_text())[key]}
 package_ids={x['id'] for p in packages for x in p['capabilities']}
 method_ids={x['id'] for x in BOT_MATRIX.build()['methods']}
 assert package_ids <= method_ids and method_ids-package_ids <= relay
 assert len(method_ids-package_ids)==16

def test_roles_are_execute_only_and_fail_closed():
 roles=PLAN['roles']; auth=PLAN['authorization']
 assert roles['login']=='obsidian_exchange_bot'
 assert roles['functionOwner']=='obsidian_exchange_bot_owner'
 assert roles['functionOwnerLogin'] is False
 assert all(roles[k] is False for k in ('inherit','superuser','createDb','createRole','replication','bypassRls'))
 assert auth['directRelationPrivileges']==auth['directSequencePrivileges']==auth['inheritedReadRoles']==[]
 assert auth['loginPrivilege']=='EXECUTE_ONLY' and auth['publicExecute'] is False
 assert {'NO_DIRECT_TABLE_DML','NO_DIRECT_TABLE_SELECT','FIXED_PG_CATALOG_SEARCH_PATH'} <= set(PLAN['ambientPolicy'])

def test_plan_does_not_claim_unproven_role_separation_or_connection_limit():
 assert PLAN['roles']['connectionLimit']==10
 assert PLAN['roles']['connectionBudget']=='docs/e0-3-bot-connection-budget.v1.json'
 assert 'one login necessarily receives the union' in PLAN['singleProcessConstraint']
 assert PLAN['rehearsalPackages'][0]['status']=='REHEARSED'
 assert PLAN['rehearsalPackages'][1]['status']=='REHEARSED'
 assert PLAN['rehearsalPackages'][1]['subpackages'][0]['status']=='REHEARSED'
 assert PLAN['rehearsalPackages'][1]['subpackages'][1]['status']=='REHEARSED'
 assert PLAN['rehearsalPackages'][2]['status']=='REHEARSED'
 b32=PLAN['rehearsalPackages'][2]['subpackages'][1]
 assert b32['status']=='REHEARSED'
 assert [p['status'] for p in b32['subpackages']]==['REHEARSED','REHEARSED']
 b4=PLAN['rehearsalPackages'][3]
 assert b4['status']=='REHEARSED'
 assert [p['status'] for p in b4['subpackages']]==['REHEARSED','REHEARSED']
 b5=PLAN['rehearsalPackages'][4]
 assert b5['status']=='REHEARSED'
 assert b5['subpackages'][0]['status']=='VERIFIED'
 assert [p['status'] for p in b5['subpackages'][1:6]]==['REHEARSED']*5
 assert b5['subpackages'][6]['status']=='REHEARSED'
 assert all(p['status']=='REHEARSED' for p in b5['subpackages'][7:10])
 assert b5['subpackages'][10]['status']=='REHEARSED'
 assert len(b5['subpackages'])==11
 assert PLAN['nextPrerequisite'].startswith('E0.3 production adapter wiring')
