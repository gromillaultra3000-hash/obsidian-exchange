"""Exact payment status module against retained live dependency or isolated PostgreSQL.

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
DOCS = ROOT / 'docs/e4-payment-status-read'
IMAGE = 'postgres@sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee'
MODE = sys.argv[1]
assert MODE in {'legacy', 'postgres'}
sys.path.insert(0, str(ROOT / 'relay'))
legacy = ROOT / 'output/manual/e4-payment-status-read-20260908/baseline/relay/repositories/order_read_store.py'
name = 'repositories.order_read_store'
spec = importlib.util.spec_from_file_location(name, legacy)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
from repositories import order_read_store as orders
from repositories.payment_status_read_store import PaymentStatusReadStore
from e4_payment_status_fixture import fixtures, verify


report = {'mode':MODE,'result':'IN_PROGRESS','productionDataAccessed':False,
          'inputs':[{'path':str(path.relative_to(ROOT)), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in [ROOT/'relay/repositories/payment_status_read_store.py', ROOT/'relay/core/order_access.py', ROOT/'relay-fastapi/main.py', ROOT/'relay/webapp.html', ROOT/'tests/e4_payment_status_fixture.py', Path(__file__)]]}
report_path = DOCS/('live-dependency-rehearsal.json' if MODE == 'legacy' else 'isolated-postgres.json')
report_path.write_text(json.dumps(report,indent=2)+'\n')
with tempfile.TemporaryDirectory(prefix='e4-payment-status-read-') as temp:
    directory=Path(temp)
    if MODE == 'legacy':
        path=directory/'fixture.db'
        with sqlite3.connect(path) as connection:
            states=fixtures(connection)
        store=orders.SQLiteOrderReadStore(str(path))
        connect=store._c
        def readonly():
            c=connect();c.execute('PRAGMA query_only=ON');return c
        store._c=readonly
        report['cases']=verify(PaymentStatusReadStore(store),states)
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
        report.update(containerId=cid,image=IMAGE)
        try:
            dsn=f'host={socket_dir} user=postgres dbname=postgres connect_timeout=1'
            deadline=time.monotonic()+30
            while True:
                if time.monotonic() >= deadline:
                    raise RuntimeError('disposable_postgres_startup_timeout')
                # The image first exposes a temporary initialization server on
                # this same socket, then deliberately stops it. Wait for that
                # phase to finish before testing the final read-only server.
                logs=subprocess.run(['docker','logs',cid],capture_output=True,text=True,
                                    check=True,timeout=5)
                if 'PostgreSQL init process complete; ready for start up.' not in logs.stdout+logs.stderr:
                    time.sleep(.25)
                    continue
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
            report.update(cases=verify(PaymentStatusReadStore(store),states),image=IMAGE,postgresVersion=version,
                          network='none',hostPorts=False,readOnlyQuerySession=True,containerId=cid)
        finally:
            subprocess.run(['docker','rm','-f',cid],check=True,capture_output=True,timeout=20)
            assert subprocess.run(['docker','inspect',cid],capture_output=True).returncode!=0
            report['containerRemoved']=True
            report_path.write_text(json.dumps(report,indent=2)+'\n')
report.update(result='PASS',temporaryDirectoryRemoved=not directory.exists(), retainedDependency={'path':str(legacy),'sha256':hashlib.sha256(legacy.read_bytes()).hexdigest()})
report_path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
