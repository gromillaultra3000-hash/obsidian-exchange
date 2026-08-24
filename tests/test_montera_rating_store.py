import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

with tempfile.TemporaryDirectory() as td:
    db_path = str(Path(td) / "montera.db")
    os.environ["DB_PATH"] = db_path
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE orders(user_id INTEGER, status TEXT)")
        conn.executemany(
            "INSERT INTO orders(user_id,status) VALUES(?,?)",
            [(7, "paid"), (7, "sent"), (7, "completed"),
             (7, "failed"), (7, "pending"),
             (8, "paid"), (8, "failed"), (8, "cancelled")],
        )

    from providers import montera

    rating, trusted = montera._get_user_rating(7)
    assert rating == {"success": 3, "failure": 1}
    assert trusted is True

    rating, trusted = montera._get_user_rating(8)
    assert rating == {"success": 1, "failure": 2}
    assert trusted is False

    for invalid in (None, 0, -1):
        assert montera._get_user_rating(invalid) == (
            {"success": 0, "failure": 0}, False)

    original_store = montera._store
    try:
        montera._store = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
        assert montera._get_user_rating(7) == (
            {"success": 0, "failure": 0}, False)
    finally:
        montera._store = original_store

os.environ.pop("DB_PATH", None)
print("Montera rating repository checks: OK")
