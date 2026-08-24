import json,subprocess,sys,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/"scripts/e0_4_build_owner_auth_sql_release.py"
def test_sql_release_is_reproducible_narrow_and_non_authorizing(tmp_path):
 results=[];bundles=[]
 for name in ("a.tar","b.tar"):
  path=tmp_path/name;bundles.append(path);results.append(json.loads(subprocess.run([sys.executable,str(SCRIPT),"--output",str(path)],check=True,capture_output=True,text=True).stdout))
 assert bundles[0].read_bytes()==bundles[1].read_bytes() and results[0]==results[1]
 with tarfile.open(bundles[0]) as t:
  assert t.getnames()==["manifest.json","sql/expand.sql","sql/forward-repair.sql","sql/rollback-to-preimage.sql"]
  manifest=json.load(t.extractfile("manifest.json")); expand=t.extractfile("sql/expand.sql").read().decode(); rollback=t.extractfile("sql/rollback-to-preimage.sql").read().decode()
 assert manifest["productionAuthorization"] is False and manifest["deployable"] is False
 assert manifest["featureFlagsRequired"]=="OFF" and manifest["legacyPrivilegesChanged"] is False
 assert expand==tarfile.open(bundles[0]).extractfile("sql/forward-repair.sql").read().decode()
 assert expand.count("CREATE FUNCTION")==8 and "CREATE OR REPLACE FUNCTION" not in expand
 assert rollback.count("DROP FUNCTION IF EXISTS")==8
 assert expand.count("catalog_preimage_not_absent")==1
 assert rollback.count("function_fingerprint_verification_failed:")==8
 assert "IF NOT (" in rollback and "prokind='f'" in rollback and "p.proparallel='u'" in rollback
 assert "p.prosrc='" in rollback and "pg_get_function_arguments" in rollback and "pg_get_function_result" in rollback
 assert "count(*)=2" in rollback and "NOT x.is_grantable" in rollback and "x.grantor=p.proowner" in rollback
 assert "relay_payment_session_latest_provider_invoice_for_authorized_or" in expand
 assert "relay_payment_session_latest_provider_invoice_for_authorized_order(" not in expand
 for forbidden in ("CREATE ROLE","ALTER ROLE","PASSWORD","REVOKE ALL ON ALL TABLES","REVOKE CONNECT","GRANT SELECT"):
  assert forbidden not in expand
 assert "OWNER TO obsidian_migrator" in expand and "TO obsidian_app" in expand
def test_existing_output_is_not_overwritten(tmp_path):
 path=tmp_path/"x.tar";path.write_bytes(b"keep")
 result=subprocess.run([sys.executable,str(SCRIPT),"--output",str(path)],capture_output=True,text=True)
 assert result.returncode!=0 and path.read_bytes()==b"keep"
