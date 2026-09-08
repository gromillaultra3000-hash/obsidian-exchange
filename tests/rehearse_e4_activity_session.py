"""Exact activity module against retained live dependency or isolated PostgreSQL.

No production DSN is accepted. PostgreSQL mode owns a networkless disposable
container and exposes only a Unix socket beneath a root-private temporary dir.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/e4-activity-session'
IMAGE = 'postgres@sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee'
MODE = sys.argv[1]
assert MODE in {'legacy', 'postgres'}
sys.path.insert(0, str(ROOT / 'relay'))
legacy = ROOT / 'output/manual/e4-activity-session-20260908/baseline/relay/repositories/order_read_store.py'
if MODE == 'legacy':
    name = 'repositories.order_read_store'
    spec = importlib.util.spec_from_file_location(name, legacy)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
from repositories import activity_read_store as activity, order_read_store as orders


def fixtures(connection, pg=False):
    mark = '%s' if pg else '?'
    connection.execute('CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount NUMERIC,'
                       'crypto_address TEXT,currency TEXT,status TEXT,created_at TEXT,paid_btc_tx TEXT,'
                       'network TEXT,receipt_sent_at TEXT)')
    connection.execute('CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,'
                       'session_token TEXT,status TEXT,created_at TEXT)')
    states = sorted(activity.SESSION_STATES) + [None, '', 'future-state']
    for oid, state in enumerate(states, 1):
        connection.execute('INSERT INTO orders VALUES('+','.join([mark]*10)+')',
                           (oid,7,2000,'synthetic','TON','pending','2026-09-08','','TON',''))
        connection.execute('INSERT INTO payment_sessions VALUES('+','.join([mark]*5)+')',
                           (oid*10,oid,'older','invoice_created','2099-01-01'))
        connection.execute('INSERT INTO payment_sessions VALUES('+','.join([mark]*5)+')',
                           (oid*10+1,oid,'latest',state,'2000-01-01'))
    connection.execute('INSERT INTO orders VALUES(99,8,4000,\'foreign\',\'TON\',\'pending\',\'2099-01-01\',\'\',\'TON\',\'\')')
    connection.commit()
    return states


def verify(store, states):
    rows = activity.customer_orders(store, 7, limit=100)
    assert len(rows) == len(states)
    for item in rows:
        status = states[item['order_id']-1]
        expected = status if status in activity.SESSION_STATES else 'unknown'
        assert item['payment_session_state'] == expected
        assert item['session_token'] == (None if expected in {'failed','expired','unknown'} else 'latest')
        assert item['rub_amount'] == 2000.0
    assert activity.customer_orders(store, 1000) == []
    assert [row['order_id'] for row in activity.customer_orders(store, 8)] == [99]
    assert len(activity.customer_orders(store, 7, limit=1)) == 1
    return len(rows)


report = {'mode':MODE,'result':'IN_PROGRESS','productionDataAccessed':False,
          'inputs':[{'path':str(path.relative_to(ROOT)), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in [ROOT/'relay/repositories/activity_read_store.py',Path(__file__)]]}
with tempfile.TemporaryDirectory(prefix='e4-activity-session-') as temp:
    directory=Path(temp)
    if MODE == 'legacy':
        path=directory/'fixture.db'
        with sqlite3.connect(path) as connection:
            states=fixtures(connection)
        store=orders.SQLiteOrderReadStore(str(path))
        report['cases']=verify(store,states)
        report['retainedDependency']={'path':str(legacy),'sha256':hashlib.sha256(legacy.read_bytes()).hexdigest()}
    else:
        import psycopg
        socket_dir=directory/'socket';socket_dir.mkdir(mode=0o700);os.chown(socket_dir,70,70)
        command=['docker','run','-d','--network=none','--read-only','--user=70:70',
                 '--cap-drop=ALL','--security-opt=no-new-privileges',
                 '--tmpfs','/var/lib/postgresql/data:rw,nosuid,nodev,uid=70,gid=70,mode=0700',
                 '--tmpfs','/tmp:rw,nosuid,nodev,mode=1777',
                 '--mount',f'type=bind,src={socket_dir},dst=/var/run/postgresql',
                 '-e','POSTGRES_HOST_AUTH_METHOD=trust',IMAGE]
        cid=subprocess.check_output(command,text=True,timeout=20).strip()
        assert re.fullmatch('[0-9a-f]{64}',cid)
        try:
            dsn=f'host={socket_dir} user=postgres dbname=postgres connect_timeout=1'
            deadline=time.monotonic()+30
            while True:
                try:
                    connection=psycopg.connect(dsn);break
                except psycopg.OperationalError:
                    if time.monotonic()>=deadline: raise
                    time.sleep(.25)
            with connection:
                version=connection.execute('SHOW server_version').fetchone()[0]
                states=fixtures(connection,pg=True)
            # Read-only is enforced by the actual PostgreSQL session, after the
            # separate synthetic fixture setup has committed.
            store=orders.PostgresOrderReadStore(dsn+' options=-cdefault_transaction_read_only=on')
            report.update(cases=verify(store,states),image=IMAGE,postgresVersion=version,
                          network='none',hostPorts=False,readOnlyQuerySession=True,containerId=cid)
        finally:
            subprocess.run(['docker','rm','-f',cid],check=True,capture_output=True,timeout=20)
            assert subprocess.run(['docker','inspect',cid],capture_output=True).returncode!=0
            report['containerRemoved']=True
report.update(result='PASS',temporaryDirectoryRemoved=not directory.exists())
(DOCS/(MODE+'-rehearsal.json')).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
