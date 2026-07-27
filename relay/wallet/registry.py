"""Единый реестр горячих кошельков ObsidianExchange.

Тонкий слой над per-chain модулями (btc_wallet, tron_wallet, evm_wallet), дающий
ОДИН нормализованный интерфейс для админ-поверхностей и (в перспективе) авто-выплат.
Фундамент мультичейн-экосистемы: будущие сети (TON, Monero) добавляются ОДНИМ
адаптером в CHAINS — остальной код (бот/сайт/mini app) их подхватит автоматически.

Нормализованная форма одного чейна (overview):
  {
    "chain": "EVM", "label": "...", "configured": bool, "unlocked": bool,
    "address": str, "network": str,
    "assets": [ {"symbol", "balance"(float|None), "status"} ],   # что отправляем/храним
    "gasAsset": {"symbol", "balance"} | None,                    # чем платится комиссия
    "error": str | None,
  }

ВАЖНО: balance() ходит в сеть — вызывать из потока (asyncio.to_thread), не в event loop.
Секретов/ключей реестр не трогает: только чтение статуса и баланса.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional

if "/root/relay" not in sys.path:
    sys.path.insert(0, "/root/relay")


# ── адаптеры конкретных сетей ────────────────────────────────────────────────
def _btc_like(coin: str, label: str) -> Dict[str, Callable]:
    """BTC/LTC через secure-контур btc_wallet (нативная монета = и актив, и газ)."""
    def status() -> Dict[str, Any]:
        from wallet import btc_wallet as bw
        st = bw.status(coin)
        return {"configured": bool(st.get("configured")),
                "unlocked": bool(st.get("unlocked")),
                "address": st.get("primaryAddress") or st.get("address") or "",
                "network": st.get("network") or coin.lower()}

    def balance() -> Dict[str, Any]:
        from wallet import btc_wallet as bw
        b = bw.balance(coin)
        amt = b.get("balance")
        return {"assets": [{"symbol": coin,
                            "balance": amt if isinstance(amt, (int, float)) else None,
                            "status": b.get("status", "?")}],
                "gasAsset": None,
                "error": b.get("reason")}

    return {"chain": coin, "label": label, "status": status, "balance": balance}


def _tron() -> Dict[str, Callable]:
    """TRON: USDT-TRC20 (актив) + TRX (газ)."""
    def status() -> Dict[str, Any]:
        from wallet.tron_wallet import tron_status
        st = tron_status()
        return {"configured": bool(st.get("configured")),
                "unlocked": bool(st.get("unlocked")),
                "address": st.get("address") or "",
                "network": st.get("network") or "tron-mainnet"}

    def balance() -> Dict[str, Any]:
        from wallet.tron_wallet import tron_balance
        b = tron_balance()
        assets = []
        for t in b.get("tokens", []):
            assets.append({"symbol": t.get("symbol"),
                           "balance": t.get("balance") if "balance" in t else None,
                           "status": t.get("status", b.get("status", "?"))})
        return {"assets": assets,
                "gasAsset": {"symbol": "TRX", "balance": b.get("balanceTrx", 0.0)},
                "error": b.get("reason")}

    return {"chain": "TRON", "label": "TRON (USDT-TRC20)", "status": status, "balance": balance}


def _evm() -> Dict[str, Callable]:
    """EVM: ETH (актив и газ) + USDT-ERC20 (актив)."""
    def status() -> Dict[str, Any]:
        from wallet import evm_wallet as ew
        st = ew.status()
        return {"configured": bool(st.get("configured")),
                "unlocked": bool(st.get("unlocked")),
                "address": st.get("address") or "",
                "network": st.get("network") or "ethereum-mainnet"}

    def balance() -> Dict[str, Any]:
        from wallet import evm_wallet as ew
        b = ew.balance()
        assets = [{"symbol": "ETH",
                   "balance": b.get("balanceEth") if b.get("status") == "OK" else None,
                   "status": b.get("status", "?")}]
        for t in b.get("tokens", []):
            assets.append({"symbol": t.get("symbol"),
                           "balance": t.get("balance") if "balance" in t else None,
                           "status": t.get("status", b.get("status", "?"))})
        return {"assets": assets,
                "gasAsset": {"symbol": "ETH", "balance": b.get("balanceEth", 0.0)},
                "error": b.get("reason")}

    return {"chain": "EVM", "label": "Ethereum (ETH · USDT-ERC20)", "status": status, "balance": balance}


def _xrp() -> Dict[str, Callable]:
    """XRP Ledger: XRP (актив и комиссия). Отдельно показываем доступный остаток —
    на XRPL часть баланса заморожена резервом счёта и отправить её нельзя."""
    def status() -> Dict[str, Any]:
        from wallet import xrp_wallet as xw
        st = xw.status()
        return {"configured": bool(st.get("configured")),
                "unlocked": bool(st.get("unlocked")),
                "address": st.get("address") or "",
                "network": st.get("network") or "xrpl-mainnet"}

    def balance() -> Dict[str, Any]:
        from wallet import xrp_wallet as xw
        total = xw.get_balance()
        avail = xw.spendable()
        return {"assets": [{"symbol": "XRP", "balance": total, "status": "OK"},
                           {"symbol": "XRP (доступно)", "balance": avail, "status": "OK"}],
                "gasAsset": {"symbol": "XRP", "balance": total},
                "error": None}

    return {"chain": "XRP", "label": "XRP Ledger", "status": status, "balance": balance}


# Порядок = порядок вывода в админ-поверхностях. Будущие сети — сюда:
#   _ton(), _monero()  (когда появятся модули wallet/ton_wallet.py и т.д.)
CHAINS: List[Callable[[], Dict[str, Callable]]] = [
    lambda: _btc_like("BTC", "Bitcoin"),
    lambda: _btc_like("LTC", "Litecoin"),
    _tron,
    _evm,
    _xrp,
]


# ── публичный API ────────────────────────────────────────────────────────────
def chains() -> List[str]:
    out = []
    for make in CHAINS:
        try:
            out.append(make()["chain"])
        except Exception:
            pass
    return out


def overview(include_balance: bool = True) -> List[Dict[str, Any]]:
    """Нормализованный срез всех кошельков. include_balance=False — только статус
    (без сети), быстро. Каждый чейн изолирован: сбой одного не роняет остальные."""
    result: List[Dict[str, Any]] = []
    for make in CHAINS:
        try:
            ad = make()
        except Exception as e:
            result.append({"chain": "?", "configured": False, "error": f"{type(e).__name__}"})
            continue
        row: Dict[str, Any] = {"chain": ad["chain"], "label": ad.get("label", ad["chain"]),
                               "assets": [], "gasAsset": None, "error": None}
        try:
            row.update({k: v for k, v in ad["status"]().items()})
        except Exception as e:
            row["error"] = f"status:{type(e).__name__}"
            row["configured"] = False
            result.append(row)
            continue
        if include_balance and row.get("configured"):
            try:
                b = ad["balance"]()
                row["assets"] = b.get("assets", [])
                row["gasAsset"] = b.get("gasAsset")
                if b.get("error"):
                    row["error"] = str(b["error"])[:160]
            except Exception as e:
                row["error"] = f"balance:{type(e).__name__}"
        result.append(row)
    return result
