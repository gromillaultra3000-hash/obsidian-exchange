#!/usr/bin/env python3
"""Build deterministic non-authorizing production-specific E0.4 SQL artifacts."""
import argparse, hashlib, io, json, os, re, tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCES={
 "deploy/postgres/proposals/032_e0_relay_p3_authorized_order_reads.sql":"d155a41f78ac03bb337dbd5b16ca7f3122d9ca5278f1a0de1d7af4a0c1069e62",
 "deploy/postgres/proposals/042_e0_bot_b3_1_engagement_non_money_writers.sql":"18ca6c872292c76ba3db739c5c42a565856f2ef1246fd7b2ed5908a94248a172"}
FUNCTIONS=[
 ("relay_order_authorized_snapshot","relay_order_authorized_snapshot","bigint,bigint,text",0),
 ("relay_payment_session_get_by_token","relay_payment_session_get_by_token","text",0),
 ("relay_payment_session_latest_for_authorized_order","relay_payment_session_latest_for_authorized_order","bigint,bigint,text",0),
 ("relay_payment_session_latest_active_for_authorized_order","relay_payment_session_latest_active_for_authorized_order","bigint,bigint,text",0),
 ("relay_payment_session_latest_provider_invoice_for_authorized_order","relay_payment_session_latest_provider_invoice_for_authorized_or","bigint,text,boolean,bigint,text",0),
 ("relay_receipt_authorized_state","relay_receipt_authorized_state","bigint,bigint,text",0),
 ("bot_b3_comment_review","bot_b3_comment_review","bigint,bigint,text",1),
 ("bot_b3_finalize_review","bot_b3_finalize_review","bigint,bigint",1)]
PREIMAGE="docs/e0-4-owner-auth-production-catalog-preimage.v1.json"
PREIMAGE_SHA256="192b4e5c5c7e2de91b21604653177c1ad9b0ad54c64d1a30645560e71b1e49b7"
INTERFACES={
 "relay_order_authorized_snapshot":("p_order_id bigint, p_user_id bigint, p_session_token text","TABLE(order_id bigint, user_id bigint, username text, currency text, rub_amount numeric, crypto_address text, status text, created_at timestamp with time zone, paid_btc_tx text, updated_at timestamp with time zone, web_user_id bigint, rub_volume_counted boolean, verification_requested text, montera_invoice_id text, receipt_deadline timestamp with time zone, receipt_sent_at timestamp with time zone, network text, agreed_rate numeric, agreed_crypto_amount numeric, agreed_at timestamp with time zone)"),
 "relay_payment_session_get_by_token":("p_session_token text","TABLE(amount numeric, order_id bigint, status text, provider_payload text, qr_payload text, expires_at timestamp with time zone)"),
 "relay_payment_session_latest_for_authorized_order":("p_order_id bigint, p_user_id bigint, p_session_token text","TABLE(session_token text, status text)"),
 "relay_payment_session_latest_active_for_authorized_order":("p_order_id bigint, p_user_id bigint, p_session_token text","TABLE(session_token text)"),
 "relay_payment_session_latest_provider_invoice_for_authorized_or":("p_order_id bigint, p_provider text, p_prefix boolean, p_user_id bigint, p_session_token text","TABLE(provider_invoice_id text, provider text)"),
 "relay_receipt_authorized_state":("p_order_id bigint, p_user_id bigint, p_session_token text","text"),
 "bot_b3_comment_review":("a_order_id bigint, a_user_id bigint, a_comment text","boolean"),
 "bot_b3_finalize_review":("a_order_id bigint, a_user_id bigint","jsonb")}

def sha(raw): return hashlib.sha256(raw).hexdigest()
def canon(v): return (json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True)+"\n").encode()
def add(t,n,b):
 i=tarfile.TarInfo(n); i.size=len(b); i.mode=0o644; i.mtime=0;i.uid=i.gid=0;i.uname=i.gname="";t.addfile(i,io.BytesIO(b))
def extract(source,name):
 pattern=re.compile(r"CREATE OR REPLACE FUNCTION public\."+re.escape(name)+r"\(.*?\).*?\$\$;",re.S)
 matches=pattern.findall(source)
 if len(matches)!=1: raise ValueError(f"function extraction mismatch: {name}")
 return matches[0].strip()
def build(output):
 texts=[]
 for path,digest in SOURCES.items():
  raw=(ROOT/path).read_bytes()
  if sha(raw)!=digest: raise ValueError(f"source digest drift: {path}")
  texts.append(raw.decode())
 pre=json.loads((ROOT/PREIMAGE).read_text())
 if sha((ROOT/PREIMAGE).read_bytes())!=PREIMAGE_SHA256: raise ValueError("catalog preimage digest drift")
 expected=[f"{catalog}({sig})" for _,catalog,sig,_ in FUNCTIONS]
 if pre["priorState"]!="ABSENT" or pre["functions"]!=expected: raise ValueError("catalog preimage mismatch")
 absent_expr=" OR ".join(f"to_regprocedure('public.{n}({s})') IS NOT NULL" for _,n,s,_ in FUNCTIONS)
 header="BEGIN;\nSET LOCAL lock_timeout='1s';\nSET LOCAL statement_timeout='10s';\nDO $$ BEGIN\n IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='obsidian_migrator') OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='obsidian_app') THEN RAISE EXCEPTION 'required_production_role_missing'; END IF;\n IF "+absent_expr+" THEN RAISE EXCEPTION 'catalog_preimage_not_absent'; END IF;\nEND $$;\n"
 definitions=[]
 for source_name,catalog_name,_,index in FUNCTIONS:
  definition=extract(texts[index],source_name)
  definition=definition.replace("FUNCTION public."+source_name+"(","FUNCTION public."+catalog_name+"(",1)
  definition=definition.replace("CREATE OR REPLACE FUNCTION","CREATE FUNCTION",1)
  definitions.append(definition)
 bodies="\n\n".join(definitions)
 acl=[]
 for _,name,sig,_ in FUNCTIONS:
  q=f"public.{name}({sig})"; acl += [f"ALTER FUNCTION {q} OWNER TO obsidian_migrator;",f"REVOKE ALL ON FUNCTION {q} FROM PUBLIC;",f"GRANT EXECUTE ON FUNCTION {q} TO obsidian_app;"]
 verify=[]; installed=[]
 for definition,(_,name,sig,_) in zip(definitions,FUNCTIONS):
  ident=f"public.{name}({sig})"
  source=definition.split("AS $$",1)[1].rsplit("$$;",1)[0]
  source_sql="'"+source.replace("'","''")+"'"
  language=re.search(r"LANGUAGE\s+(\w+)",definition,re.I).group(1).lower()
  volatility="s" if re.search(r"\bSTABLE\b",definition) else "v"
  arguments,result=INTERFACES[name]
  acl_exact="(SELECT count(*)=2 AND bool_and(x.privilege_type='EXECUTE' AND NOT x.is_grantable AND x.grantor=p.proowner AND x.grantee IN (p.proowner,(SELECT oid FROM pg_roles WHERE rolname='obsidian_app'))) FROM aclexplode(p.proacl) x)"
  condition=f"p.oid=to_regprocedure('{ident}') AND r.rolname='obsidian_migrator' AND l.lanname='{language}' AND p.provolatile='{volatility}' AND p.prokind='f' AND NOT p.proisstrict AND NOT p.proleakproof AND p.proparallel='u' AND p.prosecdef AND p.proconfig=ARRAY['search_path=pg_catalog'] AND p.prosrc={source_sql} AND pg_get_function_arguments(p.oid)='{arguments}' AND pg_get_function_result(p.oid)='{result}' AND {acl_exact}"
  verify.append(f" IF to_regprocedure('{ident}') IS NULL OR NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang WHERE {condition}) THEN RAISE EXCEPTION 'function_fingerprint_verification_failed:{name}'; END IF;")
  installed.append(verify[-1])
 expand=(header+bodies+"\n\n"+"\n".join(acl)+"\nDO $$ BEGIN\n"+"\n".join(verify)+"\nEND $$;\nCOMMIT;\n").encode()
 drops="\n".join(f"DROP FUNCTION IF EXISTS public.{n}({s});" for _,n,s,_ in reversed(FUNCTIONS))
 all_absent=" AND ".join(f"to_regprocedure('public.{n}({s})') IS NULL" for _,n,s,_ in FUNCTIONS)
 rollback=("BEGIN;\nSET LOCAL lock_timeout='1s';\nSET LOCAL statement_timeout='10s';\nDO $$ BEGIN\n IF NOT ("+all_absent+") THEN\n"+"\n".join(installed)+"\n END IF;\nEND $$;\n"+drops+f"\nDO $$ BEGIN IF {absent_expr} THEN RAISE EXCEPTION 'rollback_absence_verification_failed'; END IF; END $$;\nCOMMIT;\n").encode()
 payload={"sql/expand.sql":expand,"sql/rollback-to-preimage.sql":rollback,"sql/forward-repair.sql":expand}
 manifest={"schemaVersion":"e0-4-owner-auth-sql-release.v1","productionAuthorization":False,"deployable":False,"sourceCatalogPreimageSha256":sha((ROOT/PREIMAGE).read_bytes()),"sourceProposalSha256":SOURCES,"featureFlagsRequired":"OFF","roles":{"owner":"obsidian_migrator","executor":"obsidian_app"},"legacyPrivilegesChanged":False,"artifacts":[]}
 for name,raw in sorted(payload.items()): manifest["artifacts"].append({"path":name,"sha256":sha(raw),"bytes":len(raw)})
 manifest["manifestDigest"]=sha(canon(manifest));manifest["releaseId"]="e04sql_"+manifest["manifestDigest"][:32];payload["manifest.json"]=canon(manifest)
 fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,"wb") as h,tarfile.open(fileobj=h,mode="w",format=tarfile.USTAR_FORMAT) as t:
  for name in sorted(payload): add(t,name,payload[name])
 raw=output.read_bytes();return {"releaseId":manifest["releaseId"],"bundleSha256":sha(raw),"bundleBytes":len(raw),"deployable":False,"productionAuthorization":False}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);print(json.dumps(build(p.parse_args().output),sort_keys=True))
