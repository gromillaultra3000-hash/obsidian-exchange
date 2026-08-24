"""Read-only access to legacy operational tables kept through DB cutover."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from core import db_runtime


class SQLiteLegacyRuntimeStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path = path
        self.timeout = timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def stuck_payout_count(self, *, older_than_minutes: int = 20) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(
            minutes=int(older_than_minutes)
        )).replace(tzinfo=None).isoformat(sep=" ")
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='payout_queue'"
            ).fetchone()
            if not exists:
                return 0
            row = conn.execute(
                "SELECT COUNT(*) FROM payout_queue "
                "WHERE status='new' AND datetime(created_at) < datetime(?)",
                (cutoff,),
            ).fetchone()
            return int(row[0])

    def recent_risk_event_count(self, *, since: datetime) -> int:
        value = since.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM risk_events WHERE datetime(created_at) >= datetime(?)",
                (value,),
            ).fetchone()
            return int(row[0])


class PostgresLegacyRuntimeStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg

        return psycopg.connect(self.dsn)

    def stuck_payout_count(self, *, older_than_minutes: int = 20) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM payout_queue "
                "WHERE status='new' AND created_at < now()-(%s*interval '1 minute')",
                (int(older_than_minutes),),
            )
            return int(cur.fetchone()[0])

    def recent_risk_event_count(self, *, since: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM risk_events WHERE created_at >= %s",
                (since,),
            )
            return int(cur.fetchone()[0])


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteLegacyRuntimeStore(sqlite_path)
    enabled = os.getenv("LEGACY_RUNTIME_POSTGRES_ENABLED", "").lower()
    if db_runtime.backend(url) != "postgresql" or enabled not in {"1", "true", "yes"}:
        raise RuntimeError("postgres_legacy_runtime_store_not_enabled")
    return PostgresLegacyRuntimeStore(url)
