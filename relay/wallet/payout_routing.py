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


# Каким контуром монета уходит САМА. Список нужен потому, что «выдадим
# автоматически» — обещание, которое даётся владельцу в момент `/setreserve`,
# то есть ДО того, как клиент заплатит. Пока решение принималось перечислением
# исключений («всё кроме XRP умеем»), каждая новая монета получала это
# обещание молча: TON движок не умеет вовсе, а панель резервов рапортовала бы
# о полной готовности.
_CONTOUR_BY_CURRENCY = {
    "BTC": "btc",         # secure-контур btc_wallet
    "LTC": "btc",
    "USDT": "tron",       # TRC-20 — отдельный путь auto_check_usdt
    "ETH": "evm",
    "XRP": "xrp",         # под гейтом XRP_PAYOUTS_ENABLED
    "TON": "manual",      # своего вольта нет: watch-only, выдаёт человек
}


def payout_contour(currency, network=None) -> str:
    """Контур авто-выплаты: 'btc' | 'tron' | 'evm' | 'xrp' | 'manual' | 'unknown'.

    'manual' — монета известна, и мы знаем, что автомата для неё нет.
    'unknown' — монету забыли внести сюда; это НЕ синоним 'manual', потому что
    молчаливое умолчание и есть тот дефект, от которого список защищает:
    вызывающий обязан различать «решили выдавать руками» и «никто не решал».
    """
    c = (currency or "").strip().upper()
    if evm_payout_asset(c, network):
        return "evm"
    n = (network or "").strip().upper()
    if c == "USDT" and n and n not in ("TRC20", "TRON", "TRC-20"):
        return "unknown"          # третья сеть USDT — решения по ней нет
    return _CONTOUR_BY_CURRENCY.get(c, "unknown")
