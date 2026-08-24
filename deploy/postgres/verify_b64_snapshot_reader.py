#!/usr/bin/env python3
"""Verify the exact frozen-001-023 B64 snapshot-reader role contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from load_sqlite_snapshot import PRODUCTION_TABLE_ORDER
from verify_runtime_privileges import EXPECTED_SEQUENCES, PAYOUT_FUNCTIONS


ROLE = "obsidian_b64_snapshot_reader"
MIGRATOR = "obsidian_migrator"
EXPECTED_SETTINGS = {
    "search_path": "pg_catalog",
    "default_transaction_read_only": "on",
    "default_transaction_isolation": "repeatable read",
    "statement_timeout": "180s",
    "lock_timeout": "5s",
    "idle_in_transaction_session_timeout": "210s",
    "row_security": "off",
}
TABLE_PRIVILEGES = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES",
    "TRIGGER", "MAINTAIN",
)
SEQUENCE_PRIVILEGES = ("SELECT", "USAGE", "UPDATE")
PROFILE = "FROZEN_001_023_SOURCE_PROFILE"
PROFILE_INVENTORY = {
    "tables": sorted(PRODUCTION_TABLE_ORDER),
    "sequences": sorted(EXPECTED_SEQUENCES),
    "functions": sorted(PAYOUT_FUNCTIONS),
}
PROFILE_INVENTORY_SHA256 = hashlib.sha256(json.dumps(
    PROFILE_INVENTORY, sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()
PROFILE_COLUMN_COUNT = 423
PROFILE_COLUMN_CATALOG_SHA256 = \
    "adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99"
EXPECTED_HBA_RULES = [
    (1, "local", ["all"], [ROLE], None, None, "reject"),
    (2, "local", ["replication"], [ROLE], None, None, "reject"),
    (3, "host", ["obsidian_exchange"], [ROLE], "127.0.0.1",
     "255.255.255.255", "scram-sha-256"),
    (4, "host", ["replication"], [ROLE], "0.0.0.0", "0.0.0.0",
     "reject"),
    (5, "host", ["replication"], [ROLE], "::", "::", "reject"),
    (6, "host", ["all"], [ROLE], "0.0.0.0", "0.0.0.0", "reject"),
    (7, "host", ["all"], [ROLE], "::", "::", "reject"),
]


def _one(cur: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
    cur.execute(query, params)
    return cur.fetchone()[0]


def _acl_rows(cur: Any, query: str, params: tuple[Any, ...]) \
        -> list[tuple[str, bool]]:
    cur.execute(query, params)
    return [(row[0], bool(row[1])) for row in cur.fetchall()]


def inspect(dsn: str, *, expected_login: bool = False) -> dict[str, Any]:
    import psycopg

    violations: list[str] = []
    tables: list[str] = []
    sequences: list[str] = []
    functions: list[str] = []
    other_schemas: list[str] = []
    hba_exact = False
    hba_file_sha256: str | None = None

    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL search_path=pg_catalog")
        cur.execute("SET LOCAL statement_timeout='15s'")
        cur.execute("SET LOCAL lock_timeout='3s'")
        cur.execute(
            "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolinherit,"
            "rolcanlogin,rolreplication,rolconnlimit,rolbypassrls,"
            "COALESCE(rolconfig,'{}'),"
            "(SELECT rolpassword IS NULL FROM pg_authid WHERE oid=pg_roles.oid),"
            "(SELECT COALESCE(rolvaliduntil::text,'') FROM pg_authid "
            "WHERE oid=pg_roles.oid) "
            "FROM pg_roles WHERE rolname=%s",
            (ROLE,),
        )
        role_row = cur.fetchone()
        if role_row is None:
            return {
                "status": "mismatch",
                "violations": [f"missing_role:{ROLE}"],
                "inventory": {
                    "tables": 0, "sequences": 0, "functions": 0,
                    "otherUserSchemas": 0,
                },
            }

        role_oid = role_row[0]
        deployment_comment = _one(
            cur, "SELECT shobj_description(%s,'pg_authid')", (role_oid,)
        )
        comment_match = re.fullmatch(
            r"obsidian-b64-snapshot-reader-dormant-v1:([0-9a-f]{32})",
            deployment_comment or "",
        )
        if comment_match is None:
            violations.append("deployment_binding_missing")
        elevated = role_row[1:4] + role_row[6:7] + role_row[8:9]
        if any(elevated):
            violations.append("elevated_role")
        if role_row[4] is not False:
            violations.append("role_inherit_enabled")
        if role_row[5] is not expected_login:
            violations.append(
                "role_login_state:" + ("enabled" if role_row[5] else "disabled")
            )
        if role_row[7] != 2:
            violations.append(f"role_connection_limit:{role_row[7]}:2")
        settings = dict(item.split("=", 1) for item in (role_row[9] or []))
        if settings != EXPECTED_SETTINGS:
            violations.append(
                "role_settings:" + json.dumps(settings, sort_keys=True)
            )
        credential_absent = (
            role_row[10] is True and role_row[11] in {"", "infinity"}
        )

        database_settings = _one(
            cur,
            "SELECT count(*) FROM pg_db_role_setting "
            "WHERE setrole=%s AND setdatabase<>0",
            (role_oid,),
        )
        if database_settings:
            violations.append(f"per_database_role_settings:{database_settings}")

        cur.execute(
            "SELECT granted.rolname,member.rolname FROM pg_auth_members m "
            "JOIN pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_roles member ON member.oid=m.member "
            "WHERE m.roleid=%s OR m.member=%s "
            "ORDER BY granted.rolname,member.rolname",
            (role_oid, role_oid),
        )
        for granted, member in cur.fetchall():
            violations.append(f"role_membership:{granted}:{member}")

        owned = _one(
            cur,
            "SELECT count(*) FROM pg_shdepend WHERE refclassid='pg_authid'::regclass "
            "AND refobjid=%s AND deptype='o'",
            (role_oid,),
        )
        if owned:
            violations.append(f"owned_objects:{owned}")

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p') ORDER BY c.relname"
        )
        tables = [row[0] for row in cur.fetchall()]
        expected_tables = set(PRODUCTION_TABLE_ORDER)
        if set(tables) != expected_tables:
            violations.append("table_inventory:" + json.dumps({
                "missing": sorted(expected_tables - set(tables)),
                "unexpected": sorted(set(tables) - expected_tables),
            }, sort_keys=True))
        cur.execute(
            "SELECT count(*),encode(sha256(convert_to(COALESCE(jsonb_agg("
            "jsonb_build_object('table',c.relname,'column',a.attname,"
            "'number',a.attnum,'type',format_type(a.atttypid,a.atttypmod),"
            "'notNull',a.attnotnull,'identity',a.attidentity::text,"
            "'generated',a.attgenerated::text,'default',"
            "pg_get_expr(d.adbin,d.adrelid,false),'collation',CASE WHEN "
            "a.attcollation=0 THEN NULL ELSE cn.nspname||'.'||coll.collname END) "
            "ORDER BY c.relname COLLATE \"C\",a.attnum),'[]'::jsonb)::text,"
            "'UTF8')),'hex') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid=c.oid LEFT JOIN pg_attrdef d "
            "ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
            "LEFT JOIN pg_collation coll ON coll.oid=a.attcollation "
            "LEFT JOIN pg_namespace cn ON cn.oid=coll.collnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
            "AND a.attnum>0 AND NOT a.attisdropped"
        )
        column_count, column_catalog_sha256 = cur.fetchone()
        if (column_count != PROFILE_COLUMN_COUNT
                or column_catalog_sha256 != PROFILE_COLUMN_CATALOG_SHA256):
            violations.append(
                f"column_catalog:{column_count}:{column_catalog_sha256}"
            )

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind='S' ORDER BY c.relname"
        )
        sequences = [row[0] for row in cur.fetchall()]
        if set(sequences) != EXPECTED_SEQUENCES:
            violations.append("sequence_inventory:" + json.dumps({
                "missing": sorted(EXPECTED_SEQUENCES - set(sequences)),
                "unexpected": sorted(set(sequences) - EXPECTED_SEQUENCES),
            }, sort_keys=True))

        cur.execute(
            "SELECT p.proname || '(' || "
            "pg_get_function_identity_arguments(p.oid) || ')' "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' ORDER BY 1"
        )
        functions = [row[0] for row in cur.fetchall()]
        if set(functions) != PAYOUT_FUNCTIONS:
            violations.append("function_inventory:" + json.dumps({
                "missing": sorted(PAYOUT_FUNCTIONS - set(functions)),
                "unexpected": sorted(set(functions) - PAYOUT_FUNCTIONS),
            }, sort_keys=True))

        unexpected_relations = _one(
            cur,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('v','m','f')",
        )
        if unexpected_relations:
            violations.append(
                f"unexpected_public_relations:{unexpected_relations}"
            )
        rls_tables = _one(
            cur,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p') AND c.relrowsecurity",
        )
        if rls_tables:
            violations.append(f"rls_tables:{rls_tables}")
        large_objects = _one(cur, "SELECT count(*) FROM pg_largeobject_metadata")
        if large_objects:
            violations.append(f"large_objects:{large_objects}")

        owner_queries = (
            ("database", "SELECT pg_get_userbyid(datdba) FROM pg_database "
             "WHERE datname=current_database()"),
            ("schema", "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
             "WHERE nspname='public'"),
        )
        for label, query in owner_queries:
            owner = _one(cur, query)
            if owner != MIGRATOR:
                violations.append(f"wrong_owner:{label}:{owner}")
        cur.execute(
            "SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','S')"
        )
        for name, owner in cur.fetchall():
            if owner != MIGRATOR:
                violations.append(f"wrong_owner:relation:{name}:{owner}")
        cur.execute(
            "SELECT p.proname,pg_get_userbyid(p.proowner) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public'"
        )
        for name, owner in cur.fetchall():
            if owner != MIGRATOR:
                violations.append(f"wrong_owner:function:{name}:{owner}")

        if not _one(
            cur, "SELECT has_database_privilege(%s,current_database(),'CONNECT')",
            (ROLE,),
        ):
            violations.append("database_connect_missing")
        for privilege in ("CREATE", "TEMPORARY"):
            if _one(
                cur,
                "SELECT has_database_privilege(%s,current_database(),%s)",
                (ROLE, privilege),
            ):
                violations.append(f"database_excess:{privilege}")
        if not _one(
            cur, "SELECT has_schema_privilege(%s,'public','USAGE')", (ROLE,)
        ):
            violations.append("schema_usage_missing")
        if _one(
            cur, "SELECT has_schema_privilege(%s,'public','CREATE')", (ROLE,)
        ):
            violations.append("schema_create_excess")

        database_acl = _acl_rows(
            cur,
            "SELECT a.privilege_type,a.is_grantable FROM pg_database d "
            "CROSS JOIN LATERAL aclexplode(d.datacl) a "
            "WHERE d.datname=current_database() AND a.grantee=%s "
            "ORDER BY a.privilege_type",
            (role_oid,),
        )
        if database_acl != [("CONNECT", False)]:
            violations.append("database_direct_acl:" + json.dumps(database_acl))
        schema_acl = _acl_rows(
            cur,
            "SELECT a.privilege_type,a.is_grantable FROM pg_namespace n "
            "CROSS JOIN LATERAL aclexplode(n.nspacl) a "
            "WHERE n.nspname='public' AND a.grantee=%s "
            "ORDER BY a.privilege_type",
            (role_oid,),
        )
        if schema_acl != [("USAGE", False)]:
            violations.append("schema_direct_acl:" + json.dumps(schema_acl))

        for table in tables:
            for privilege in TABLE_PRIVILEGES:
                actual = bool(_one(
                    cur,
                    "SELECT has_table_privilege(%s,%s::regclass,%s)",
                    (ROLE, f"public.{table}", privilege),
                ))
                if actual != (privilege == "SELECT"):
                    violations.append(
                        f"table_privilege:{table}:{privilege}:{actual}"
                    )
            direct = _acl_rows(
                cur,
                "SELECT a.privilege_type,a.is_grantable FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "CROSS JOIN LATERAL aclexplode(c.relacl) a "
                "WHERE n.nspname='public' AND c.relname=%s "
                "AND c.relkind IN ('r','p') AND a.grantee=%s "
                "ORDER BY a.privilege_type",
                (table, role_oid),
            )
            if direct != [("SELECT", False)]:
                violations.append(
                    f"table_direct_acl:{table}:" + json.dumps(direct)
                )
            cur.execute(
                "SELECT a.attname FROM pg_attribute a "
                "WHERE a.attrelid=%s::regclass AND a.attnum>0 "
                "AND NOT a.attisdropped ORDER BY a.attnum",
                (f"public.{table}",),
            )
            for (column,) in cur.fetchall():
                for privilege in ("INSERT", "UPDATE", "REFERENCES"):
                    if _one(
                        cur,
                        "SELECT has_column_privilege(%s,%s::regclass,%s,%s)",
                        (ROLE, f"public.{table}", column, privilege),
                    ):
                        violations.append(
                            f"column_privilege:{table}:{column}:{privilege}"
                        )
            direct_columns = _one(
                cur,
                "SELECT count(*) FROM pg_attribute a "
                "CROSS JOIN LATERAL aclexplode(a.attacl) acl "
                "WHERE a.attrelid=%s::regclass AND a.attnum>0 "
                "AND NOT a.attisdropped AND acl.grantee=%s",
                (f"public.{table}", role_oid),
            )
            if direct_columns:
                violations.append(
                    f"column_direct_acl:{table}:{direct_columns}"
                )

        for sequence in sequences:
            for privilege in SEQUENCE_PRIVILEGES:
                actual = bool(_one(
                    cur,
                    "SELECT has_sequence_privilege(%s,%s::regclass,%s)",
                    (ROLE, f"public.{sequence}", privilege),
                ))
                if actual != (privilege == "SELECT"):
                    violations.append(
                        f"sequence_privilege:{sequence}:{privilege}:{actual}"
                    )
            direct = _acl_rows(
                cur,
                "SELECT a.privilege_type,a.is_grantable FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "CROSS JOIN LATERAL aclexplode(c.relacl) a "
                "WHERE n.nspname='public' AND c.relname=%s "
                "AND c.relkind='S' AND a.grantee=%s "
                "ORDER BY a.privilege_type",
                (sequence, role_oid),
            )
            if direct != [("SELECT", False)]:
                violations.append(
                    f"sequence_direct_acl:{sequence}:" + json.dumps(direct)
                )

        for function in functions:
            if _one(
                cur,
                "SELECT has_function_privilege(%s,%s::regprocedure,'EXECUTE')",
                (ROLE, f"public.{function}"),
            ):
                violations.append(f"function_execute:{function}")

        default_grants = _one(
            cur,
            "SELECT count(*) FROM pg_default_acl d "
            "CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
            "WHERE a.grantee=%s",
            (role_oid,),
        )
        if default_grants:
            violations.append(f"default_acl_grants:{default_grants}")
        other_database_grants = _one(
            cur,
            "SELECT count(*) FROM pg_database d "
            "CROSS JOIN LATERAL aclexplode(d.datacl) a "
            "WHERE d.datname<>current_database() AND a.grantee=%s",
            (role_oid,),
        )
        if other_database_grants:
            violations.append(
                f"other_database_direct_grants:{other_database_grants}"
            )
        cur.execute(
            "SELECT datname,"
            "has_database_privilege(%s,datname,'CONNECT'),"
            "has_database_privilege(%s,datname,'CREATE'),"
            "has_database_privilege(%s,datname,'TEMPORARY') "
            "FROM pg_database WHERE datname<>current_database() "
            "AND datallowconn ORDER BY datname",
            (ROLE, ROLE, ROLE),
        )
        ambient_database_privileges = [
            {"database": name, "connect": bool(connect),
             "create": bool(create), "temporary": bool(temporary)}
            for name, connect, create, temporary in cur.fetchall()
            if connect or create or temporary
        ]

        cur.execute(
            "SELECT rule_number,type,database,user_name,address,netmask,"
            "auth_method,error FROM pg_hba_file_rules ORDER BY rule_number"
        )
        hba_rows = cur.fetchall()
        hba_errors = [
            {"ruleNumber": row[0], "error": row[7]}
            for row in hba_rows if row[7] is not None
        ]
        if hba_errors:
            violations.append(
                "hba_file_errors:" + json.dumps(hba_errors, sort_keys=True)
            )
        role_hba_rows = [
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6])
            for row in hba_rows
            if row[3] is not None and ROLE in row[3]
        ]
        hba_exact = role_hba_rows == EXPECTED_HBA_RULES
        hba_file_sha256 = _one(
            cur,
            "SELECT encode(sha256(pg_read_binary_file("
            "current_setting('hba_file'))),'hex')",
        )

        cur.execute(
            "SELECT oid,nspname FROM pg_namespace "
            "WHERE nspname<>'public' AND nspname<>'information_schema' "
            "AND nspname!~'^pg_' ORDER BY nspname"
        )
        other_schema_rows = cur.fetchall()
        other_schemas = [row[1] for row in other_schema_rows]
        for schema_oid, schema_name in other_schema_rows:
            for privilege in ("USAGE", "CREATE"):
                if _one(
                    cur, "SELECT has_schema_privilege(%s,%s,%s)",
                    (ROLE, schema_oid, privilege),
                ):
                    violations.append(
                        f"other_schema_privilege:{schema_name}:{privilege}"
                    )
            cur.execute(
                "SELECT c.oid,c.relname,c.relkind FROM pg_class c "
                "WHERE c.relnamespace=%s AND c.relkind IN "
                "('r','p','v','m','f','S') ORDER BY c.relname",
                (schema_oid,),
            )
            for object_oid, object_name, kind in cur.fetchall():
                privileges = (SEQUENCE_PRIVILEGES if kind == "S"
                              else TABLE_PRIVILEGES)
                function_name = ("has_sequence_privilege" if kind == "S"
                                 else "has_table_privilege")
                for privilege in privileges:
                    if _one(
                        cur, f"SELECT {function_name}(%s,%s,%s)",
                        (ROLE, object_oid, privilege),
                    ):
                        violations.append(
                            f"other_relation_privilege:{schema_name}."
                            f"{object_name}:{privilege}"
                        )
                if kind != "S":
                    cur.execute(
                        "SELECT attname FROM pg_attribute WHERE attrelid=%s "
                        "AND attnum>0 AND NOT attisdropped ORDER BY attnum",
                        (object_oid,),
                    )
                    for (column,) in cur.fetchall():
                        for privilege in (
                            "SELECT", "INSERT", "UPDATE", "REFERENCES"
                        ):
                            if _one(
                                cur,
                                "SELECT has_column_privilege(%s,%s,%s,%s)",
                                (ROLE, object_oid, column, privilege),
                            ):
                                violations.append(
                                    f"other_column_privilege:{schema_name}."
                                    f"{object_name}:{column}:{privilege}"
                                )
            cur.execute(
                "SELECT oid,proname FROM pg_proc WHERE pronamespace=%s "
                "ORDER BY proname", (schema_oid,)
            )
            for function_oid, function_name in cur.fetchall():
                if _one(
                    cur,
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                    (ROLE, function_oid),
                ):
                    violations.append(
                        f"other_function_execute:{schema_name}.{function_name}"
                    )

    activation_blockers = []
    if not role_row[5]:
        activation_blockers.append("LOGIN_DISABLED")
    if not credential_absent:
        activation_blockers.append("CREDENTIAL_STATE_PRESENT_UNATTESTED")
    else:
        activation_blockers.append("CREDENTIAL_NOT_ISSUED")
    if ambient_database_privileges and not hba_exact:
        activation_blockers.append("OTHER_DATABASE_PUBLIC_ACL_OR_HBA_NOT_ISOLATED")
    if not hba_exact:
        activation_blockers.append("EXACT_HBA_FIRST_MATCH_NOT_ATTESTED")
    activation_blockers.append("TCP_SCRAM_EXPORTED_SNAPSHOT_NOT_REHEARSED")
    return {
        "status": "match" if not violations else "mismatch",
        "violations": sorted(violations),
        "role": ROLE,
        "profile": PROFILE,
        "profileInventorySha256": PROFILE_INVENTORY_SHA256,
        "inventory": {
            "tables": len(tables),
            "sequences": len(sequences),
            "functions": len(functions),
            "otherUserSchemas": len(other_schemas),
            "columns": column_count,
        },
        "columnCatalogSha256": column_catalog_sha256,
        "sequenceContract": {
            "select": True,
            "usage": False,
            "update": False,
            "reason": "PG_DUMP_READS_LAST_VALUE_AND_IS_CALLED",
        },
        "credentialState": "ABSENT" if credential_absent else "PRESENT",
        "deploymentNonce": comment_match.group(1) if comment_match else None,
        "loginState": "ENABLED" if role_row[5] else "DISABLED",
        "activationStatus": "READY" if not activation_blockers else "BLOCKED",
        "activationBlockers": activation_blockers,
        "ambientOtherDatabasePrivileges": ambient_database_privileges,
        "hbaIsolationStatus": "EXACT" if hba_exact else "MISSING_OR_DRIFTED",
        "hbaFileSha256": hba_file_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--expect-login", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = inspect(args.postgres, expected_login=args.expect_login)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "match" else 2


if __name__ == "__main__":
    raise SystemExit(main())
