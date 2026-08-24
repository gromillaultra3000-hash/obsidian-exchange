#!/usr/bin/env python3
"""Verify the production PostgreSQL 001-023 runtime privilege matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from load_sqlite_snapshot import PRODUCTION_TABLE_ORDER


ROLE_MIGRATOR = "obsidian_migrator"
ROLE_APP = "obsidian_app"
ROLE_READONLY = "obsidian_readonly"
ROLE_PAYOUT = "obsidian_payout"
ROLES = (ROLE_MIGRATOR, ROLE_APP, ROLE_READONLY, ROLE_PAYOUT)
EXPECTED_ROLE_LIMITS = {
    ROLE_MIGRATOR: 2,
    ROLE_APP: 60,
    ROLE_READONLY: 10,
    ROLE_PAYOUT: 4,
}
EXPECTED_ROLE_SETTINGS = {
    ROLE_MIGRATOR: {"search_path": "public, pg_catalog"},
    ROLE_APP: {
        "search_path": "public, pg_catalog",
        "statement_timeout": "15s",
        "lock_timeout": "3s",
        "idle_in_transaction_session_timeout": "30s",
    },
    ROLE_READONLY: {
        "search_path": "public, pg_catalog",
        "default_transaction_read_only": "on",
        "statement_timeout": "15s",
        "lock_timeout": "3s",
        "idle_in_transaction_session_timeout": "30s",
    },
    ROLE_PAYOUT: {
        "search_path": "public, pg_catalog",
        "statement_timeout": "30s",
        "lock_timeout": "5s",
        "idle_in_transaction_session_timeout": "30s",
    },
}

READONLY_TABLES = set(PRODUCTION_TABLE_ORDER)
PAYOUT_TABLES = {"payout_intents", "referral_payout_intents"}
PAYOUT_UPDATE_COLUMNS = {
    "state",
    "attempts",
    "txid",
    "error_code",
    "claimed_at",
    "finished_at",
    "updated_at",
}
PAYOUT_FUNCTIONS = {
    "claim_next_order_payout()",
    "claim_next_referral_payout()",
}
EXPECTED_SEQUENCES = {
    "admin_log_id_seq",
    "audit_log_id_seq",
    "bot_notification_jobs_id_seq",
    "dca_schedules_id_seq",
    "gift_vouchers_id_seq",
    "limit_orders_id_seq",
    "notification_outbox_id_seq",
    "order_lifecycle_work_id_seq",
    "orders_order_id_seq",
    "payment_notification_outbox_id_seq",
    "payment_sessions_id_seq",
    "payment_transition_audit_id_seq",
    "payout_intent_audit_id_seq",
    "payout_intents_id_seq",
    "payout_queue_id_seq",
    "promo_codes_id_seq",
    "rate_locks_id_seq",
    "referral_bonuses_id_seq",
    "referral_payout_intent_audit_id_seq",
    "referral_payout_intents_id_seq",
    "reviews_id_seq",
    "risk_events_id_seq",
    "sell_orders_id_seq",
    "sell_settlement_outbox_id_seq",
    "support_messages_id_seq",
    "support_tickets_id_seq",
    "swap_sessions_id_seq",
    "wallet_send_intents_id_seq",
    "web_users_id_seq",
}


def _one(cur: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
    cur.execute(query, params)
    return cur.fetchone()[0]


def _table_privilege(cur: Any, role: str, table: str, privilege: str) -> bool:
    return bool(_one(
        cur,
        "SELECT has_table_privilege(%s,%s::regclass,%s)",
        (role, f"public.{table}", privilege),
    ))


def _column_privilege(
    cur: Any, role: str, table: str, column: str, privilege: str
) -> bool:
    return bool(_one(
        cur,
        "SELECT has_column_privilege(%s,%s::regclass,%s,%s)",
        (role, f"public.{table}", column, privilege),
    ))


def inspect(dsn: str) -> dict[str, Any]:
    import psycopg

    violations: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
            "rolbypassrls,rolcanlogin,rolconnlimit,COALESCE(rolconfig,'{}') "
            "FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname",
            (list(ROLES),),
        )
        role_rows = {row[0]: row[1:] for row in cur.fetchall()}
        for role in ROLES:
            if role not in role_rows:
                violations.append(f"missing_role:{role}")
                continue
            elevated = role_rows[role][:5]
            can_login = role_rows[role][5]
            if any(elevated):
                violations.append(f"elevated_role:{role}")
            if not can_login:
                violations.append(f"role_not_login:{role}")
            connection_limit = role_rows[role][6]
            if connection_limit != EXPECTED_ROLE_LIMITS[role]:
                violations.append(
                    f"role_connection_limit:{role}:{connection_limit}:"
                    f"{EXPECTED_ROLE_LIMITS[role]}"
                )
            settings = dict(
                item.split("=", 1) for item in (role_rows[role][7] or [])
            )
            if settings != EXPECTED_ROLE_SETTINGS[role]:
                violations.append(
                    f"role_settings:{role}:" +
                    json.dumps(settings, sort_keys=True)
                )

        cur.execute(
            "SELECT granted.rolname,member.rolname FROM pg_auth_members m "
            "JOIN pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_roles member ON member.oid=m.member "
            "WHERE granted.rolname=ANY(%s) OR member.rolname=ANY(%s) "
            "ORDER BY granted.rolname,member.rolname",
            (list(ROLES), list(ROLES)),
        )
        for granted_role, member_role in cur.fetchall():
            violations.append(
                f"role_membership:{granted_role}:{member_role}"
            )

        cur.execute(
            "SELECT d.defaclnamespace,a.grantee,a.privilege_type,a.is_grantable "
            "FROM pg_default_acl d JOIN pg_roles r ON r.oid=d.defaclrole "
            "CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
            "WHERE r.rolname=%s AND d.defaclobjtype='f' "
            "ORDER BY d.defaclnamespace,a.grantee,a.privilege_type,a.is_grantable",
            (ROLE_MIGRATOR,),
        )
        function_defaults = cur.fetchall()
        migrator_oid = _one(
            cur, "SELECT oid FROM pg_roles WHERE rolname=%s", (ROLE_MIGRATOR,)
        )
        if function_defaults != [(0, migrator_oid, "EXECUTE", False)]:
            violations.append(
                "default_function_acl:" + json.dumps(function_defaults)
            )

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname"
        )
        tables = [row[0] for row in cur.fetchall()]
        expected_tables = set(PRODUCTION_TABLE_ORDER)
        if set(tables) != expected_tables:
            violations.append(
                "table_inventory:" +
                json.dumps({
                    "missing": sorted(expected_tables - set(tables)),
                    "unexpected": sorted(set(tables) - expected_tables),
                }, sort_keys=True)
            )

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='S' ORDER BY c.relname"
        )
        sequences = [row[0] for row in cur.fetchall()]
        if set(sequences) != EXPECTED_SEQUENCES:
            violations.append(
                "sequence_inventory:" +
                json.dumps({
                    "missing": sorted(EXPECTED_SEQUENCES - set(sequences)),
                    "unexpected": sorted(set(sequences) - EXPECTED_SEQUENCES),
                }, sort_keys=True)
            )

        cur.execute(
            "SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' ORDER BY 1"
        )
        functions = [row[0] for row in cur.fetchall()]
        if set(functions) != PAYOUT_FUNCTIONS:
            violations.append(
                "function_inventory:" +
                json.dumps({
                    "missing": sorted(PAYOUT_FUNCTIONS - set(functions)),
                    "unexpected": sorted(set(functions) - PAYOUT_FUNCTIONS),
                }, sort_keys=True)
            )

        owner_checks = [
            ("database", _one(
                cur,
                "SELECT pg_get_userbyid(datdba) FROM pg_database "
                "WHERE datname=current_database()",
            )),
            ("schema", _one(
                cur,
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                "WHERE nspname='public'",
            )),
        ]
        cur.execute(
            "SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','S')"
        )
        owner_checks.extend((f"relation:{name}", owner) for name, owner in cur.fetchall())
        cur.execute(
            "SELECT p.proname,pg_get_userbyid(p.proowner) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'"
        )
        owner_checks.extend((f"function:{name}", owner) for name, owner in cur.fetchall())
        for object_name, owner in owner_checks:
            if owner != ROLE_MIGRATOR:
                violations.append(f"wrong_owner:{object_name}:{owner}")

        for table in tables:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if not _table_privilege(cur, ROLE_APP, table, privilege):
                    violations.append(f"app_missing:{table}:{privilege}")
            for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                if _table_privilege(cur, ROLE_APP, table, privilege):
                    violations.append(f"app_excess:{table}:{privilege}")

            readonly_should_select = table in READONLY_TABLES
            if _table_privilege(cur, ROLE_READONLY, table, "SELECT") != readonly_should_select:
                violations.append(f"readonly_select:{table}:{readonly_should_select}")
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                if _table_privilege(cur, ROLE_READONLY, table, privilege):
                    violations.append(f"readonly_excess:{table}:{privilege}")

            payout_should_select = table in PAYOUT_TABLES
            if _table_privilege(cur, ROLE_PAYOUT, table, "SELECT") != payout_should_select:
                violations.append(f"payout_select:{table}:{payout_should_select}")
            for privilege in ("INSERT", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                if _table_privilege(cur, ROLE_PAYOUT, table, privilege):
                    violations.append(f"payout_excess:{table}:{privilege}")

        for table in PAYOUT_TABLES:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
            for (column,) in cur.fetchall():
                expected = column in PAYOUT_UPDATE_COLUMNS
                actual = _column_privilege(cur, ROLE_PAYOUT, table, column, "UPDATE")
                if actual != expected:
                    violations.append(f"payout_update:{table}:{column}:{expected}")

        for sequence in sequences:
            for privilege in ("SELECT", "UPDATE"):
                if _one(
                    cur,
                    "SELECT has_sequence_privilege(%s,%s::regclass,%s)",
                    (ROLE_APP, f"public.{sequence}", privilege),
                ):
                    violations.append(f"app_sequence_excess:{sequence}:{privilege}")
            if not _one(
                cur,
                "SELECT has_sequence_privilege(%s,%s::regclass,'USAGE')",
                (ROLE_APP, f"public.{sequence}"),
            ):
                violations.append(f"app_sequence_missing:{sequence}:USAGE")
            for role in (ROLE_READONLY, ROLE_PAYOUT):
                for privilege in ("USAGE", "SELECT", "UPDATE"):
                    if _one(
                        cur,
                        "SELECT has_sequence_privilege(%s,%s::regclass,%s)",
                        (role, f"public.{sequence}", privilege),
                    ):
                        violations.append(f"sequence_excess:{role}:{sequence}:{privilege}")

        for function in functions:
            for role in (ROLE_APP, ROLE_READONLY):
                if _one(
                    cur,
                    "SELECT has_function_privilege(%s,%s::regprocedure,'EXECUTE')",
                    (role, f"public.{function}"),
                ):
                    violations.append(f"function_excess:{role}:{function}")
            expected = function in PAYOUT_FUNCTIONS
            actual = bool(_one(
                cur,
                "SELECT has_function_privilege(%s,%s::regprocedure,'EXECUTE')",
                (ROLE_PAYOUT, f"public.{function}"),
            ))
            if actual != expected:
                violations.append(f"payout_function:{function}:{expected}")

        for role in (ROLE_APP, ROLE_READONLY, ROLE_PAYOUT):
            if not _one(
                cur,
                "SELECT has_database_privilege(%s,current_database(),'CONNECT')",
                (role,),
            ):
                violations.append(f"database_connect_missing:{role}")
            if _one(
                cur,
                "SELECT has_database_privilege(%s,current_database(),'TEMPORARY')",
                (role,),
            ):
                violations.append(f"database_temp_excess:{role}")
            if not _one(
                cur,
                "SELECT has_schema_privilege(%s,'public','USAGE')",
                (role,),
            ):
                violations.append(f"schema_usage_missing:{role}")
            if _one(
                cur,
                "SELECT has_schema_privilege(%s,'public','CREATE')",
                (role,),
            ):
                violations.append(f"schema_create_excess:{role}")

        public_acl_queries = {
            "database": (
                "SELECT count(*) FROM pg_database d CROSS JOIN LATERAL "
                "aclexplode(COALESCE(d.datacl,acldefault('d',d.datdba))) a "
                "WHERE d.datname=current_database() AND a.grantee=0"
            ),
            "schema": (
                "SELECT count(*) FROM pg_namespace n CROSS JOIN LATERAL "
                "aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a "
                "WHERE n.nspname='public' AND a.grantee=0"
            ),
            "relations": (
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace CROSS JOIN LATERAL "
                "aclexplode(COALESCE(c.relacl,acldefault(CASE WHEN c.relkind='S' "
                "THEN 'S'::\"char\" ELSE 'r'::\"char\" END,c.relowner))) a "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p','S') "
                "AND a.grantee=0"
            ),
            "functions": (
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid=p.pronamespace CROSS JOIN LATERAL "
                "aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a "
                "WHERE n.nspname='public' AND a.grantee=0"
            ),
        }
        for scope, query in public_acl_queries.items():
            if _one(cur, query):
                violations.append(f"public_acl:{scope}")

    return {
        "status": "match" if not violations else "mismatch",
        "violations": violations,
        "inventory": {
            "tables": len(tables),
            "sequences": len(sequences),
            "functions": len(functions),
            "readonly_tables": len(READONLY_TABLES),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = inspect(args.postgres)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "match" else 2


if __name__ == "__main__":
    raise SystemExit(main())
