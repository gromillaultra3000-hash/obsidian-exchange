import os
import requests

TROCADOR_BASE_URL = "https://trocador.app"

TROCADOR_STATUSES = frozenset({
    "new", "waiting", "confirming", "sending", "finished", "failed",
    "expired", "refunded",
})
TROCADOR_TERMINAL_STATUSES = frozenset({"finished", "failed", "expired", "refunded"})
TROCADOR_TRANSITIONS = {
    "new": frozenset({"waiting", "confirming", "sending", "finished", "failed", "expired", "refunded"}),
    "waiting": frozenset({"confirming", "sending", "finished", "failed", "expired", "refunded"}),
    "confirming": frozenset({"sending", "finished", "failed", "expired", "refunded"}),
    "sending": frozenset({"finished", "failed", "expired", "refunded"}),
}


def verified_trocador_status(info):
    """Return only a provider-fetched, recognized status.

    Callback payload status is intentionally not accepted by this helper.
    Unknown values fail closed so a provider/API change cannot invent a local
    money-state transition.
    """
    if not isinstance(info, dict) or info.get("error"):
        return None
    status = info.get("Status") or info.get("status")
    if not isinstance(status, str):
        return None
    status = status.strip().lower()
    return status if status in TROCADOR_STATUSES else None


def safe_trocador_transition(old_status, new_status):
    """Accept idempotent or forward-only transitions; terminal states stay immutable."""
    old = str(old_status or "").strip().lower()
    new = str(new_status or "").strip().lower()
    if new not in TROCADOR_STATUSES:
        return None
    if new == old:
        return new
    if old not in TROCADOR_TRANSITIONS or new not in TROCADOR_TRANSITIONS[old]:
        return None
    return new


class TrocadorProvider:
    """Неконсьюдиальный своп через AnonPay-виджет Trocador.

    Создаёт сделку через https://trocador.app/anonpay/ с нашим
    реферальным кодом — пользователь сам отправляет монету на адрес,
    который выдаёт Trocador, и сам получает результат на свой адрес.
    Мы не держим средства пользователя.
    """

    def __init__(self):
        self.ref = os.getenv('TROCADOR_REF_CODE', '')

    def create_swap(self, ticker_from, network_from, ticker_to, network_to,
                     amount, address, webhook=None, name="ObsidianExchange"):
        params = {
            "ticker_from": ticker_from,
            "network_from": network_from,
            "ticker_to": ticker_to,
            "network_to": network_to,
            "amount": amount,
            "address": address,
            "direct": "False",
            "name": name,
        }
        if self.ref:
            params["ref"] = self.ref
        if webhook:
            params["webhook"] = webhook
        try:
            r = requests.get(
                f"{TROCADOR_BASE_URL}/en/anonpay/",
                params=params,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            try:
                data = r.json()
            except ValueError:
                return {"error": r.text.strip() or f"Trocador HTTP {r.status_code}"}
            if "url" not in data:
                return {"error": data.get("error") or str(data)}
            return {
                "id": data.get("ID"),
                "url": data.get("url"),
                "status_url": data.get("status_url"),
                "raw": data,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, trocador_id):
        try:
            r = requests.get(
                f"{TROCADOR_BASE_URL}/anonpay/status/{trocador_id}",
                headers={"Accept": "application/json"},
                timeout=15,
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}
