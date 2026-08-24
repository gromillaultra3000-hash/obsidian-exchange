-- PG17 read-only, collision-safe bounded catalog/security fingerprint v2.
-- Output is only: coverage version, section, entry count, SHA-256.
-- Runtime sequence state is intentionally excluded because it is non-MVCC.
-- Transaction-neutral: callers may execute this inside an already-exported
-- snapshot transaction. These session settings do not commit that transaction.
SET search_path = pg_catalog;
SET row_security = off;

WITH sections(section) AS (VALUES
 ('column_acl'),('default_acl'),('membership'),('db_role_setting'),
 ('relation_security'),('constraint_security'),('index_security'),
 ('trigger_security'),('function_security'),('policy_security'),
 ('sequence_definition'),('type_security'),('extension_security')
), entries(section,item) AS (
 SELECT 'column_acl',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,'column',a.attname,'number',a.attnum,
  'aclIsNull',a.attacl IS NULL,'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable)
 FROM pg_catalog.pg_attribute a
 JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 LEFT JOIN LATERAL pg_catalog.aclexplode(a.attacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public' AND c.relkind IN('r','p','v','m','f')
  AND a.attnum>0 AND NOT a.attisdropped
 UNION ALL
 SELECT 'default_acl',jsonb_build_object(
  'owner',o.rolname,'schema',CASE WHEN d.defaclnamespace=0 THEN '<GLOBAL>' ELSE n.nspname END,
  'objectType',d.defaclobjtype::text,'aclIsNull',d.defaclacl IS NULL,
  'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable)
 FROM pg_catalog.pg_default_acl d
 JOIN pg_catalog.pg_roles o ON o.oid=d.defaclrole
 LEFT JOIN pg_catalog.pg_namespace n ON n.oid=d.defaclnamespace
 LEFT JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE o.rolname LIKE 'obsidian\_%' ESCAPE '\'
 UNION ALL
 SELECT 'membership',jsonb_build_object(
  'role',r.rolname,'member',m.rolname,'grantor',g.rolname,
  'admin',am.admin_option,'inherit',am.inherit_option,'set',am.set_option)
 FROM pg_catalog.pg_auth_members am
 JOIN pg_catalog.pg_roles r ON r.oid=am.roleid
 JOIN pg_catalog.pg_roles m ON m.oid=am.member
 JOIN pg_catalog.pg_roles g ON g.oid=am.grantor
 WHERE r.rolname LIKE 'obsidian\_%' ESCAPE '\' OR m.rolname LIKE 'obsidian\_%' ESCAPE '\'
 UNION ALL
 SELECT 'db_role_setting',jsonb_build_object(
  'role',CASE WHEN s.setrole=0 THEN '<ALL_ROLES>' ELSE r.rolname END,
  'database',CASE WHEN s.setdatabase=0 THEN '<ALL_DATABASES>'
    WHEN d.datname=pg_catalog.current_database() THEN '<CURRENT>' ELSE d.datname END,
  'settingName',CASE WHEN q.setting IS NULL THEN NULL ELSE pg_catalog.left(q.setting,pg_catalog.strpos(q.setting,'=')-1) END,
  'assignmentSha256',CASE WHEN q.setting IS NULL THEN NULL ELSE pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(q.setting,'UTF8')),'hex') END,
  'configIsEmpty',COALESCE(pg_catalog.cardinality(s.setconfig),0)=0)
 FROM pg_catalog.pg_db_role_setting s
 LEFT JOIN pg_catalog.pg_roles r ON r.oid=s.setrole
 LEFT JOIN pg_catalog.pg_database d ON d.oid=s.setdatabase
 LEFT JOIN LATERAL pg_catalog.unnest(s.setconfig) q(setting) ON true
 WHERE s.setrole=0 OR r.rolname LIKE 'obsidian\_%' ESCAPE '\'
 UNION ALL
 SELECT 'relation_security',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,'kind',c.relkind::text,'owner',o.rolname,
  'persistence',c.relpersistence::text,'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
  'replicaIdentity',c.relreplident::text,'isPartition',c.relispartition,
  'options',COALESCE((SELECT jsonb_agg(v ORDER BY v) FROM pg_catalog.unnest(c.reloptions) v),'[]'::jsonb),
  'partitionKey',CASE WHEN c.relkind='p' THEN pg_catalog.pg_get_partkeydef(c.oid) END,
  'partitionBound',pg_catalog.pg_get_expr(c.relpartbound,c.oid,false),
  'viewDefinition',CASE WHEN c.relkind IN('v','m') THEN pg_catalog.pg_get_viewdef(c.oid,false) END,
  'aclIsNull',c.relacl IS NULL,'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable)
 FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_catalog.pg_roles o ON o.oid=c.relowner
 LEFT JOIN LATERAL pg_catalog.aclexplode(c.relacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public' AND c.relkind IN('r','p','S','v','m','f')
 UNION ALL
 SELECT 'constraint_security',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,'constraint',con.conname,'type',con.contype::text,
  'validated',con.convalidated,'deferrable',con.condeferrable,'deferred',con.condeferred,
  'noInherit',con.connoinherit,'definition',pg_catalog.pg_get_constraintdef(con.oid,false))
 FROM pg_catalog.pg_constraint con
 JOIN pg_catalog.pg_class c ON c.oid=con.conrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'constraint_security',jsonb_build_object(
  'schema',n.nspname,'domain',t.typname,'constraint',con.conname,'type',con.contype::text,
  'validated',con.convalidated,'deferrable',con.condeferrable,'deferred',con.condeferred,
  'noInherit',con.connoinherit,'definition',pg_catalog.pg_get_constraintdef(con.oid,false))
 FROM pg_catalog.pg_constraint con
 JOIN pg_catalog.pg_type t ON t.oid=con.contypid
 JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
 WHERE n.nspname='public' AND con.contypid<>0
 UNION ALL
 SELECT 'index_security',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,'index',i.relname,
  'valid',x.indisvalid,'ready',x.indisready,'live',x.indislive,'unique',x.indisunique,
  'primary',x.indisprimary,'exclusion',x.indisexclusion,'replicaIdentity',x.indisreplident,
  'clustered',x.indisclustered,'definition',pg_catalog.pg_get_indexdef(i.oid))
 FROM pg_catalog.pg_index x
 JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid
 JOIN pg_catalog.pg_class c ON c.oid=x.indrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'trigger_security',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,
  'trigger',CASE WHEN t.tgisinternal THEN NULL ELSE t.tgname END,
  'constraintSchema',con_n.nspname,'constraintRelation',con_c.relname,'constraint',con.conname,
  'typeBits',t.tgtype,'enabled',t.tgenabled::text,
  'internal',t.tgisinternal,'deferrable',t.tgdeferrable,'initiallyDeferred',t.tginitdeferred,
  'functionSchema',pn.nspname,'function',p.proname,
  'functionArgs',pg_catalog.pg_get_function_identity_arguments(p.oid),
  'definition',CASE WHEN t.tgisinternal THEN NULL ELSE pg_catalog.pg_get_triggerdef(t.oid,false) END)
 FROM pg_catalog.pg_trigger t
 JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
 JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
 LEFT JOIN pg_catalog.pg_constraint con ON con.oid=t.tgconstraint
 LEFT JOIN pg_catalog.pg_class con_c ON con_c.oid=con.conrelid
 LEFT JOIN pg_catalog.pg_namespace con_n ON con_n.oid=con_c.relnamespace
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'function_security',jsonb_build_object(
  'schema',n.nspname,'function',p.proname,'identityArgs',pg_catalog.pg_get_function_identity_arguments(p.oid),
  'kind',p.prokind::text,'owner',o.rolname,'language',l.lanname,'securityDefiner',p.prosecdef,
  'leakproof',p.proleakproof,'strict',p.proisstrict,'returnsSet',p.proretset,
  'volatility',p.provolatile::text,'parallel',p.proparallel::text,
  'configSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(COALESCE(
    (SELECT pg_catalog.string_agg(v,chr(10) ORDER BY v) FROM pg_catalog.unnest(p.proconfig) v),''),'UTF8')),'hex'),
  'aclIsNull',p.proacl IS NULL,'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable,
  'definitionSha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_functiondef(p.oid),'UTF8')),'hex'))
 FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_catalog.pg_roles o ON o.oid=p.proowner
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 LEFT JOIN LATERAL pg_catalog.aclexplode(p.proacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public' AND p.prokind IN('f','p')
 UNION ALL
 SELECT 'policy_security',jsonb_build_object(
  'schema',n.nspname,'relation',c.relname,'policy',p.polname,'permissive',p.polpermissive,
  'command',p.polcmd::text,'roles',COALESCE((SELECT jsonb_agg(CASE WHEN q.role_oid=0 THEN 'PUBLIC' ELSE r.rolname END ORDER BY CASE WHEN q.role_oid=0 THEN 'PUBLIC' ELSE r.rolname END)
    FROM pg_catalog.unnest(p.polroles) q(role_oid) LEFT JOIN pg_catalog.pg_roles r ON r.oid=q.role_oid),'[]'::jsonb),
  'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid,false),
  'withCheck',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,false))
 FROM pg_catalog.pg_policy p
 JOIN pg_catalog.pg_class c ON c.oid=p.polrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'sequence_definition',jsonb_build_object(
  'schema',n.nspname,'sequence',c.relname,'owner',o.rolname,'persistence',c.relpersistence::text,
  'type',pg_catalog.format_type(s.seqtypid,NULL),'start',s.seqstart,'increment',s.seqincrement,
  'maximum',s.seqmax,'minimum',s.seqmin,'cache',s.seqcache,'cycle',s.seqcycle,
  'ownedBy',(
    SELECT jsonb_build_object('schema',rn.nspname,'relation',rc.relname,'column',a.attname,'dependencyType',dep.deptype::text)
    FROM pg_catalog.pg_depend dep
    JOIN pg_catalog.pg_class rc ON rc.oid=dep.refobjid
    JOIN pg_catalog.pg_namespace rn ON rn.oid=rc.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=rc.oid AND a.attnum=dep.refobjsubid
    WHERE dep.classid='pg_catalog.pg_class'::regclass AND dep.objid=c.oid
      AND dep.refclassid='pg_catalog.pg_class'::regclass AND dep.deptype IN('a','i')
    ORDER BY rn.nspname,rc.relname,a.attname LIMIT 1),
  'aclIsNull',c.relacl IS NULL,'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable)
 FROM pg_catalog.pg_sequence s
 JOIN pg_catalog.pg_class c ON c.oid=s.seqrelid
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_catalog.pg_roles o ON o.oid=c.relowner
 LEFT JOIN LATERAL pg_catalog.aclexplode(c.relacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public'
 UNION ALL
 SELECT 'type_security',jsonb_build_object(
  'schema',n.nspname,'type',t.typname,'kind',t.typtype::text,'category',t.typcategory::text,
  'owner',o.rolname,'notNull',t.typnotnull,'default',t.typdefault,
  'collationSchema',cn.nspname,'collation',coll.collname,
  'aclIsNull',t.typacl IS NULL,'grantee',CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE g.rolname END,
  'grantor',go.rolname,'privilege',x.privilege_type,'grantable',x.is_grantable,
  'enumLabels',COALESCE((SELECT jsonb_agg(e.enumlabel ORDER BY e.enumsortorder) FROM pg_catalog.pg_enum e WHERE e.enumtypid=t.oid),'[]'::jsonb))
 FROM pg_catalog.pg_type t
 JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
 JOIN pg_catalog.pg_roles o ON o.oid=t.typowner
 LEFT JOIN pg_catalog.pg_collation coll ON coll.oid=t.typcollation
 LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid=coll.collnamespace
 LEFT JOIN LATERAL pg_catalog.aclexplode(t.typacl) x ON true
 LEFT JOIN pg_catalog.pg_roles g ON g.oid=x.grantee
 LEFT JOIN pg_catalog.pg_roles go ON go.oid=x.grantor
 WHERE n.nspname='public' AND t.typtype IN('b','c','d','e','r','m')
 UNION ALL
 SELECT 'extension_security',jsonb_build_object(
  'extension',e.extname,'owner',o.rolname,'version',e.extversion,
  'relocatable',e.extrelocatable,'schema',n.nspname)
 FROM pg_catalog.pg_extension e
 JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
 JOIN pg_catalog.pg_roles o ON o.oid=e.extowner
)
SELECT 'b64-catalog-security-fingerprint.v2' AS coverage_version,s.section,
 count(e.item) AS entry_count,
 pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(COALESCE(
   pg_catalog.jsonb_agg(e.item ORDER BY e.item) FILTER (WHERE e.item IS NOT NULL),'[]'::jsonb)::text,'UTF8')),'hex') AS sha256
FROM sections s LEFT JOIN entries e USING (section)
GROUP BY s.section ORDER BY s.section;
