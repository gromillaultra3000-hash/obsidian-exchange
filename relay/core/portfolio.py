"""Сколько стоит то, что лежит у клиента в подключённых кошельках.

Зачем отдельный модуль. Карточка кошелька в Mini App показывала ОДНУ сеть —
TON, если она есть, иначе первую попавшуюся. Клиент, подтвердивший три адреса,
видел один и делал вывод, что остальные мы потеряли. «Сколько у меня всего» не
отвечал никто: рублёвая оценка считалась прямо в разметке и только для той
единственной монеты.

Здесь это считается один раз и отдаётся боту, сайту и Mini App. Своя формула на
каждой поверхности — то же самое, из-за чего курс выкупа однажды разошёлся
между ботом и сайтом (см. `core/pricing`).

Два правила, которые важнее удобства:

1. **«Не знаем» никогда не становится нулём.** Обозреватель молчит — актив идёт
   в список с пустой суммой, а ИТОГ помечается неполным (`complete=False`).
   Показать заниженный итог как окончательный — соврать про деньги.
2. **Актив без цены не попадает в итог.** У монеты может не быть источника
   котировки (TRX сейчас такой). Её остаток показывается, но в рублёвую сумму
   не входит, и это тоже делает итог неполным — молча дорисовывать ноль нельзя.

Модуль не ходит в сеть сам: остатки ему передают, цены он берёт из общего
кеша курсов (`utils.exchange_calc`), у которого TTL 10 минут.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _rate(asset: str):
    """Рыночная цена одной единицы актива в рублях или None.

    Именно РЫНОЧНАЯ, а не наш курс покупки/продажи: портфель отвечает на вопрос
    «сколько это стоит», а не «сколько мы за это дадим». Подмешать сюда свою
    маржу значило бы показать клиенту заниженное состояние счёта.
    """
    code = str(asset or "").strip().upper()
    if not code:
        return None
    try:
        from utils.exchange_calc import get_cached_rate
        value = float(get_cached_rate(code) or 0)
    except Exception as e:
        # ValueError у неизвестной монеты — штатный ответ «источника цены нет»,
        # остальное — сбой. И то и другое означает одно: цены нет.
        logger.info("portfolio: нет цены для %s (%s)", code, type(e).__name__)
        return None
    return value if value > 0 else None


def _lines_of(wallet: dict) -> list:
    """Активы одного подключённого кошелька.

    Читатель может отдать состав счёта (`assets`) — тогда берём его целиком.
    Не отдал — считаем, что на счёте один заглавный актив. Пустой список при
    статусе OK трактуем как «ничего нет», а не как «читатель промолчал»:
    решение принимает читатель, здесь мы его не переспрашиваем.
    """
    assets = wallet.get("assets")
    if isinstance(assets, list) and assets:
        return assets
    return [{"asset": wallet.get("asset") or wallet.get("chain"),
             "balance": wallet.get("balance"),
             "status": wallet.get("status"),
             "reason": wallet.get("reason")}]


def summarize(wallets) -> dict:
    """Портфель по списку подключённых кошельков (`wallet_link.balances_for`).

    Возвращает:
      chains   — по кошельку: сеть, адрес, активы с рублёвой оценкой;
      total_rub — сумма ТОЛЬКО того, что известно и имеет цену;
      complete — можно ли показывать итог как окончательный;
      unknown  — из-за чего итог неполный (для честной подписи под суммой).
    """
    chains, total, unknown = [], 0.0, []
    for w in (wallets or []):
        chain = w.get("chain") or ""
        items = []
        for a in _lines_of(w):
            code = str(a.get("asset") or chain or "").upper()
            bal = a.get("balance")
            known = isinstance(bal, (int, float)) and not isinstance(bal, bool)
            rate = _rate(code) if known else None
            rub = round(bal * rate, 2) if (known and rate is not None) else None
            if not known:
                unknown.append(f"{code}: остаток недоступен")
            elif rate is None:
                unknown.append(f"{code}: нет источника цены")
            else:
                total += rub
            items.append({"asset": code, "balance": bal if known else None,
                          "rub": rub, "status": a.get("status") or w.get("status"),
                          "reason": a.get("reason") or w.get("reason")})
        chains.append({"chain": chain, "address": w.get("address") or "",
                       "verified_at": w.get("verified_at"),
                       "pending": w.get("pending"), "assets": items})
    return {"chains": chains, "total_rub": round(total, 2),
            "complete": not unknown, "unknown": unknown}


def total_line(summary: dict) -> str:
    """Одна строка про итог — общая для бота и витрин.

    Неполный итог называется неполным прямо в тексте. Подпись «всего 12 000 ₽»
    под суммой, в которую не вошёл недоступный кошелёк, — это не округление, а
    неверное число про деньги клиента.
    """
    if not summary or not summary.get("chains"):
        return ""
    rub = f"{summary.get('total_rub', 0):,.2f} ₽".replace(",", " ")
    return rub if summary.get("complete") else f"≥ {rub} (часть данных недоступна)"
