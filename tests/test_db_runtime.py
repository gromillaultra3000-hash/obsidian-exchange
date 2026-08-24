import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from core import db_runtime

assert db_runtime.backend("/tmp/exchange.db") == "sqlite"
assert db_runtime.backend("postgresql://localhost/db") == "postgresql"
with tempfile.TemporaryDirectory() as td:
    conn = db_runtime.sqlite_connect(str(Path(td) / "test.db"), timeout=1)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1000
    conn.close()
old = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "postgresql://localhost/blocked"
try:
    try:
        db_runtime.sqlite_connect(":memory:")
        raise AssertionError("PostgreSQL URL was silently treated as SQLite")
    except RuntimeError as exc:
        assert str(exc) == "postgres_runtime_not_enabled"
    with tempfile.TemporaryDirectory() as td:
        aux = db_runtime.auxiliary_sqlite_connect(str(Path(td) / "support.db"))
        aux.execute("CREATE TABLE support_state(id INTEGER PRIMARY KEY)")
        aux.close()
finally:
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old
print("database runtime boundary checks: OK")
