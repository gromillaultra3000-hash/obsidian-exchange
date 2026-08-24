"""Read-only reporting queries shared by API and operator analytics."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from core import db_runtime


class SQLiteReportingStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def provider_conversion_rows(self, days: int):
        since = (datetime.now() - timedelta(days=int(days))).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ps.provider provider,COUNT(*) shown,"
                "SUM(CASE WHEN o.status IN ('paid','sent') THEN 1 ELSE 0 END) paid "
                "FROM payment_sessions ps JOIN orders o ON o.order_id=ps.order_id "
                "WHERE ps.created_at>? GROUP BY ps.provider",
                (since,),
            ).fetchall()
        return [{"provider": row[0], "shown": row[1], "paid": row[2]} for row in rows]

    def completed_evidence_rows(self, days: int):
        since = (datetime.now() - timedelta(days=int(days))).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT order_id,status,paid_btc_tx FROM orders "
                "WHERE status IN ('paid','sent') AND created_at>?",
                (since,),
            ).fetchall()
        return [{"order_id": row[0], "status": row[1], "paid_btc_tx": row[2]} for row in rows]

    def public_stats(self):
        today = datetime.now().date().isoformat()
        since = (datetime.now() - timedelta(days=1)).isoformat()
        with self._connect() as conn:
            sent_today = conn.execute(
                "SELECT COUNT(order_id) FROM orders WHERE created_at>=? AND created_at<? "
                "AND status='sent'", (today, today + "T23:59:59.999999")
            ).fetchone()[0]
            total_cnt, total_vol = conn.execute(
                "SELECT COUNT(order_id),COALESCE(SUM(rub_amount),0) FROM orders WHERE status='sent'"
            ).fetchone()
            vol_24h = conn.execute(
                "SELECT COALESCE(SUM(rub_amount),0) FROM orders "
                "WHERE status='sent' AND created_at>?", (since,)
            ).fetchone()[0]
        return {"exchanges_today": sent_today, "exchanges_total": total_cnt,
                "volume_24h": vol_24h, "volume_total": total_vol}

    def reserves(self, *, positive_only: bool = False):
        sql = "SELECT currency,amount FROM reserves"
        if positive_only:
            sql += " WHERE amount>0"
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY currency").fetchall()
        return [(row[0], row[1]) for row in rows]

    def reserves_detailed(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT currency,amount,updated_at FROM reserves ORDER BY currency LIMIT 100"
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def bot_today_summary(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(rub_amount),0),"
                "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END),"
                "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) "
                "FROM orders WHERE date(created_at)=date('now')"
            ).fetchone()
            pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
            paid = conn.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0]
            new_users = conn.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT user_id FROM orders "
                "WHERE date(created_at)=date('now') AND user_id NOT IN "
                "(SELECT DISTINCT user_id FROM orders WHERE date(created_at)<date('now')))"
            ).fetchone()[0]
            limits = conn.execute("SELECT COUNT(*) FROM limit_orders WHERE status='active'").fetchone()[0]
            dca = conn.execute("SELECT COUNT(*) FROM dca_schedules WHERE status='active'").fetchone()[0]
        return {"today_count": row[0], "today_volume": row[1], "today_sent": row[2] or 0,
                "today_sent_volume": row[3], "pending": pending, "paid": paid,
                "new_users": new_users, "active_limits": limits, "active_dca": dca}

    def admin_stats(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(order_id),SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END),"
                "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) "
                "FROM orders"
            ).fetchone()
        return {"total": row[0], "pending": row[1] or 0, "sent": row[2] or 0,
                "volume": row[3] or 0}

    def site_stats(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(order_id),"
                "SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN status IN ('paid','sent','failed') THEN 1 ELSE 0 END) "
                "FROM orders"
            ).fetchone()
        return {"total": int(row[0] or 0), "completed": int(row[1] or 0),
                "attempted": int(row[2] or 0)}

    def today_status_counts(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(order_id),"
                "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) "
                "FROM orders WHERE date(created_at)=date('now')"
            ).fetchone()
        return {"total": int(row[0] or 0), "pending": int(row[1] or 0),
                "completed": int(row[2] or 0), "expired": int(row[3] or 0)}

    def stuck_pending_orders(self, *, older_than_minutes: int = 30,
                             newer_than_hours: int = 24, limit: int = 5):
        older = (datetime.now() - timedelta(minutes=int(older_than_minutes))).isoformat(sep=" ")
        newer = (datetime.now() - timedelta(hours=int(newer_than_hours))).isoformat(sep=" ")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT order_id,currency,rub_amount,created_at FROM orders "
                "WHERE status='pending' AND created_at<? AND created_at>? "
                "ORDER BY created_at LIMIT ?", (older, newer, int(limit))
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status='pending' "
                "AND created_at<? AND created_at>?", (older, newer)
            ).fetchone()[0]
        return {"count": int(count), "rows": [
            {"order_id": row[0], "currency": row[1], "rub_amount": row[2],
             "created_at": row[3]} for row in rows]}

    def recent_conversion(self, *, minutes: int = 60):
        since = (datetime.now() - timedelta(minutes=int(minutes))).isoformat(sep=" ")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*),SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) "
                "FROM orders WHERE created_at>?", (since,)
            ).fetchone()
        return {"total": int(row[0] or 0), "paid": int(row[1] or 0)}

    def daily_order_stats(self):
        today = datetime.now().date().isoformat()
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*),SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END),"
                "COALESCE(SUM(CASE WHEN status IN ('paid','sent') THEN rub_amount ELSE 0 END),0),"
                "COUNT(DISTINCT user_id) FROM orders WHERE created_at>=? AND created_at<?",
                (today, tomorrow),
            ).fetchone()
        return {"total": int(row[0] or 0), "paid": int(row[1] or 0),
                "volume": row[2] or 0, "users": int(row[3] or 0)}

    def period_order_report(self, date_from: str, date_to: str):
        with self._connect() as conn:
            sent = conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                "WHERE date(created_at) BETWEEN ? AND ? AND status='sent'",
                (date_from, date_to)).fetchone()
            total = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE date(created_at) BETWEEN ? AND ?",
                (date_from, date_to)).fetchone()[0]
            currencies = conn.execute(
                "SELECT currency,COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                "WHERE date(created_at) BETWEEN ? AND ? AND status='sent' "
                "GROUP BY currency ORDER BY 3 DESC LIMIT 100", (date_from, date_to)).fetchall()
            new_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM orders WHERE "
                "date(created_at) BETWEEN ? AND ? AND user_id>0 AND NOT EXISTS "
                "(SELECT 1 FROM orders o2 WHERE o2.user_id=orders.user_id "
                "AND date(o2.created_at)<?)", (date_from, date_to, date_from)).fetchone()[0]
        return {"sent_count": sent[0], "sent_volume": sent[1], "total_count": total,
                "currencies": list(currencies), "new_users": new_users}

    def cumulative_stats(self, starts: dict[str, str], month_start: str,
                         currencies, statuses):
        if len(starts) > 32 or len(currencies) > 32 or len(statuses) > 32:
            raise ValueError("cumulative_stats_inputs_too_many")
        periods, by_currency, by_status = {}, {}, {}
        with self._connect() as conn:
            for name, start in starts.items():
                periods[name] = conn.execute(
                    "SELECT COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                    "WHERE date(created_at)>=? AND status='sent'", (start,)).fetchone()
            for currency in currencies:
                by_currency[currency] = conn.execute(
                    "SELECT COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                    "WHERE date(created_at)>=? AND currency=? AND status='sent'",
                    (month_start, currency)).fetchone()
            for status in statuses:
                by_status[status] = conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE date(created_at)>=? AND status=?",
                    (month_start, status)).fetchone()[0]
        return {"periods": periods, "currencies": by_currency, "statuses": by_status}

    def admin_analytics(self):
        with self._connect() as conn:
            conn.row_factory = __import__("sqlite3").Row

            def rows(sql):
                return [dict(row) for row in conn.execute(sql).fetchall()]

            daily = rows(
                "SELECT strftime('%m-%d',created_at) day,COUNT(order_id) orders,"
                "SUM(rub_amount) volume,"
                "SUM(CASE WHEN status IN('paid','sent') THEN 1 ELSE 0 END) paid "
                "FROM orders WHERE created_at>date('now','-14 days') "
                "GROUP BY day ORDER BY day"
            )
            hourly = rows(
                "SELECT CAST(strftime('%H',created_at) AS INTEGER) hour,COUNT(order_id) cnt "
                "FROM orders GROUP BY hour ORDER BY hour"
            )
            by_currency = rows(
                "SELECT currency,COUNT(order_id) cnt,SUM(rub_amount) vol FROM orders "
                "GROUP BY currency ORDER BY currency LIMIT 32"
            )
            by_status = rows("SELECT status,COUNT(order_id) cnt FROM orders "
                             "GROUP BY status ORDER BY status LIMIT 32")
            providers = rows(
                "SELECT provider,is_healthy,failed_count,avg_response_time,"
                "COALESCE(status,'') status,COALESCE(blocker,'') blocker FROM provider_health "
                "ORDER BY provider LIMIT 64"
            )
            recent = rows(
                "SELECT o.order_id,o.currency,o.rub_amount,o.status,o.created_at,o.username,"
                "(SELECT ps.provider FROM payment_sessions ps WHERE ps.order_id=o.order_id "
                "ORDER BY ps.id DESC LIMIT 1) provider FROM orders o "
                "ORDER BY o.order_id DESC LIMIT 20"
            )
            totals = rows(
                "SELECT COUNT(order_id) total_orders,SUM(rub_amount) total_volume,"
                "SUM(CASE WHEN status IN('paid','sent') THEN 1 ELSE 0 END) paid_orders,"
                "SUM(CASE WHEN status IN('paid','sent') THEN rub_amount ELSE 0 END) paid_volume "
                "FROM orders"
            )
        return {"daily": daily, "hourly": hourly, "by_currency": by_currency,
                "by_status": by_status, "providers": providers, "recent": recent,
                "totals": totals[0] if totals else {}}


class PostgresReportingStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def provider_conversion_rows(self, days: int):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ps.provider provider,COUNT(*) shown,"
                "SUM(CASE WHEN o.status IN ('paid','sent') THEN 1 ELSE 0 END) paid "
                "FROM payment_sessions ps JOIN orders o ON o.order_id=ps.order_id "
                "WHERE ps.created_at>now()-(%s*interval '1 day') GROUP BY ps.provider",
                (int(days),),
            )
            return [dict(row) for row in cur.fetchall()]

    def completed_evidence_rows(self, days: int):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT order_id,status,paid_btc_tx FROM orders "
                "WHERE status IN ('paid','sent') AND created_at>now()-(%s*interval '1 day')",
                (int(days),),
            )
            return [dict(row) for row in cur.fetchall()]

    def public_stats(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(order_id) FILTER (WHERE created_at>=CURRENT_DATE) sent_today,"
                "COUNT(order_id) total_cnt,COALESCE(SUM(rub_amount),0) total_vol,"
                "COALESCE(SUM(rub_amount) FILTER (WHERE created_at>now()-interval '1 day'),0) vol_24h "
                "FROM orders WHERE status='sent'"
            )
            row = cur.fetchone()
        return {"exchanges_today": row["sent_today"], "exchanges_total": row["total_cnt"],
                "volume_24h": row["vol_24h"], "volume_total": row["total_vol"]}

    def reserves(self, *, positive_only: bool = False):
        sql = "SELECT currency,amount FROM reserves"
        if positive_only:
            sql += " WHERE amount>0"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql + " ORDER BY currency")
            return [(row["currency"], row["amount"]) for row in cur.fetchall()]

    def reserves_detailed(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT currency,amount,updated_at FROM reserves ORDER BY currency LIMIT 100")
            return [(r["currency"], r["amount"], r["updated_at"].isoformat()) for r in cur.fetchall()]

    def bot_today_summary(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) today_count,COALESCE(SUM(rub_amount),0) today_volume,"
                "COUNT(*) FILTER(WHERE status='sent') today_sent,"
                "COALESCE(SUM(rub_amount) FILTER(WHERE status='sent'),0) today_sent_volume "
                "FROM orders WHERE created_at>=CURRENT_DATE AND created_at<CURRENT_DATE+interval '1 day'")
            result = dict(cur.fetchone())
            cur.execute("SELECT COUNT(*) FILTER(WHERE status='pending') pending,"
                        "COUNT(*) FILTER(WHERE status='paid') paid FROM orders")
            result.update(dict(cur.fetchone()))
            cur.execute("SELECT COUNT(DISTINCT o.user_id) new_users FROM orders o "
                        "WHERE o.created_at>=CURRENT_DATE AND NOT EXISTS "
                        "(SELECT 1 FROM orders old WHERE old.user_id=o.user_id "
                        "AND old.created_at<CURRENT_DATE)")
            result.update(dict(cur.fetchone()))
            cur.execute("SELECT (SELECT COUNT(*) FROM limit_orders WHERE status='active') active_limits,"
                        "(SELECT COUNT(*) FROM dca_schedules WHERE status='active') active_dca")
            result.update(dict(cur.fetchone()))
        return result

    def admin_stats(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(order_id) total,COUNT(order_id) FILTER (WHERE status='pending') pending,"
                "COUNT(order_id) FILTER (WHERE status='sent') sent,"
                "COALESCE(SUM(rub_amount) FILTER (WHERE status='sent'),0) volume FROM orders"
            )
            return dict(cur.fetchone())

    def site_stats(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(order_id) total,"
                "COUNT(order_id) FILTER (WHERE status IN ('paid','sent')) completed,"
                "COUNT(order_id) FILTER (WHERE status IN ('paid','sent','failed')) attempted "
                "FROM orders"
            )
            return dict(cur.fetchone())

    def today_status_counts(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(order_id) total,"
                "COUNT(order_id) FILTER (WHERE status='pending') pending,"
                "COUNT(order_id) FILTER (WHERE status IN ('paid','sent')) completed,"
                "COUNT(order_id) FILTER (WHERE status='expired') expired "
                "FROM orders WHERE created_at>=CURRENT_DATE "
                "AND created_at<CURRENT_DATE+interval '1 day'"
            )
            return dict(cur.fetchone())

    def stuck_pending_orders(self, *, older_than_minutes: int = 30,
                             newer_than_hours: int = 24, limit: int = 5):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT order_id,currency,rub_amount,created_at,COUNT(*) OVER() total_count "
                "FROM orders WHERE status='pending' "
                "AND created_at<now()-(%s*interval '1 minute') "
                "AND created_at>now()-(%s*interval '1 hour') "
                "ORDER BY created_at LIMIT %s",
                (int(older_than_minutes), int(newer_than_hours), int(limit)),
            )
            rows = cur.fetchall()
        return {"count": int(rows[0]["total_count"]) if rows else 0, "rows": [
            {"order_id": row["order_id"], "currency": row["currency"],
             "rub_amount": row["rub_amount"], "created_at": row["created_at"]}
            for row in rows]}

    def recent_conversion(self, *, minutes: int = 60):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) total,COUNT(*) FILTER (WHERE status IN ('paid','sent')) paid "
                "FROM orders WHERE created_at>now()-(%s*interval '1 minute')", (int(minutes),)
            )
            row = cur.fetchone()
        return {"total": int(row["total"]), "paid": int(row["paid"])}

    def daily_order_stats(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) total,COUNT(*) FILTER (WHERE status IN ('paid','sent')) paid,"
                "COALESCE(SUM(rub_amount) FILTER (WHERE status IN ('paid','sent')),0) volume,"
                "COUNT(DISTINCT user_id) users FROM orders WHERE created_at>=CURRENT_DATE"
            )
            return dict(cur.fetchone())

    def period_order_report(self, date_from: str, date_to: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FILTER(WHERE status='sent') sent_count,"
                "COALESCE(SUM(rub_amount) FILTER(WHERE status='sent'),0) sent_volume,"
                "COUNT(*) total_count FROM orders WHERE created_at::date BETWEEN %s AND %s",
                (date_from, date_to))
            result = dict(cur.fetchone())
            cur.execute(
                "SELECT currency,COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                "WHERE created_at::date BETWEEN %s AND %s AND status='sent' "
                "GROUP BY currency ORDER BY 3 DESC LIMIT 100", (date_from, date_to))
            result["currencies"] = [(r["currency"], r["count"], r["coalesce"])
                                      for r in cur.fetchall()]
            cur.execute(
                "SELECT COUNT(DISTINCT o.user_id) new_users FROM orders o WHERE "
                "o.created_at::date BETWEEN %s AND %s AND o.user_id>0 AND NOT EXISTS "
                "(SELECT 1 FROM orders old WHERE old.user_id=o.user_id "
                "AND old.created_at::date<%s)", (date_from, date_to, date_from))
            result["new_users"] = cur.fetchone()["new_users"]
        return result

    def cumulative_stats(self, starts: dict[str, str], month_start: str,
                         currencies, statuses):
        if len(starts) > 32 or len(currencies) > 32 or len(statuses) > 32:
            raise ValueError("cumulative_stats_inputs_too_many")
        periods, by_currency, by_status = {}, {}, {}
        with self._connect() as conn, conn.cursor() as cur:
            for name, start in starts.items():
                cur.execute("SELECT COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                            "WHERE created_at::date>=%s AND status='sent'", (start,))
                row = cur.fetchone(); periods[name] = (row["count"], row["coalesce"])
            for currency in currencies:
                cur.execute("SELECT COUNT(*),COALESCE(SUM(rub_amount),0) FROM orders "
                            "WHERE created_at::date>=%s AND currency=%s AND status='sent'",
                            (month_start, currency))
                row = cur.fetchone(); by_currency[currency] = (row["count"], row["coalesce"])
            for status in statuses:
                cur.execute("SELECT COUNT(*) FROM orders WHERE created_at::date>=%s AND status=%s",
                            (month_start, status))
                by_status[status] = cur.fetchone()["count"]
        return {"periods": periods, "currencies": by_currency, "statuses": by_status}

    def admin_analytics(self):
        with self._connect() as conn, conn.cursor() as cur:
            def rows(sql):
                cur.execute(sql)
                return [dict(row) for row in cur.fetchall()]

            daily = rows(
                "SELECT to_char(created_at,'MM-DD') AS \"day\",COUNT(order_id) AS orders,"
                "SUM(rub_amount) volume,"
                "COUNT(order_id) FILTER(WHERE status IN('paid','sent')) paid "
                "FROM orders WHERE created_at>CURRENT_DATE-interval '14 days' "
                "GROUP BY 1 ORDER BY 1"
            )
            hourly = rows(
                "SELECT EXTRACT(HOUR FROM created_at)::integer AS \"hour\",COUNT(order_id) cnt "
                "FROM orders GROUP BY 1 ORDER BY 1"
            )
            by_currency = rows(
                "SELECT currency,COUNT(order_id) cnt,SUM(rub_amount) vol FROM orders "
                "GROUP BY currency ORDER BY currency LIMIT 32"
            )
            by_status = rows("SELECT status,COUNT(order_id) cnt FROM orders "
                             "GROUP BY status ORDER BY status LIMIT 32")
            providers = rows(
                "SELECT provider,is_healthy,failed_count,avg_response_time,"
                "COALESCE(status,'') status,COALESCE(blocker,'') blocker FROM provider_health "
                "ORDER BY provider LIMIT 64"
            )
            recent = rows(
                "SELECT o.order_id,o.currency,o.rub_amount,o.status,o.created_at,o.username,"
                "(SELECT ps.provider FROM payment_sessions ps WHERE ps.order_id=o.order_id "
                "ORDER BY ps.id DESC LIMIT 1) provider FROM orders o "
                "ORDER BY o.order_id DESC LIMIT 20"
            )
            totals = rows(
                "SELECT COUNT(order_id) total_orders,SUM(rub_amount) total_volume,"
                "COUNT(order_id) FILTER(WHERE status IN('paid','sent')) paid_orders,"
                "SUM(rub_amount) FILTER(WHERE status IN('paid','sent')) paid_volume FROM orders"
            )
        return {"daily": daily, "hourly": hourly, "by_currency": by_currency,
                "by_status": by_status, "providers": providers, "recent": recent,
                "totals": totals[0] if totals else {}}


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteReportingStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("REPORTING_POSTGRES_ENABLED", "").lower() not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_reporting_store_not_enabled")
    return PostgresReportingStore(url)
