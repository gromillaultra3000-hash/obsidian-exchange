#!/usr/bin/env python3
"""Bounded preflight/apply/verify/auto-rollback for the dormant B64 reader."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from verify_b64_snapshot_reader import (
    PROFILE,
    PROFILE_INVENTORY_SHA256,
    PROFILE_COLUMN_CATALOG_SHA256,
    PROFILE_COLUMN_COUNT,
    ROLE,
    inspect,
)


ROOT = Path(__file__).resolve().parents[2]
POSTGRES = ROOT / "deploy/postgres"
PLAN_PATH = ROOT / "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json"
PROVISION_PATH = POSTGRES / "provision_b64_snapshot_reader.sql"
ROLLBACK_PATH = POSTGRES / "rollback_b64_snapshot_reader.sql"
ARTIFACT_PATHS = {
    "runner": POSTGRES / "b64_064a_hardened_refresh.py",
    "dirtyScan": POSTGRES / "check_b64_notification_migration.py",
    "catalogFingerprintSql": POSTGRES / "b64_catalog_security_fingerprint.sql",
    "tableFingerprintSql": POSTGRES / "b64_table_fingerprint.sql",
    "catalogComparator": POSTGRES / "b64_compare_catalog_fingerprints.py",
    "tableComparator": POSTGRES / "b64_compare_table_fingerprints.py",
    "bootstrapRolesSql": POSTGRES / "bootstrap_roles.sql",
    "prepareDatabaseSql": POSTGRES / "prepare_database.sql",
    "runtimePrivilegesSql": POSTGRES / "runtime_privileges.sql",
    "snapshotReaderProvisionSql": PROVISION_PATH,
    "snapshotReaderRollbackSql": ROLLBACK_PATH,
    "snapshotReaderVerifier": POSTGRES / "verify_b64_snapshot_reader.py",
    "snapshotReaderDeployRunner": Path(__file__).resolve(),
    "snapshotReaderHbaManifest": POSTGRES / "b64_snapshot_reader_hba.v1.json",
    "snapshotReaderHbaDeployRunner": (
        POSTGRES / "deploy_b64_snapshot_reader_hba.py"
    ),
    "snapshotReaderRuntime": POSTGRES / "b64_snapshot_reader_runtime.py",
}
REQUIRED_DORMANT_BLOCKERS = {
    "LOGIN_DISABLED",
    "CREDENTIAL_NOT_ISSUED",
    "EXACT_HBA_FIRST_MATCH_NOT_ATTESTED",
    "TCP_SCRAM_EXPORTED_SNAPSHOT_NOT_REHEARSED",
}


class DeploymentError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_and_bind_plan() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "b64_064a_hardened_refresh", ARTIFACT_PATHS["runner"]
    )
    if spec is None or spec.loader is None:
        raise DeploymentError("RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        module.validate_plan(plan)
    except Exception as exc:
        raise DeploymentError("PLAN_VALIDATION_FAILED") from exc
    bindings = plan.get("artifactsSha256")
    if not isinstance(bindings, dict) or set(bindings) != set(ARTIFACT_PATHS):
        raise DeploymentError("PLAN_ARTIFACT_SET_MISMATCH")
    for key, path in ARTIFACT_PATHS.items():
        if bindings[key] != _sha256(path):
            raise DeploymentError(f"ARTIFACT_DIGEST_MISMATCH:{key}")
    return plan


def _inspect_container(name: str, expected_id: str, expected_image: str,
                       require_healthy: bool, dsn: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name):
        raise DeploymentError("INVALID_CONTAINER_NAME")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_id):
        raise DeploymentError("INVALID_EXPECTED_CONTAINER_ID")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image):
        raise DeploymentError("INVALID_EXPECTED_IMAGE_ID")
    template = (
        '{"Id":{{json .Id}},"Image":{{json .Image}},'
        '"Running":{{json .State.Running}},'
        '"Status":{{json .State.Status}},"Pid":{{json .State.Pid}},'
        '"Health":{{with (index .State "Health")}}'
        '{{json .Status}}{{else}}null{{end}},'
        '"Ports":{{json .NetworkSettings.Ports}}}'
    )
    result = subprocess.run(
        ["/usr/bin/docker", "inspect", f"--format={template}", name],
        capture_output=True, text=True, check=False, timeout=10,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if result.returncode != 0:
        raise DeploymentError("CONTAINER_INSPECT_FAILED")
    try:
        value = json.loads(result.stdout)
        container_id = value["Id"].removeprefix("sha256:")
        image_id = value["Image"]
        container_pid = value["Pid"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DeploymentError("INVALID_CONTAINER_INSPECTION") from exc
    if container_id != expected_id or image_id != expected_image:
        raise DeploymentError("CONTAINER_IDENTITY_MISMATCH")
    if value.get("Running") is not True or value.get("Status") != "running":
        raise DeploymentError("CONTAINER_NOT_RUNNING")
    if not isinstance(container_pid, int) or container_pid <= 0:
        raise DeploymentError("INVALID_CONTAINER_PID")
    health = value.get("Health")
    if require_healthy and health != "healthy":
        raise DeploymentError("CONTAINER_NOT_HEALTHY")

    connection = conninfo_to_dict(dsn)
    if connection.get("host") not in {"127.0.0.1", "localhost"}:
        raise DeploymentError("DSN_NOT_LOOPBACK_BOUND")
    if connection.get("hostaddr") not in {None, "127.0.0.1", "::1"}:
        raise DeploymentError("DSN_HOSTADDR_NOT_LOOPBACK_BOUND")
    port = str(connection.get("port", "5432"))
    bindings = value.get("Ports", {}).get("5432/tcp") or []
    if not any(item.get("HostIp") in {"127.0.0.1", "::1"}
               and item.get("HostPort") == port for item in bindings):
        raise DeploymentError("DSN_CONTAINER_PORT_BINDING_MISMATCH")
    return {
        "containerId": container_id,
        "imageId": image_id,
        "status": value["Status"],
        "health": health,
        "hostPort": int(port),
        "containerPid": container_pid,
    }


def _catalog_preflight(dsn: str, expected_database: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='15s'")
        cur.execute("SET LOCAL lock_timeout='3s'")
        cur.execute("SET LOCAL search_path=pg_catalog")
        cur.execute(
            "SELECT current_database(),current_setting('server_version_num')::int,"
            "pg_get_userbyid(datdba) FROM pg_database "
            "WHERE datname=current_database()"
        )
        database, version_num, database_owner = cur.fetchone()
        if database != expected_database:
            raise DeploymentError("DATABASE_IDENTITY_MISMATCH")
        if version_num // 10000 != 17:
            raise DeploymentError("SERVER_MAJOR_MISMATCH")
        if database_owner != "obsidian_migrator":
            raise DeploymentError("DATABASE_OWNER_MISMATCH")
        public_owner = cur.execute(
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
            "WHERE nspname='public'"
        ).fetchone()[0]
        if public_owner != "obsidian_migrator":
            raise DeploymentError("PUBLIC_SCHEMA_OWNER_MISMATCH")
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p') ORDER BY c.relname COLLATE \"C\""
        )
        tables = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind='S' ORDER BY c.relname COLLATE \"C\""
        )
        sequences = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT p.proname || '(' || "
            "pg_get_function_identity_arguments(p.oid) || ')' "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' ORDER BY p.proname COLLATE \"C\","
            "pg_get_function_identity_arguments(p.oid) COLLATE \"C\""
        )
        functions = [row[0] for row in cur.fetchall()]
        profile_digest = hashlib.sha256(json.dumps({
            "tables": tables,
            "sequences": sequences,
            "functions": functions,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if profile_digest != PROFILE_INVENTORY_SHA256:
            raise DeploymentError("FROZEN_PROFILE_MISMATCH")
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
            raise DeploymentError("FROZEN_COLUMN_CATALOG_MISMATCH")
        rls = cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p') AND c.relrowsecurity"
        ).fetchone()[0]
        large_objects = cur.execute(
            "SELECT count(*) FROM pg_largeobject_metadata"
        ).fetchone()[0]
        if rls or large_objects:
            raise DeploymentError("UNSUPPORTED_SOURCE_SECURITY_OBJECTS")
        role_exists = bool(cur.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname=%s", (ROLE,)
        ).fetchone()[0])
    return {
        "database": database,
        "serverVersionNum": version_num,
        "databaseOwner": database_owner,
        "publicSchemaOwner": public_owner,
        "profile": PROFILE,
        "profileInventorySha256": profile_digest,
        "tables": len(tables),
        "sequences": len(sequences),
        "functions": len(functions),
        "columns": column_count,
        "columnCatalogSha256": column_catalog_sha256,
        "rlsTables": rls,
        "largeObjects": large_objects,
        "roleAbsent": not role_exists,
    }


def _role_exists(dsn: str) -> bool:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        return bool(conn.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname=%s", (ROLE,)
        ).fetchone()[0])


def _validate_container_admin_dsn(dsn: str, expected_database: str,
                                  container_pid: int) -> None:
    ambient_libpq = sorted(
        key for key, value in os.environ.items()
        if key.startswith("PG") and value
    )
    if ambient_libpq:
        raise DeploymentError("AMBIENT_LIBPQ_ENV_FORBIDDEN")
    connection = conninfo_to_dict(dsn)
    expected_socket = (
        f"/proc/{container_pid}/root/var/run/postgresql"
    )
    if connection.get("host") != expected_socket:
        raise DeploymentError("ADMIN_DSN_NOT_BOUND_TO_CONTAINER_SOCKET")
    if connection.get("hostaddr") is not None:
        raise DeploymentError("ADMIN_DSN_HOSTADDR_FORBIDDEN")
    if connection.get("dbname") != expected_database:
        raise DeploymentError("ADMIN_DSN_DATABASE_MISMATCH")
    if connection.get("user") != "postgres":
        raise DeploymentError("ADMIN_DSN_PRINCIPAL_MISMATCH")
    if connection.get("port") not in {None, "5432"}:
        raise DeploymentError("ADMIN_DSN_PORT_MISMATCH")
    if any(connection.get(key) for key in (
            "password", "passfile", "service", "servicefile")):
        raise DeploymentError("ADMIN_DSN_CREDENTIAL_FORBIDDEN")
    if connection.get("sslmode") != "disable":
        raise DeploymentError("ADMIN_DSN_SSLMODE_MISMATCH")
    if connection.get("target_session_attrs") != "read-write":
        raise DeploymentError("ADMIN_DSN_TARGET_SESSION_MISMATCH")


def _bind_empty_memfd_passfile(dsn: str) -> tuple[int, str]:
    try:
        fd = os.memfd_create(
            "obsidian-b64-empty-pgpass", flags=os.MFD_CLOEXEC
        )
        os.fchmod(fd, 0o600)
        return fd, make_conninfo(dsn, passfile=f"/proc/self/fd/{fd}")
    except BaseException:
        if "fd" in locals():
            os.close(fd)
        raise


def _admin_preflight(dsn: str, expected_database: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SET LOCAL lock_timeout='3s'")
        cur.execute(
            "SELECT current_user,current_database(),r.rolsuper,"
            "r.rolcreaterole,current_setting('transaction_read_only'),"
            "inet_client_addr() IS NULL "
            "FROM pg_roles r WHERE r.rolname=current_user"
        )
        row = cur.fetchone()
    if row is None or row[0] != "postgres" or row[1] != expected_database:
        raise DeploymentError("ADMIN_PRINCIPAL_OR_DATABASE_MISMATCH")
    if (row[2] is not True or row[3] is not True or row[4] != "off"
            or row[5] is not True):
        raise DeploymentError("ADMIN_AUTHORITY_INSUFFICIENT")
    return {
        "currentUser": row[0],
        "database": row[1],
        "superuser": row[2],
        "createRole": row[3],
        "transactionReadOnly": row[4] == "on",
        "unixSocketTransport": row[5],
    }


def _execute_bound_sql(dsn: str, expected_database: str, path: Path, *,
                       deployment_nonce: str,
                       require_absent: bool = False) -> None:
    import psycopg

    source = path.read_text(encoding="utf-8")
    with psycopg.connect(
        dsn, autocommit=True, connect_timeout=5
    ) as conn:
        conn.execute(sql.SQL(
            "SET obsidian.snapshot_reader_expected_database = {}"
        ).format(sql.Literal(expected_database)))
        conn.execute(sql.SQL(
            "SET obsidian.snapshot_reader_require_absent = {}"
        ).format(sql.Literal("on" if require_absent else "off")))
        conn.execute(sql.SQL(
            "SET obsidian.snapshot_reader_deployment_nonce = {}"
        ).format(sql.Literal(deployment_nonce)))
        conn.execute(source)


def _safe_reason(exc: BaseException) -> str:
    value = str(exc)
    if isinstance(exc, DeploymentError) and re.fullmatch(
        r"[A-Z0-9_]+(?::[A-Za-z0-9_]+)?", value
    ):
        return value
    return "UNEXPECTED_DEPLOYMENT_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-env", default="EXCHANGE_DATABASE_URL")
    parser.add_argument("--admin-postgres-env")
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--allow-contract-database", action="store_true")
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-container-id", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--require-healthy", action="store_true")
    parser.add_argument("--require-role-absent", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "schemaVersion": "obsidian-b64-snapshot-reader-deployment.v1",
        "status": "FAILED",
        "action": "APPLY" if args.apply else "PREFLIGHT",
        "productionRowsRead": False,
        "adminDsnReadFromNamedEnvironment": True,
        "adminCredentialLogged": False,
        "rollbackAttempted": False,
        "rollbackVerified": False,
        "compensationState": "NOT_REQUIRED",
    }
    observation_dsn = os.environ.get(args.postgres_env)
    if not observation_dsn:
        result["reason"] = "POSTGRES_ENV_MISSING"
        print(json.dumps(result, sort_keys=True))
        return 2
    admin_dsn = (os.environ.get(args.admin_postgres_env)
                 if args.admin_postgres_env else None)
    if args.admin_postgres_env and not admin_dsn:
        result["reason"] = "ADMIN_POSTGRES_ENV_MISSING"
        print(json.dumps(result, sort_keys=True))
        return 2
    if args.apply and admin_dsn is None:
        result["reason"] = "ADMIN_POSTGRES_ENV_REQUIRED_FOR_APPLY"
        print(json.dumps(result, sort_keys=True))
        return 2
    if (args.expected_database != "obsidian_exchange"
            and not (args.allow_contract_database and re.fullmatch(
                r"b64_reader_contract_[0-9]+", args.expected_database))):
        result["reason"] = "EXPECTED_DATABASE_NOT_ALLOWED"
        print(json.dumps(result, sort_keys=True))
        return 2

    apply_attempted = False
    before_container: dict[str, Any] | None = None
    mutation_dsn = observation_dsn
    admin_passfile_fd: int | None = None
    deployment_nonce = secrets.token_hex(16)
    result["deploymentNonce"] = deployment_nonce
    deadline = time.monotonic() + 90
    try:
        plan = _load_and_bind_plan()
        result["planSha256"] = hashlib.sha256(json.dumps(
            plan, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        before_container = _inspect_container(
            args.container, args.expected_container_id,
            args.expected_image_id, args.require_healthy, observation_dsn,
        )
        preflight = _catalog_preflight(observation_dsn, args.expected_database)
        result["container"] = before_container
        result["preflight"] = preflight
        if args.require_role_absent and not preflight["roleAbsent"]:
            raise DeploymentError("ROLE_ALREADY_EXISTS")
        if admin_dsn is not None:
            _validate_container_admin_dsn(
                admin_dsn, args.expected_database,
                before_container["containerPid"],
            )
            admin_passfile_fd, mutation_dsn = _bind_empty_memfd_passfile(
                admin_dsn
            )
            result["mutationTransport"] = "BOUND_CONTAINER_UNIX_SOCKET"
            result["mutationCredentialPresent"] = False
            result["mutationPassfile"] = "EMPTY_MEMFD"
        else:
            result["mutationTransport"] = "OBSERVATION_DSN"
        if admin_dsn is not None or args.apply:
            result["adminPreflight"] = _admin_preflight(
                mutation_dsn, args.expected_database
            )
        if not args.apply:
            result["status"] = "PREFLIGHT_PASS"
            if admin_passfile_fd is not None:
                os.close(admin_passfile_fd)
                admin_passfile_fd = None
            print(json.dumps(result, sort_keys=True))
            return 0
        if not preflight["roleAbsent"]:
            raise DeploymentError("APPLY_REQUIRES_ABSENT_ROLE")
        apply_attempted = True
        _execute_bound_sql(
            mutation_dsn, args.expected_database, PROVISION_PATH,
            deployment_nonce=deployment_nonce, require_absent=True
        )
        if time.monotonic() > deadline:
            raise DeploymentError("OVERALL_DEADLINE_EXCEEDED")
        verification = inspect(mutation_dsn)
        result["verification"] = verification
        if (verification.get("status") != "match"
                or verification.get("credentialState") != "ABSENT"
                or verification.get("loginState") != "DISABLED"
                or verification.get("deploymentNonce") != deployment_nonce
                or verification.get("activationStatus") != "BLOCKED"
                or not REQUIRED_DORMANT_BLOCKERS.issubset(
                    set(verification.get("activationBlockers", [])))):
            raise DeploymentError("POST_APPLY_VERIFICATION_FAILED")
        after_container = _inspect_container(
            args.container, args.expected_container_id,
            args.expected_image_id, args.require_healthy, observation_dsn,
        )
        if after_container != before_container:
            raise DeploymentError("CONTAINER_CHANGED_DURING_APPLY")
        result["status"] = "DEPLOYED_DORMANT"
        result["activationAuthorized"] = False
        if admin_passfile_fd is not None:
            os.close(admin_passfile_fd)
            admin_passfile_fd = None
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        result["reason"] = _safe_reason(exc)
        if args.apply and apply_attempted:
            result["compensationState"] = "RECONCILING"
            try:
                if before_container is None:
                    raise DeploymentError("ORIGINAL_CONTAINER_NOT_BOUND")
                rebound = _inspect_container(
                    args.container, args.expected_container_id,
                    args.expected_image_id, args.require_healthy,
                    observation_dsn,
                )
                if rebound != before_container:
                    raise DeploymentError("COMPENSATION_TARGET_CHANGED")
                if admin_dsn is not None:
                    _validate_container_admin_dsn(
                        admin_dsn, args.expected_database,
                        rebound["containerPid"],
                    )
                role_exists = _role_exists(mutation_dsn)
            except BaseException:
                result["status"] = "ROLLBACK_UNCERTAIN"
                result["compensationState"] = "TARGET_OR_STATE_UNCONFIRMED"
            else:
                if not role_exists:
                    result["status"] = "FAILED_ROLE_ABSENT"
                    result["rollbackVerified"] = True
                    result["compensationState"] = "ROLE_ABSENCE_VERIFIED"
                else:
                    result["rollbackAttempted"] = True
                    try:
                        current = inspect(mutation_dsn)
                        if current.get("deploymentNonce") != deployment_nonce:
                            raise DeploymentError("DEPLOYMENT_BINDING_MISMATCH")
                        _execute_bound_sql(
                            mutation_dsn, args.expected_database, ROLLBACK_PATH,
                            deployment_nonce=deployment_nonce,
                        )
                        result["rollbackVerified"] = not _role_exists(
                            mutation_dsn
                        )
                    except BaseException:
                        result["status"] = "ROLLBACK_UNCERTAIN"
                        result["compensationState"] = "ROLLBACK_NOT_VERIFIED"
                    else:
                        if result["rollbackVerified"]:
                            result["status"] = "FAILED_ROLLED_BACK"
                            result["compensationState"] = "ROLE_ABSENCE_VERIFIED"
                        else:
                            result["status"] = "ROLLBACK_UNCERTAIN"
                            result["compensationState"] = "ROLLBACK_NOT_VERIFIED"
        if admin_passfile_fd is not None:
            os.close(admin_passfile_fd)
            admin_passfile_fd = None
        print(json.dumps(result, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
