"""One-shot, fail-closed B5.3 notification reconciler for systemd supervision."""
import json
import os
import sys


EXPECTED_KEYS = {
    "acceptedFinalized", "staleManualReview", "actionAllowed", "automaticRetryAllowed"
}


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid_{name.lower()}") from exc
    if value < low or value > high:
        raise RuntimeError(f"invalid_{name.lower()}")
    return value


def run_once(connect) -> dict:
    dsn = os.getenv("BOT_NOTIFICATION_RECONCILER_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("notification_reconciler_database_url_missing")
    limit = _bounded_int("BOT_NOTIFICATION_RECONCILER_LIMIT", 100, 1, 1000)
    stale = _bounded_int("BOT_NOTIFICATION_STALE_AFTER_SECONDS", 900, 60, 86400)
    with connect(dsn) as conn:
        conn.execute("SET LOCAL statement_timeout='20s'")
        conn.execute("SET LOCAL lock_timeout='2s'")
        identity = conn.execute(
            "SELECT session_user,current_user,r.rolcanlogin,r.rolinherit,r.rolsuper,"
            "r.rolcreaterole,r.rolcreatedb,r.rolreplication,r.rolbypassrls,"
            "(SELECT count(*) FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid) "
            "FROM pg_catalog.pg_roles r WHERE r.rolname=session_user"
        ).fetchone()
        expected = "obsidian_exchange_bot_notification_reconciler"
        if (not identity or identity[0] != expected or identity[1] != expected
                or not identity[2] or any(identity[3:9]) or int(identity[9]) != 0):
            raise RuntimeError("notification_reconciler_identity_preflight_failed")
        privilege = conn.execute(
            "SELECT pg_catalog.has_function_privilege(session_user,"
            "'public.bot_b63_reconcile_batch(integer,integer)'::regprocedure,'EXECUTE'),"
            "pg_catalog.has_function_privilege('public',"
            "'public.bot_b63_reconcile_batch(integer,integer)'::regprocedure,'EXECUTE')"
        ).fetchone()
        if not privilege or privilege != (True, False):
            raise RuntimeError("notification_reconciler_manifest_preflight_failed")
        row = conn.execute(
            "SELECT public.bot_b63_reconcile_batch(%s,%s)", (limit, stale)
        ).fetchone()
    result = row[0] if row else None
    if not isinstance(result, dict) or set(result) != EXPECTED_KEYS:
        raise RuntimeError("notification_reconciler_result_invalid")
    if (type(result["acceptedFinalized"]) is not int
            or type(result["staleManualReview"]) is not int
            or result["acceptedFinalized"] < 0 or result["staleManualReview"] < 0
            or result["actionAllowed"] is not False
            or result["automaticRetryAllowed"] is not False):
        raise RuntimeError("notification_reconciler_result_invalid")
    return result


def main() -> int:
    try:
        import psycopg
        result = run_once(psycopg.connect)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "errorType": type(exc).__name__}, separators=(",", ":")))
        return 1
    print(json.dumps({"status": "OK", **result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
