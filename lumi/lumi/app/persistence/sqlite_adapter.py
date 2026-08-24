import json, os, sqlite3
from datetime import datetime, timezone
from lumi.app.persistence.storage_models import SQLITE_SCHEMA
from lumi.app.providers.redaction import RedactionUtil

class SQLiteStorageAdapter:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
        self._conn = None
        self._db_path = None
    def initialize(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SQLITE_SCHEMA)
        self._conn.commit()
    def save_record(self, profile_id: str, collection: str, record_id: str, payload: dict):
        if not self._conn: raise RuntimeError("Storage not initialized")
        now = datetime.now(timezone.utc).isoformat()
        safe = self.redaction.redact_dict(payload or {})
        payload_json = json.dumps(safe, ensure_ascii=False)
        self._conn.execute("""
            INSERT INTO lumi_records(profile_id, collection, record_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, collection, record_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
        """, (profile_id, collection, record_id, payload_json, now, now))
        self._conn.commit()
    def load_collection(self, profile_id: str, collection: str) -> list[dict]:
        if not self._conn: return []
        rows = self._conn.execute("SELECT payload_json FROM lumi_records WHERE profile_id=? AND collection=? ORDER BY id", (profile_id, collection)).fetchall()
        out=[]
        for row in rows:
            try: out.append(json.loads(row[0]))
            except Exception: continue
        return out
    def delete_record(self, profile_id: str, collection: str, record_id: str):
        if not self._conn: return
        self._conn.execute("DELETE FROM lumi_records WHERE profile_id=? AND collection=? AND record_id=?", (profile_id, collection, record_id)); self._conn.commit()
    def clear_collection(self, profile_id: str, collection: str):
        if not self._conn: return
        self._conn.execute("DELETE FROM lumi_records WHERE profile_id=? AND collection=?", (profile_id, collection)); self._conn.commit()
    def clear_profile(self, profile_id: str):
        if not self._conn: return
        self._conn.execute("DELETE FROM lumi_records WHERE profile_id=?", (profile_id,)); self._conn.execute("DELETE FROM lumi_profile_meta WHERE profile_id=?", (profile_id,)); self._conn.commit()
    def list_collections(self, profile_id: str) -> list[str]:
        if not self._conn: return []
        rows = self._conn.execute("SELECT DISTINCT collection FROM lumi_records WHERE profile_id=?", (profile_id,)).fetchall()
        return [r[0] for r in rows]
    def health(self) -> dict:
        if not self._conn: return {"status":"not_initialized","readable":False,"writable":False,"path":self._db_path}
        try:
            self._conn.execute("SELECT 1").fetchone()
            self._conn.execute("CREATE TABLE IF NOT EXISTS lumi_health_check(x TEXT)")
            self._conn.commit()
            return {"status":"ready","readable":True,"writable":True,"path":self._db_path}
        except Exception as e:
            return {"status":"degraded","readable":False,"writable":False,"path":self._db_path,"error":str(e)}
