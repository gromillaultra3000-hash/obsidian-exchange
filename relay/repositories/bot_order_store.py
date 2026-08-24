"""Bot buy-order creation and single-use rate-lock transaction."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol

from core import db_runtime


class BotOrderStore(Protocol):
    def active_rate_lock(self, user_id: int, currency: str) -> dict[str, Any] | None: ...
    def replace_rate_lock(self, *, user_id: int, currency: str, locked_rate: float,
                          fee_rub: float, locked_until: datetime) -> int: ...
    def create_order(self, *, user_id: int, username: str | None, currency: str,
                     rub_amount: float, destination: str, network: str | None,
                     preferred_rate: float, preferred_crypto_amount: float,
                     fallback_rate: float, fallback_crypto_amount: float,
                     lock_id: int | None = None, promo_id: int | None = None,
                     lock_no_promo_rate: float | None = None,
                     lock_no_promo_crypto_amount: float | None = None,
                     regular_no_promo_rate: float | None = None,
                     regular_no_promo_crypto_amount: float | None = None) -> dict[str, Any]: ...


class SQLiteBotOrderStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout
    def _connect(self): return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def active_rate_lock(self, user_id: int, currency: str):
        with self._connect() as conn:
            row=conn.execute("SELECT id,locked_rate,fee_rub FROM rate_locks WHERE user_id=? "
                             "AND currency=? AND used=0 AND locked_until>CURRENT_TIMESTAMP "
                             "ORDER BY id DESC LIMIT 1", (int(user_id),currency)).fetchone()
        return ({"lock_id":int(row[0]),"rate":float(row[1]),"fee":float(row[2])}
                if row else None)

    def replace_rate_lock(self, *, user_id: int, currency: str, locked_rate: float,
                          fee_rub: float, locked_until: datetime) -> int:
        until=locked_until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE rate_locks SET used=1 WHERE user_id=? AND currency=? AND used=0",
                         (int(user_id),currency))
            cur=conn.execute("INSERT INTO rate_locks(user_id,currency,locked_rate,fee_rub,locked_until) "
                             "VALUES(?,?,?,?,?)",(int(user_id),currency,float(locked_rate),
                                                  float(fee_rub),until))
            conn.commit(); return int(cur.lastrowid)

    def create_order(self, **data):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur=conn.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,"
                             "status,network,agreed_rate,agreed_crypto_amount,agreed_at) "
                             "VALUES(?,?,?,?,?,'pending',?,?,?,CURRENT_TIMESTAMP)",
                             (int(data["user_id"]),data.get("username"),data["currency"],
                              float(data["rub_amount"]),data["destination"],data.get("network"),
                              float(data["preferred_rate"]),float(data["preferred_crypto_amount"])))
            oid=int(cur.lastrowid); used=False
            if data.get("lock_id") is not None:
                used=conn.execute("UPDATE rate_locks SET used=1,order_id=? WHERE id=? AND user_id=? "
                                  "AND currency=? AND used=0 AND locked_until>CURRENT_TIMESTAMP",
                                  (oid,int(data["lock_id"]),int(data["user_id"]),
                                   data["currency"])).rowcount==1
            promo_used=False
            if data.get("promo_id") is not None:
                promo_used=conn.execute(
                    "UPDATE promo_codes SET uses_count=uses_count+1 WHERE id=? AND is_active=1 "
                    "AND valid_until>=CURRENT_TIMESTAMP AND uses_count<max_uses AND NOT EXISTS("
                    "SELECT 1 FROM promo_uses WHERE code_id=? AND user_id=?)",
                    (int(data["promo_id"]),int(data["promo_id"]),int(data["user_id"]))).rowcount==1
                if promo_used:
                    conn.execute("INSERT INTO promo_uses(code_id,user_id,order_id) VALUES(?,?,?)",
                                 (int(data["promo_id"]),int(data["user_id"]),oid))
            if used:
                actual_rate=(data["preferred_rate"] if promo_used or data.get("promo_id") is None
                             else data["lock_no_promo_rate"])
                actual_crypto=(data["preferred_crypto_amount"] if promo_used or data.get("promo_id") is None
                               else data["lock_no_promo_crypto_amount"])
            else:
                actual_rate=(data["fallback_rate"] if promo_used or data.get("promo_id") is None
                             else data["regular_no_promo_rate"])
                actual_crypto=(data["fallback_crypto_amount"] if promo_used or data.get("promo_id") is None
                               else data["regular_no_promo_crypto_amount"])
            conn.execute("UPDATE orders SET agreed_rate=?,agreed_crypto_amount=? WHERE order_id=?",
                         (float(actual_rate),float(actual_crypto),oid))
            conn.commit()
            return {"order_id":oid,"lock_used":used,"promo_used":promo_used,
                    "agreed_rate":float(actual_rate),"agreed_crypto_amount":float(actual_crypto)}


class PostgresBotOrderStore:
    def __init__(self, dsn: str): self.dsn=dsn
    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn,row_factory=dict_row)
    def active_rate_lock(self,user_id:int,currency:str):
        with self._connect() as conn,conn.cursor() as cur:
            cur.execute("SELECT id lock_id,locked_rate rate,fee_rub fee FROM rate_locks "
                        "WHERE user_id=%s AND currency=%s AND used=false AND locked_until>now() "
                        "ORDER BY id DESC LIMIT 1",(int(user_id),currency)); row=cur.fetchone()
            return dict(row) if row else None
    def replace_rate_lock(self,*,user_id:int,currency:str,locked_rate:float,
                          fee_rub:float,locked_until:datetime)->int:
        with self._connect() as conn,conn.cursor() as cur:
            cur.execute("SELECT id FROM rate_locks WHERE user_id=%s AND currency=%s AND used=false "
                        "FOR UPDATE",(int(user_id),currency))
            cur.execute("UPDATE rate_locks SET used=true WHERE user_id=%s AND currency=%s AND used=false",
                        (int(user_id),currency))
            cur.execute("INSERT INTO rate_locks(user_id,currency,locked_rate,fee_rub,locked_until) "
                        "VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (int(user_id),currency,locked_rate,fee_rub,locked_until))
            return int(cur.fetchone()["id"])
    def create_order(self,**data):
        with self._connect() as conn,conn.cursor() as cur:
            cur.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
                        "network,agreed_rate,agreed_crypto_amount,agreed_at) "
                        "VALUES(%s,%s,%s,%s,%s,'pending',%s,%s,%s,now()) RETURNING order_id",
                        (int(data["user_id"]),data.get("username"),data["currency"],data["rub_amount"],
                         data["destination"],data.get("network"),data["preferred_rate"],
                         data["preferred_crypto_amount"])); oid=int(cur.fetchone()["order_id"]); used=False
            if data.get("lock_id") is not None:
                cur.execute("UPDATE rate_locks SET used=true,order_id=%s WHERE id=%s AND user_id=%s "
                            "AND currency=%s AND used=false AND locked_until>now()",
                            (oid,int(data["lock_id"]),int(data["user_id"]),data["currency"]))
                used=cur.rowcount==1
            promo_used=False
            if data.get("promo_id") is not None:
                cur.execute("UPDATE promo_codes SET uses_count=uses_count+1 WHERE id=%s AND is_active=true "
                            "AND valid_until>=now() AND uses_count<max_uses AND NOT EXISTS("
                            "SELECT 1 FROM promo_uses WHERE code_id=%s AND user_id=%s)",
                            (int(data["promo_id"]),int(data["promo_id"]),int(data["user_id"])))
                promo_used=cur.rowcount==1
                if promo_used:
                    cur.execute("INSERT INTO promo_uses(code_id,user_id,order_id) VALUES(%s,%s,%s)",
                                (int(data["promo_id"]),int(data["user_id"]),oid))
            if used:
                actual_rate=data["preferred_rate"] if promo_used or data.get("promo_id") is None else data["lock_no_promo_rate"]
                actual_crypto=data["preferred_crypto_amount"] if promo_used or data.get("promo_id") is None else data["lock_no_promo_crypto_amount"]
            else:
                actual_rate=data["fallback_rate"] if promo_used or data.get("promo_id") is None else data["regular_no_promo_rate"]
                actual_crypto=data["fallback_crypto_amount"] if promo_used or data.get("promo_id") is None else data["regular_no_promo_crypto_amount"]
            cur.execute("UPDATE orders SET agreed_rate=%s,agreed_crypto_amount=%s WHERE order_id=%s",
                        (actual_rate,actual_crypto,oid))
            return {"order_id":oid,"lock_used":used,"promo_used":promo_used,
                    "agreed_rate":float(actual_rate),"agreed_crypto_amount":float(actual_crypto)}


def from_environment(*,sqlite_path:str)->BotOrderStore:
    url=os.getenv("DATABASE_URL","").strip()
    if not url:return SQLiteBotOrderStore(sqlite_path)
    if (db_runtime.backend(url)!="postgresql" or
        os.getenv("BOT_ORDER_POSTGRES_ENABLED","").strip().lower() not in {"1","true","yes"}):
        raise RuntimeError("postgres_bot_order_store_not_enabled")
    return PostgresBotOrderStore(url)
