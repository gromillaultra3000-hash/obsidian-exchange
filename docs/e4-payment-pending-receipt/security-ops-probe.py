#!/usr/bin/env python3
"""Independent single-file rollback probe; disposable files and fake services."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

ROOT=Path('/root')
RECIPE=ROOT/'deploy/e4_payment_pending_receipt_rollout.py'
MAIN=ROOT/'relay-fastapi/main.py'
OLD_SOURCE=subprocess.run(['git','show','b848d6f429f5b4f79478b41849c70a73d793ce1b:relay-fastapi/main.py'],cwd=ROOT,capture_output=True,check=True).stdout
cases=[]

def fixture(folder):
    spec=importlib.util.spec_from_file_location('terminal_security_ops',RECIPE)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    for name in ['REPO','LIVE','PREIMAGES']:
        value=folder/name.lower();value.mkdir();setattr(m,name,value)
    m.ROOT=m.REPO/'output';m.ROOT.mkdir()
    m.DOCS=m.REPO/'docs';m.DOCS.mkdir()
    m.STATE=m.ROOT/'deployment-state.json';m.MANIFEST=m.DOCS/'ops-release-manifest.json'
    old=OLD_SOURCE;new=MAIN.read_bytes();html=b'unchanged synthetic webapp\n'
    m.BASELINE={m.MAIN:m.sha(old)};m.PRESERVED={m.HTML:m.sha(html)}
    for base,path,data in [(m.LIVE,m.MAIN,old),(m.REPO,m.MAIN,new),(m.LIVE,m.HTML,html),
                           (m.REPO,m.RECIPE,RECIPE.read_bytes()),(m.ROOT/'baseline',m.MAIN,old)]:
        p=base/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o640)
    states={name:{'MainPID':str(i+100),'ActiveState':'active','SubState':'running',
                  'NRestarts':'0','ExecMainStartTimestamp':'synthetic-start-0'} for i,name in enumerate(m.SERVICES)}
    m.services=lambda require_active=True:copy.deepcopy(states)
    m.autopilot_stopped=lambda:{'MainPID':'0','ActiveState':'failed'}
    m.gates=lambda candidate:None
    def public(template):
        assert template==html
        return [{'syntheticPublicTemplateUnchanged':True}]
    m.public_check=public
    calls=[]
    def submit(command,**kwargs):
        assert command==['systemctl','restart','--no-block','relay-fastapi.service']
        calls.append(command)
        states[m.SERVICES[0]].update(MainPID=str(100+len(calls)),
            ExecMainStartTimestamp='synthetic-start-'+str(len(calls)))
        return SimpleNamespace(returncode=0)
    m.subprocess.run=submit
    m.bind();m.preflight()
    metadata=m.metadata(m.LIVE/m.MAIN)
    return m,calls,old,html,metadata

for scenario in ['normal-round-trip','before-publication','after-publication','restart-acknowledgement-lost']:
    with tempfile.TemporaryDirectory(prefix='pending-receipt-security-ops-') as temporary:
        m,calls,old,html,metadata=fixture(Path(temporary))
        replace,restart,submit=m.replace,m.restart_relay,m.subprocess.run
        def interrupt(*args,**kwargs):raise RuntimeError('independent interruption')
        if scenario=='before-publication':m.replace=interrupt
        if scenario=='after-publication':m.restart_relay=interrupt
        if scenario=='restart-acknowledgement-lost':
            def lost_ack(command,**kwargs):
                submit(command,**kwargs)
                raise RuntimeError('independent interruption')
            m.subprocess.run=lost_ack
        if scenario=='normal-round-trip':assert m.deploy()['state']=='VERIFIED'
        else:
            try:m.deploy();raise AssertionError('missing interruption')
            except RuntimeError as error:assert str(error)=='independent interruption'
        before=m.file_state(m.LIVE/m.MAIN);count=len(calls)
        reconciliation=m.reconcile()
        assert reconciliation['result']=='OBSERVED_NO_REPLAY'
        assert len(calls)==count and m.file_state(m.LIVE/m.MAIN)==before
        if scenario=='restart-acknowledgement-lost':
            assert reconciliation['journalState']=='DEPLOY_RESTART_REQUESTED' and count==1
        if scenario in ['before-publication','after-publication']:assert count==0
        try:m.deploy();raise AssertionError('blind deploy replay allowed')
        except RuntimeError as error:assert 'never_repeat_deployment' in str(error)
        m.replace,m.restart_relay,m.subprocess.run=replace,restart,submit
        assert m.rollback()['state']=='ROLLED_BACK'
        assert len(calls)==count+1
        assert (m.LIVE/m.MAIN).read_bytes()==old and (m.LIVE/m.HTML).read_bytes()==html
        current=m.metadata(m.LIVE/m.MAIN)
        assert all(current[k]==metadata[k] for k in ['uid','gid','mode','mtimeNs','xattrs'])
        assert m.reconcile()['journalState']=='ROLLED_BACK'
        try:m.rollback();raise AssertionError('terminal rollback replay allowed')
        except RuntimeError as error:assert 'already_terminal' in str(error)
        cases.append({'case':scenario,'result':'PASS','reconciliationSubmittedNoRestart':True,
            'exactOriginalBytesMetadataRestored':True,'preservedFileUnchanged':True,'restartCount':len(calls)})
    assert not Path(temporary).exists()

print(json.dumps({'schemaVersion':'e4-payment-pending-receipt-independent-ops-probe.v1','result':'PASS',
 'inputs':[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [Path(__file__),RECIPE,MAIN]],
 'cases':cases,'temporaryDirectoriesRemoved':True,'productionReadsWritesNetworkRestarts':False,
 'scope':'Actual single-file journal, publication, reconciliation and rollback functions on disposable files; only upstream gates and service/public observations are mocked.'},indent=2))
