"""Живой баланс горячего кошелька как резерв обменника (read-only, кэш).

Шаг #6a: кошелёк → витрина резервов. НИЧЕГО не двигает. Авто-выплата из кошелька —
отдельный gated-этап (#6b) под sell_guard/circuit-breaker и с funded-кошельком.
"""
from __future__ import annotations
import time

_CACHE = {"ts": 0.0, "data": None}
_TTL = 60


def hot_wallet_reserve(ttl: int = _TTL) -> dict:
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["ts"] < ttl:
        return _CACHE["data"]
    data: dict
    try:
        from wallet.tron_wallet import tron_status, tron_balance
        st = tron_status()
        if not st.get("configured"):
            data = {"configured": False, "note": "горячий кошелёк не создан"}
        else:
            b = tron_balance()
            usdt = next((t.get("balance") for t in b.get("tokens", [])
                         if t.get("symbol") == "USDT" and "balance" in t), None)
            data = {
                "configured": True,
                "network": "tron",
                "address": st.get("address"),
                "USDT": usdt,
                "TRX": b.get("balanceTrx"),
                "status": b.get("status"),
            }
    except Exception as e:
        data = {"error": type(e).__name__}
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data
