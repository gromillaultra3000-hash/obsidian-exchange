\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned
-- Emits only table name, row count and SHA-256; never emits row values.
SELECT format(
 'SELECT %L,count(*),encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::text,chr(10) ORDER BY to_jsonb(t)::text),''''),''UTF8'')),''hex'') FROM %I.%I t;',
 c.relname,n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN('r','p')
ORDER BY c.relname
\gexec
