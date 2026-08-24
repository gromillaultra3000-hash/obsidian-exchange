import re
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\bCREATE\s+(?:TABLE|INDEX)|\bALTER\s+TABLE|executescript", re.I)


def test_runtime_repositories_contain_no_ddl():
    offenders = {}
    for path in sorted((ROOT / "relay/repositories").glob("*.py")):
        matches = sorted(set(match.group(0) for match in FORBIDDEN.finditer(path.read_text())))
        if matches:
            offenders[path.name] = matches
    assert offenders == {}


def test_sqlite_migrations_apply_together_to_empty_database():
    migrations = sorted((ROOT / "deploy/sqlite").glob("[0-9][0-9][0-9]_*.sql"))
    assert migrations
    with tempfile.TemporaryDirectory() as td:
        with sqlite3.connect(Path(td) / "schema.db") as conn:
            for migration in migrations:
                conn.executescript(migration.read_text())
