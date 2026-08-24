-- Read-only, identifier-free ACL/owner fingerprint for B64 restore comparison.
WITH acl_entries AS (
 SELECT 'relation|'||c.relkind::text||'|'||c.relname||'|owner='||o.rolname||'|grantee='||
  COALESCE(g.rolname,'PUBLIC')||'|grantor='||go.rolname||'|priv='||x.privilege_type||
  '|grantable='||x.is_grantable AS item
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_roles o ON o.oid=c.relowner
 CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault(
  CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,c.relowner))) x
 LEFT JOIN pg_roles g ON g.oid=x.grantee JOIN pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public' AND c.relkind IN('r','p','S')
 UNION ALL
 SELECT 'function|'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')|owner='||o.rolname||
  '|grantee='||COALESCE(g.rolname,'PUBLIC')||'|grantor='||go.rolname||'|priv='||x.privilege_type||
  '|grantable='||x.is_grantable
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles o ON o.oid=p.proowner
 CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) x
 LEFT JOIN pg_roles g ON g.oid=x.grantee JOIN pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'schema|public|owner='||o.rolname||'|grantee='||COALESCE(g.rolname,'PUBLIC')||
  '|grantor='||go.rolname||'|priv='||x.privilege_type||'|grantable='||x.is_grantable
 FROM pg_namespace n JOIN pg_roles o ON o.oid=n.nspowner
 CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) x
 LEFT JOIN pg_roles g ON g.oid=x.grantee JOIN pg_roles go ON go.oid=x.grantor WHERE n.nspname='public'
 UNION ALL
 SELECT 'database|owner='||o.rolname||'|grantee='||COALESCE(g.rolname,'PUBLIC')||
  '|grantor='||go.rolname||'|priv='||x.privilege_type||'|grantable='||x.is_grantable
 FROM pg_database d JOIN pg_roles o ON o.oid=d.datdba
 CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl,acldefault('d',d.datdba))) x
 LEFT JOIN pg_roles g ON g.oid=x.grantee JOIN pg_roles go ON go.oid=x.grantor
 WHERE d.datname=current_database()
), role_entries AS (
 SELECT rolname||'|super='||rolsuper||'|createdb='||rolcreatedb||'|createrole='||rolcreaterole||
  '|replication='||rolreplication||'|bypassrls='||rolbypassrls||'|login='||rolcanlogin||
  '|inherit='||rolinherit||'|connlimit='||rolconnlimit||'|config='||COALESCE(array_to_string(rolconfig,','),'') AS item
 FROM pg_roles WHERE rolname IN('obsidian_migrator','obsidian_app','obsidian_readonly','obsidian_payout')
), combined AS (
 SELECT 'acl' section,item FROM acl_entries UNION ALL SELECT 'role',item FROM role_entries
)
SELECT jsonb_build_object(
 'aclEntries',count(*) FILTER(WHERE section='acl'),
 'aclSha256',encode(sha256(convert_to(COALESCE(string_agg(item,E'\n' ORDER BY item) FILTER(WHERE section='acl'),''),'UTF8')),'hex'),
 'roleEntries',count(*) FILTER(WHERE section='role'),
 'roleSha256',encode(sha256(convert_to(COALESCE(string_agg(item,E'\n' ORDER BY item) FILTER(WHERE section='role'),''),'UTF8')),'hex')
) FROM combined;
