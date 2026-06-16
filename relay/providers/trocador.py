import os
import requests

TROCADOR_BASE_URL = "https://trocador.app"


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
