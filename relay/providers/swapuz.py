import os
import uuid
import requests
from utils.logger import get_logger

logger = get_logger(__name__)

SWAPUZ_BASE_URL = "https://api.swapuz.com"
SWAPUZ_API_KEY = os.getenv("SWAPUZ_API_KEY", "")

# Сопоставление наших монет → сети SwapUZ
SWAPUZ_NETWORKS = {
    "BTC": "BTC",
    "LTC": "LTC",
    "USDT": "TRX",  # TRC20
}

# Статусы: 0=ожидание, 1-5=в процессе, 6=завершено, 10=просрочено
_STATUS_MAP = {
    0: "waiting",
    1: "confirming",
    2: "confirming",
    3: "exchanging",
    4: "sending",
    5: "sending",
    6: "finished",
    10: "expired",
}


class SwapUzProvider:
    def __init__(self):
        self.base_url = SWAPUZ_BASE_URL
        self.api_key = SWAPUZ_API_KEY

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Api-key"] = self.api_key
        return h

    def get_rate(self, coin_from: str, coin_to: str, amount: float) -> dict:
        net_from = SWAPUZ_NETWORKS.get(coin_from.upper(), coin_from.upper())
        net_to = SWAPUZ_NETWORKS.get(coin_to.upper(), coin_to.upper())
        try:
            r = requests.get(
                f"{self.base_url}/api/home/v1/rate/",
                params={
                    "from": coin_from.upper(),
                    "to": coin_to.upper(),
                    "amount": amount,
                    "fromNetwork": net_from,
                    "toNetwork": net_to,
                    "mode": "float",
                },
                headers=self._headers(),
                timeout=10,
            )
            data = r.json()
            if r.status_code != 200 or not data.get("result"):
                return {"error": data.get("message") or f"SwapUZ rate error {r.status_code}"}
            res = data["result"]
            return {
                "estimated_receive": res.get("result"),
                "rate": res.get("rate"),
                "min_amount": res.get("minAmount"),
                "max_amount": res.get("maxAmount"),
                "withdraw_fee": res.get("withdrawFee"),
            }
        except Exception as e:
            logger.error(f"SwapUZ get_rate failed: {e}")
            return {"error": str(e)}

    def create_swap(self, coin_from: str, coin_to: str, amount: float, address: str, order_uuid: str = None) -> dict:
        net_from = SWAPUZ_NETWORKS.get(coin_from.upper(), coin_from.upper())
        net_to = SWAPUZ_NETWORKS.get(coin_to.upper(), coin_to.upper())
        uid = order_uuid or str(uuid.uuid4())
        payload = {
            "from": coin_from.upper(),
            "fromNetwork": net_from,
            "to": coin_to.upper(),
            "toNetwork": net_to,
            "address": address,
            "amount": amount,
            "uuid": uid,
            "modeCurs": "float",
        }
        try:
            r = requests.post(
                f"{self.base_url}/api/home/v1/order",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
            data = r.json()
            if r.status_code != 200 or not data.get("result"):
                return {"error": data.get("message") or f"SwapUZ order error {r.status_code}"}
            res = data["result"]
            return {
                "uid": res.get("uid"),
                "deposit_address": res.get("addressFrom"),
                "estimated_receive": res.get("amountResult"),
                "amount_from": amount,
                "url": f"https://swapuz.com/order/{res.get('uid')}",
                "raw": res,
            }
        except Exception as e:
            logger.error(f"SwapUZ create_swap failed: {e}")
            return {"error": str(e)}

    def get_status(self, uid: str) -> dict:
        try:
            r = requests.get(
                f"{self.base_url}/api/order/uid/{uid}",
                headers=self._headers(),
                timeout=10,
            )
            data = r.json()
            if r.status_code != 200 or not data.get("result"):
                return {"status": "unknown"}
            res = data["result"]
            status_code = res.get("status", -1)
            return {
                "status": _STATUS_MAP.get(status_code, f"status_{status_code}"),
                "status_code": status_code,
                "raw": res,
            }
        except Exception as e:
            logger.error(f"SwapUZ get_status failed: {e}")
            return {"status": "unknown"}
