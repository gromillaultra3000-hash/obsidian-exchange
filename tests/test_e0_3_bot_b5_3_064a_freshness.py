import hashlib, json, shutil, subprocess, sys
from pathlib import Path

ROOT=Path('/root'); SCRIPT=ROOT/'scripts/b64_064a_decision_freshness.py'
OLDEST=1786941026  # 2026-08-17T04:30:26Z
NEWEST=1786943724  # 2026-08-17T05:15:24Z

def run(root, now):
    p=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--now',str(now)],text=True,capture_output=True)
    return p,json.loads(p.stdout)

def copy_package(tmp_path):
    for rel in ('docs/e0-3-bot-b5-3-064a-decision-input.v1.json','docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json','docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json'):
        dst=tmp_path/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,dst)
    decision=json.loads((ROOT/'docs/e0-3-bot-b5-3-064a-decision-input.v1.json').read_text())
    for rel in ('docs/e0-3-bot-b5-3-064a-freshness-policy.v1.json','docs/e0-3-bot-b5-3-064a-offline-signing-rehearsal.v1.json','docs/b64-064a-offline-signing.md','relay/core/b64_064a_decision.py','scripts/b64_064a_offline_signer.py','tests/test_e0_3_bot_b5_3_064a_decision.py','tests/test_e0_3_bot_b5_3_064a_offline_signer.py'):
        dst=tmp_path/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,dst)
    mapping={x['artifactId']:x for x in decision['artifactDigests']}
    paths={'migration_plan':'docs/e0-3-bot-b5-3-production-migration-plan.v1.json','dirty_data_scan':'docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json','catalog_drift_rehearsal':'docs/e0-3-bot-b5-3-catalog-security-drift-rehearsal.v1.json','catalog_source_restore_rehearsal':'docs/e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1.json','bootstrap_roles':'deploy/postgres/bootstrap_roles.sql','prepare_database':'deploy/postgres/prepare_database.sql','runtime_privileges':'deploy/postgres/runtime_privileges.sql'}
    for key,rel in paths.items():
        dst=tmp_path/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,dst)
        mapping[key]['sha256']=hashlib.sha256(dst.read_bytes()).hexdigest()
    decision_path=tmp_path/'docs/e0-3-bot-b5-3-064a-decision-input.v1.json'
    decision_path.write_text(json.dumps(decision,indent=2)+'\n')
    rewrite_decision_and_bind(tmp_path,lambda value:None)
    return decision_path

def rewrite_decision_and_bind(root, mutate):
    path=root/'docs/e0-3-bot-b5-3-064a-decision-input.v1.json'; value=json.loads(path.read_text()); mutate(value)
    path.write_text(json.dumps(value,indent=2)+'\n'); digest=hashlib.sha256(path.read_bytes()).hexdigest()
    for rel in ('docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json','docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json'):
        p=root/rel; x=json.loads(p.read_text()); x['decisionInputSha256']=digest; p.write_text(json.dumps(x,indent=2)+'\n')
    policy=root/'docs/e0-3-bot-b5-3-064a-freshness-policy.v1.json'; v=json.loads(policy.read_text())
    by_path={x['path']:x for x in v['supportingArtifacts']}
    for rel,item in by_path.items():
        item['sha256']=hashlib.sha256((root/rel).read_bytes()).hexdigest()
    policy.write_text(json.dumps(v,indent=2)+'\n')

def test_current_package_fails_closed_for_age_and_ambiguous_scope():
    p,x=run(ROOT,1787079480)
    assert p.returncode==2 and x['status']=='REFRESH_REQUIRED'
    assert x['packageIntegrity'] is False and x['ownerDeferralActive'] is True
    assert x['sourceObservationFresh'] is False and x['decisionScopeUnambiguous'] is False
    assert 'ARTIFACT_DIGEST_DRIFT:bootstrap_roles' in x['reasonCodes']
    assert 'ARTIFACT_DIGEST_DRIFT:prepare_database' in x['reasonCodes']
    assert any(r.startswith('SUPPORTING_ARTIFACT_DIGEST_DRIFT:') for r in x['reasonCodes'])
    assert 'DECISION_SCOPE_LABEL_AMBIGUOUS' in x['reasonCodes']
    assert any(r.startswith('SOURCE_OBSERVATION_STALE:') for r in x['reasonCodes'])
    assert x['actionAllowed'] is False and x['productionExpandAuthorized'] is False

def test_fresh_exact_unambiguous_copy_remains_blocked_owner(tmp_path):
    copy_package(tmp_path)
    rewrite_decision_and_bind(tmp_path,lambda x:x.update(requestedDecision='ACCEPT_BOUNDED_EVIDENCE_ONLY'))
    p,x=run(tmp_path,NEWEST+60)
    assert p.returncode==3 and x['status']=='CURRENT_BUT_BLOCKED_OWNER'
    assert x['technicalEvidenceCurrent'] is True and x['ownerDeferralActive'] is True
    assert x['signingPreparationEligible'] is False
    assert x['authenticatedAcceptancePresent'] is False
    assert x['actionAllowed'] is False and x['productionMutationAuthorized'] is False

def test_artifact_drift_binding_drift_future_and_bad_input_fail_closed(tmp_path):
    copy_package(tmp_path); (tmp_path/'deploy/postgres/runtime_privileges.sql').write_text('-- drift')
    p,x=run(tmp_path,NEWEST+60); assert p.returncode==2 and any('ARTIFACT_DIGEST_DRIFT' in r for r in x['reasonCodes'])
    copy_package(tmp_path); d=tmp_path/'docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json'; v=json.loads(d.read_text()); v['decisionInputSha256']='0'*64; d.write_text(json.dumps(v))
    p,x=run(tmp_path,NEWEST+60); assert p.returncode==2 and any('BINDING_DRIFT' in r for r in x['reasonCodes'])
    copy_package(tmp_path); p,x=run(tmp_path,OLDEST-61); assert p.returncode==2 and any('FROM_FUTURE' in r for r in x['reasonCodes'])
    p=subprocess.run([sys.executable,str(SCRIPT),'--root',str(tmp_path),'--now','0'],text=True,capture_output=True); assert p.returncode!=0

def test_freshness_boundaries_and_deferral_never_expires_into_allowance(tmp_path):
    copy_package(tmp_path); rewrite_decision_and_bind(tmp_path,lambda x:x.update(requestedDecision='ACCEPT_BOUNDED_EVIDENCE_ONLY'))
    for now,code in ((OLDEST+86400,3),(OLDEST+86401,2),(NEWEST-60,3),(NEWEST-61,2)):
        p,x=run(tmp_path,now); assert p.returncode==code
        assert x['actionAllowed'] is False and x['signingPreparationEligible'] is False
    d=tmp_path/'docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json'; v=json.loads(d.read_text()); v['actionAllowed']=True; d.write_text(json.dumps(v))
    p,x=run(tmp_path,NEWEST+60); assert p.returncode==2 and x['actionAllowed'] is False

def test_new_candidate_digest_without_new_owner_binding_stays_blocked(tmp_path):
    copy_package(tmp_path)
    path=tmp_path/'docs/e0-3-bot-b5-3-064a-decision-input.v1.json'; value=json.loads(path.read_text())
    value['requestedDecision']='ACCEPT_BOUNDED_EVIDENCE_ONLY'; path.write_text(json.dumps(value,indent=2)+'\n')
    p,x=run(tmp_path,NEWEST+60)
    assert p.returncode==2 and x['status']=='REFRESH_REQUIRED' and x['gateStatus']=='BLOCKED_OWNER'
    assert any('DECISION_INPUT_BINDING_DRIFT:ownerDeferral'==r for r in x['reasonCodes'])
    assert x['actionAllowed'] is False and x['productionExpandAuthorized'] is False

def test_missing_malformed_symlink_and_invalid_timestamp_use_finite_fail_closed_status(tmp_path):
    targets=[]
    copy_package(tmp_path); (tmp_path/'docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json').unlink(); targets.append(tmp_path)
    for index,kind in enumerate(('malformed','symlink','timestamp')):
        root=tmp_path/f'case-{index}'; copy_package(root)
        if kind=='malformed': (root/'docs/e0-3-bot-b5-3-064a-decision-input.v1.json').write_text('{')
        elif kind=='symlink':
            p=root/'docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json'; p.unlink(); p.symlink_to(root/'docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json')
        else:
            p=root/'docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json'; v=json.loads(p.read_text()); v['observedAt']='not-a-time'; p.write_text(json.dumps(v))
        targets.append(root)
    for root in targets:
        p,x=run(root,NEWEST+60)
        assert p.returncode==2 and x['status']=='REFRESH_REQUIRED' and x['gateStatus']=='BLOCKED_OWNER'
        assert x['reasonCodes']==['PREFLIGHT_INPUT_INVALID']
        for field in ('signingPreparationEligible','authenticatedAcceptancePresent','productionMutationAuthorized','productionExpandAuthorized','cutoverAuthorized','actionAllowed'): assert x[field] is False

def test_closed_supporting_paths_reject_substitution_absolute_parent_and_symlink(tmp_path):
    for index,replacement in enumerate(('docs/b64-064a-offline-signing.md','/etc/passwd','../outside')):
        root=tmp_path/f'paths-{index}'; copy_package(root)
        policy=root/'docs/e0-3-bot-b5-3-064a-freshness-policy.v1.json'; v=json.loads(policy.read_text()); v['supportingArtifacts'][0]['path']=replacement; policy.write_text(json.dumps(v))
        p,x=run(root,NEWEST+60); assert p.returncode==2 and x['status']=='REFRESH_REQUIRED'
        assert 'SUPPORTING_ARTIFACT_SET_MISMATCH' in x['reasonCodes'] and x['actionAllowed'] is False
        assert x['packageIntegrity'] is False
    root=tmp_path/'paths-symlink'; copy_package(root)
    target=root/'docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json'; target.unlink(); target.symlink_to(root/'docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json')
    p,x=run(root,NEWEST+60); assert p.returncode==2 and x['status']=='REFRESH_REQUIRED'
    assert x['packageIntegrity'] is False

def test_policy_authority_outcome_time_source_and_extra_keys_are_closed(tmp_path):
    mutations=(lambda v:v['authority'].update(freshnessCanAuthorize=True),
               lambda v:v.update(outcomes=['APPROVED']),
               lambda v:v.update(evaluatedTimeSource='TRUSTED'),
               lambda v:v.update(extra='value'))
    for index,mutate in enumerate(mutations):
        root=tmp_path/f'policy-{index}'; copy_package(root)
        path=root/'docs/e0-3-bot-b5-3-064a-freshness-policy.v1.json'; value=json.loads(path.read_text()); mutate(value); path.write_text(json.dumps(value))
        p,x=run(root,NEWEST+60)
        assert p.returncode==2 and x['status']=='REFRESH_REQUIRED' and x['packageIntegrity'] is False
        assert 'FRESHNESS_POLICY_INVALID' in x['reasonCodes'] and x['actionAllowed'] is False

def test_naive_and_non_utc_timestamp_are_rejected(tmp_path):
    for index,value in enumerate(('2026-08-17T04:30:26','2026-08-17T05:30:26+01:00')):
        root=tmp_path/f'time-{index}'; copy_package(root)
        path=root/'docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json'; item=json.loads(path.read_text()); item['observedAt']=value; path.write_text(json.dumps(item))
        p,x=run(root,NEWEST+60); assert p.returncode==2 and x['status']=='REFRESH_REQUIRED' and x['reasonCodes']==['PREFLIGHT_INPUT_INVALID']

def test_script_has_no_network_db_secret_or_write_path():
    s=SCRIPT.read_text()
    for marker in ('requests','httpx','socket','psycopg','subprocess','os.environ','write_text','open('): assert marker not in s
    assert 'actionAllowed": False' in s and 'productionExpandAuthorized": False' in s
