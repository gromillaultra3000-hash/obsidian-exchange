import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

import psycopg
from reconcile_snapshot import reconcile

dsn = os.environ["TEST_POSTGRES_DSN"]
with tempfile.TemporaryDirectory() as td:
    source = str(Path(td) / "source.db")
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY,amount REAL,enabled INTEGER,created_at TEXT,note TEXT)")
    conn.execute("INSERT INTO sample VALUES(1,10.5,1,'2026-08-09 00:00:00','тест')")
    conn.commit()
    conn.close()

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS sample")
        cur.execute("CREATE TABLE sample(id bigint PRIMARY KEY,amount numeric,enabled boolean,created_at timestamptz,note text)")
        cur.execute("INSERT INTO sample VALUES(1,10.500,true,'2026-08-09 00:00:00+00','тест')")

    result = reconcile(source, dsn, ["sample"])
    assert result[0]["status"] == "match", result

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("UPDATE sample SET amount=11 WHERE id=1")
    result = reconcile(source, dsn, ["sample"])
    assert result[0]["status"] == "data_mismatch", result
    assert result[0]["sqlite_count"] == result[0]["postgres_count"] == 1

print("PostgreSQL snapshot reconciliation checks: OK")
