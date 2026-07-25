"""Роутинг авто-выплат по сетям — чистая логика (без зависимостей от бота).

Определяет, каким контуром отправлять монету/сеть, и фиче-гейты. Вынесено из
main_bot для тестируемости и переиспользования (сайт/mini app/будущие сети).
"""
import os


def evm_payouts_enabled() -> bool:
    """Фиче-гейт авто-выплат EVM. По умолчанию ВЫКЛ: код готов, но ничего не
    отправляет, пока EVM_PAYOUTS_ENABLED не включён (и вольт не создан/пополнен)."""
    return os.getenv("EVM_PAYOUTS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


# Сети, которые реально обслуживает наш EVM-контур (Ethereum mainnet). Всё, что
# НЕ в этом множестве (TRC20/TRON/BSC/POLYGON/…), через EVM НЕ отправляем.
EVM_NETWORKS = {"ERC20", "ETH", "EVM", "ETHEREUM", "ETHEREUM-MAINNET"}


def evm_payout_asset(currency, network=None):
    """Актив EVM для выплаты или None (не EVM). Fail-closed по сети: если сеть указана
    явно, она РЕШАЕТ — только EVM-сети из allowlist разрешают EVM-путь, любая другая
    (TRC20/TRON/BSC/…) → None (не отправим не в ту сеть). Значения нормализуются
    (strip+upper), чтобы ' TRC20 ' не обошло защиту."""
    c = (currency or "").strip().upper()
    n = (network or "").strip().upper()
    if n:  # сеть задана явно — она решает
        if n not in EVM_NETWORKS:
            return None  # TRC20/TRON/BSC/POLYGON/… — не наш EVM-контур
        if c == "ETH":
            return "ETH"
        if c.startswith("USDT"):
            return "USDT"
        return None
    # сеть не задана — решаем по каноническому коду валюты
    if c == "ETH":
        return "ETH"
    if c in ("USDT_ERC20", "USDT-ERC20", "USDTE"):
        return "USDT"
    return None  # 'USDT' без сети → не EVM (это Tron/воркер)
