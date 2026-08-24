"""Куда клиенту приходят рубли за проданную крипту — один реестр на все поверхности.

Зачем модуль. До него направление продажи знало ровно один способ выплаты:
номер телефона для СБП, который владелец переводил руками. У Vertu есть
`POST /v1/payout/` — выплата на карту или по СБП с их баланса; методы провайдера
(`create_payout`, `get_payout_status`) были написаны давно и не вызывались
ниоткуда. Возможность, до которой не доходит клиент, — это не возможность.

Здесь описано ровно три вещи, и все три fail-closed:

  1. КАКИЕ направления выплаты открыты. Карта появляется только когда включён
     автоматический рельс: обещать «на карту» и платить руками мы не готовы —
     кто-то должен вводить номер карты в чужом банке каждый раз.
  2. КАКИЕ поля обязательны для выбранного направления. Vertu требует
     `bank` + `bank_details` + `full_name` для ЛЮБОГО типа выплаты, включая
     СБП: заявка без ФИО в этот рельс просто не уйдёт, и узнать об этом
     в момент выплаты — значит узнать слишком поздно.
  3. ЧЕМ платим — Vertu или человек. Неизвестное направление → человек, а не
     догадка.

Проверка номера карты — контрольная сумма Луна, а не длина. Опечатка в одной
цифре даёт валидный по длине номер чужой карты, и деньги уходят незнакомцу;
цифра, изменённая случайно, контрольную сумму не проходит в 9 случаях из 10.
"""
from __future__ import annotations

import logging
import os
import re
from repositories.sell_order_store import from_environment as _sell_store_from_environment

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
def _store():
    # DB_PATH is deliberately mutable in isolated tests and maintenance tools.
    return _sell_store_from_environment(sqlite_path=DB_PATH)

CARD = "card"
SBP = "sbp"

# Человеческие названия банков — коды берутся у провайдера (VertuProvider.
# PAYOUT_BANKS), чтобы список не разъехался с тем, что рельс реально принимает.
# Порядок = порядок кнопок у клиента.
BANK_LABELS = {
    "sber": "Сбербанк",
    "t-bank": "Т-Банк",
    "alfa": "Альфа-Банк",
    "vtb": "ВТБ",
    "gazprom": "Газпромбанк",
    "psb": "ПСБ",
}


def _vertu():
    from providers.vertu import VertuProvider
    return VertuProvider


def vertu_payout_enabled() -> bool:
    """Включён ли автоматический рельс выплат Vertu.

    Мало флага: без учётных данных вызов упадёт уже с деньгами клиента у нас,
    поэтому проверяем и их. Флаг отдельно от учётных данных потому, что для
    выплат нужен ПОЛОЖИТЕЛЬНЫЙ баланс у Vertu — включать рельс должен человек,
    который этот баланс видит.
    """
    if os.getenv("VERTU_PAYOUT", "") != "1":
        return False
    return bool(os.getenv("VERTU_API_KEY", "")
                or (os.getenv("VERTU_LOGIN", "") and os.getenv("VERTU_PASSWORD", "")))


def sbp_via_vertu() -> bool:
    """Пускать ли СБП через тот же автоматический рельс.

    По умолчанию НЕТ: СБП сегодня работает руками и работает, а перевод его на
    рельс добавляет клиенту два обязательных поля (банк и ФИО). Ломать рабочий
    путь ради единообразия нельзя — включается отдельно, когда владелец решит.
    """
    return vertu_payout_enabled() and os.getenv("VERTU_PAYOUT_SBP", "") == "1"


def methods() -> tuple:
    """Открытые направления выплаты, в порядке показа клиенту."""
    open_ = [SBP]
    if vertu_payout_enabled():
        open_.insert(0, CARD)
    return tuple(open_)


def label(method: str) -> str:
    return {CARD: "💳 На карту", SBP: "📱 По СБП"}.get(method, method)


def details_label(method: str) -> str:
    return {CARD: "Номер карты", SBP: "Номер телефона"}.get(method, "Реквизиты")


def route(method: str) -> str:
    """Чем платим: 'vertu' — автоматически, 'manual' — человеком.

    Неизвестное направление отправляется человеку, а не в рельс: попытка
    заплатить по правилам, которых мы не знаем, — это перевод вслепую.
    """
    if method == CARD and vertu_payout_enabled():
        return "vertu"
    if method == SBP and sbp_via_vertu():
        return "vertu"
    return "manual"


def needs_bank(method: str) -> bool:
    """Нужен ли код банка. Vertu требует его для обоих типов выплаты."""
    return route(method) == "vertu"


def needs_full_name(method: str) -> bool:
    """Нужно ли ФИО получателя. Требование рельса, а не наше: без него
    `POST /v1/payout/` отвечает 422, и узнали бы мы это уже с криптой клиента."""
    return route(method) == "vertu"


def banks() -> list:
    """[(код, название)] — только те коды, которые рельс реально принимает."""
    allowed = _vertu().PAYOUT_BANKS
    known = [(c, n) for c, n in BANK_LABELS.items() if c in allowed]
    # Код без названия — не прятать: иначе клиент не сможет выбрать банк,
    # который у провайдера работает, и мы об этом даже не узнаем.
    known += [(c, c) for c in sorted(allowed) if c not in BANK_LABELS]
    return known


def bank_label(code: str) -> str:
    return BANK_LABELS.get((code or "").strip().lower(), code or "")


def normalize_bank(code: str) -> str:
    """Код банка в том виде, в каком его принимает рельс, или '' — не принимает.

    Поверхности зовут отсюда, а не у провайдера напрямую: список банков и его
    синонимы живут в одном месте, и когда рельс сменится, менять придётся тоже
    одно место.
    """
    return _vertu().normalize_bank(code) if code else ""


# ── проверки реквизита ───────────────────────────────────────────────────────

def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def normalize_details(method: str, value: str) -> str:
    """Приводит реквизит к виду, в котором его примет рельс. '' — не годится."""
    raw = re.sub(r"[\s\-]", "", str(value or ""))
    if method == CARD:
        return raw if raw.isdigit() and 13 <= len(raw) <= 19 and _luhn_ok(raw) else ""
    if method == SBP:
        raw = raw.lstrip("+")
        if raw.startswith("8") and len(raw) == 11:
            raw = "7" + raw[1:]
        return raw if re.fullmatch(r"7\d{10}", raw) else ""
    return ""


_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-']{1,}$")


def normalize_full_name(value: str) -> str:
    """ФИО получателя. Требуем минимум два слова: одно слово в этом поле у
    провайдера почти всегда означает, что клиент ввёл не то (ник, «карта»)."""
    parts = [p for p in re.split(r"\s+", str(value or "").strip()) if p]
    if len(parts) < 2 or len(parts) > 4:
        return ""
    if any(not _NAME_RE.match(p) for p in parts):
        return ""
    return " ".join(parts)


def mask_details(method: str, value: str) -> str:
    """Как показывать реквизит в чатах персонала и в карточке клиента."""
    v = re.sub(r"[\s\-]", "", str(value or ""))
    if method == CARD and len(v) >= 4:
        return "•••• " + v[-4:]
    if method == SBP and len(v) >= 4:
        return v[:2] + "•" * (len(v) - 6) + v[-4:]
    return v


def staff_details(method: str, value: str) -> str:
    """Реквизит в том виде, в каком его видит персонал.

    Маска годится клиенту и истории, но НЕ тому, кто переводит руками: по
    `79•••••4567` перевод не сделать, и заявка встанет. Поэтому полный номер
    показывается ровно там, где по нему платит человек, — на ручном пути.
    Когда платит рельс, номер не нужен никому: он уходит в API. Нашёл codex.
    """
    if route(method) == "manual":
        return re.sub(r"[\s\-]", "", str(value or ""))
    return mask_details(method, value)


def refuse(method: str, details: str, bank: str = "", full_name: str = "") -> str:
    """Причина отказа или '' — одна на бота, сайт и Mini App.

    Проверяет ровно то, без чего выплата не состоится, и в том же порядке, в
    каком поля показываются клиенту.
    """
    if method not in methods():
        return "Этот способ выплаты сейчас недоступен."
    if not normalize_details(method, details):
        if method == CARD:
            return ("Проверьте номер карты — он не проходит контрольную сумму. "
                    "Так отсеивается опечатка в одной цифре: перевод по такому "
                    "номеру ушёл бы чужому человеку.")
        return "Неверный формат телефона. Пример: 79001234567."
    if needs_bank(method):
        if not _vertu().normalize_bank(bank):
            return "Выберите банк получателя из списка."
    if needs_full_name(method) and not normalize_full_name(full_name):
        return ("Укажите ФИО получателя как в банке — два-три слова "
                "(например: Иван Иванов). Этого требует платёжный партнёр.")
    return ""


def target(row) -> dict:
    """Куда платить по этой заявке. row — строка sell_orders (dict/sqlite3.Row).

    Единственное место, где решается «какой реквизит настоящий»: у старых
    заявок способ не записан вовсе, и их реквизит лежит в `sbp_phone`.
    Догадываться об этом на каждой поверхности значит однажды заплатить не по
    тому полю.
    """
    def _get(key):
        try:
            v = row[key]
        except (KeyError, IndexError, TypeError):
            return ""
        return "" if v is None else str(v)

    method = (_get("payout_method") or SBP).lower()
    details = _get("payout_details") or (_get("sbp_phone") if method == SBP else "")
    return {
        "method": method,
        "details": details,
        "bank": _get("payout_bank"),
        "full_name": _get("payout_name"),
        "route": route(method),
        "shown": mask_details(method, details),
        # Для персонала — то, чем можно воспользоваться: см. staff_details().
        "for_staff": staff_details(method, details),
    }


# ── отправка рублей ──────────────────────────────────────────────────────────

def _row(sell_id):
    return _store().get(int(sell_id))


def already_sent(sell_id) -> dict:
    """Уже уходила ли выплата по этой заявке. {} — не уходила.

    Единственная защита от второй отправки: у Vertu нет идемпотентности по
    нашему deal_id (каждый вызов создаёт НОВУЮ выплату), поэтому «нажали кнопку
    дважды» стоило бы ровно двух переводов клиенту.
    """
    row = _row(sell_id)
    if row is None:
        return {}
    try:
        ref, st = row["payout_ref"], row["payout_status"]
    except (KeyError, IndexError):
        return {}
    # Невнятный исход блокирует повтор так же, как живая выплата: рельс ответил
    # успехом без идентификатора, то есть перевод мог УЙТИ, а сослаться на него
    # нечем. Вторая кнопка здесь стоила бы второго перевода вслепую.
    if str(st or "").lower() == "unknown":
        return {"ref": ref or "", "status": "unknown", "needs_human": True}
    if not ref:
        return {}
    # Отклонённую провайдером выплату повторить МОЖНО и нужно — деньги не ушли.
    if str(st or "").lower() in REJECTED:
        return {}
    return {"ref": ref, "status": st}


def send_rub(sell_id, callback_url: str = "") -> dict:
    """Отправить рубли клиенту по заявке на продажу.

    ⚠️ Это перевод денег. Звать ТОЛЬКО после того, как приход крипты подтверждён
    в блокчейне (`bot/sell_guard.verify_sell_deposit`) — модуль этого сам не
    проверяет и проверить не может: он про рубли, а не про цепь.

    Возвращает:
      {"ok": True, "manual": True}            — рельса нет, платит человек
      {"ok": True, "ref": …, "status": …}     — выплата создана у провайдера
      {"ok": False, "error": …}               — не создана, деньги НЕ ушли
    """
    row = _row(sell_id)
    if row is None:
        return {"ok": False, "error": f"Заявка #{sell_id} не найдена"}
    dst = target(row)
    if dst["route"] != "vertu":
        return {"ok": True, "manual": True, "target": dst}

    seen = already_sent(sell_id)
    if seen.get("needs_human"):
        return {"ok": False, "needs_human": True, "target": dst,
                "error": "Прошлая попытка закончилась невнятно — рельс ответил "
                         "успехом без номера выплаты. Повтор вслепую может "
                         "отправить деньги второй раз: сверьте в кабинете Vertu."}
    if seen:
        # Не ошибка и не успех: выплата уже живёт, нужен её статус, а не вторая.
        return {"ok": True, "duplicate": True, "ref": seen["ref"],
                "status": seen["status"], "target": dst}

    # Реквизит перепроверяется здесь, а не только при приёме заявки: между
    # приёмом и выплатой проходят часы, за которые могли снять рельс, поменять
    # список банков или отредактировать строку в базе руками.
    why = refuse(dst["method"], dst["details"], dst["bank"], dst["full_name"])
    if why:
        return {"ok": False, "error": f"Реквизит выплаты не годится: {why}"}

    try:
        rub = float(row["rub_amount"] or 0)
    except (TypeError, ValueError):
        rub = 0.0
    if rub <= 0:
        return {"ok": False, "error": "Сумма выплаты нулевая — платить нечего"}

    from providers.vertu import VertuProvider
    res = VertuProvider().create_payout(
        order_id=f"sell{int(sell_id)}",
        amount=rub,
        bank=dst["bank"],
        bank_details=normalize_details(dst["method"], dst["details"]),
        full_name=normalize_full_name(dst["full_name"]),
        payment_method=dst["method"],
        user_id=row["user_id"],
        callback_url=callback_url or None,
    )
    if res.get("error"):
        logger.error("продажа #%s: выплата не создана — %s", sell_id, res["error"])
        return {"ok": False, "error": res["error"], "target": dst}

    ref = res.get("payout_id") or ""
    # Ответ без номера выплаты — не успех. Перевод мог уйти (рельс ответил
    # 200), но сослаться на него нечем: ни статус спросить, ни отменить.
    # Считать это удачей значит закрыть заявку по переводу, которого мы не
    # видим; считать сбоем и вернуть в очередь — значит разрешить вторую
    # кнопку и второй перевод. Поэтому третий исход: заявка остаётся занятой,
    # решает человек, сверившись с кабинетом. Нашёл codex.
    _store().record_provider(int(sell_id),provider='vertu',ref=ref,
        status="unknown" if not ref else (res.get("status") or "pending"))
    if not ref:
        logger.error("продажа #%s: рельс ответил успехом без номера выплаты — "
                     "нужен человек", sell_id)
        return {"ok": False, "needs_human": True, "target": dst,
                "error": "Партнёр принял выплату, но не вернул её номер. Деньги "
                         "могли уйти — проверьте в кабинете Vertu, прежде чем "
                         "повторять."}
    logger.info("продажа #%s: выплата %s ₽ создана, ref=%s", sell_id, rub, ref)
    return {"ok": True, "ref": ref, "status": res.get("status") or "pending",
            "target": dst, "raw": res.get("raw")}


# Терминальные исходы выплаты. «Создана» и «в обработке» сюда не входят
# намеренно: Vertu отвечает на создание Pending и может отклонить выплату
# спустя минуты, а заявка, помеченная выплаченной по факту СОЗДАНИЯ, после
# отказа остаётся paid навсегда — ни очередь, ни сторож её больше не увидят.
SETTLED = "paid"
REJECTED = ("failed", "declined", "revoked")


def is_settled(status: str) -> bool:
    return str(status or "").lower() == SETTLED


def is_rejected(status: str) -> bool:
    return str(status or "").lower() in REJECTED


def mark_settled(sell_id) -> bool:
    """Заявка выплачена по ФАКТУ зачисления. True — перевёл именно этот вызов.

    Возвращаемое значение важнее самого перехода: начисление VIP-объёма и
    письмо клиенту «выполнено» обязаны случиться ровно один раз, а сюда
    приходят и фоновой обход, и обратный вызов провайдера — одновременно.
    """
    return _store().mark_settled(int(sell_id))


def mark_rejected(sell_id) -> bool:
    """Рельс отказал: заявка возвращается в очередь выплат. True — вернул этот вызов.

    Возврат именно в 'pending', а не в 'failed': монеты клиента у нас, долг
    никуда не делся, и заявка обязана снова попасться на глаза человеку.

    Открывается ТОЛЬКО заявка в полёте ('paying'). Выплаченная заявка
    терминальна: обход и обратный вызов спрашивают статус независимо, ответы
    приходят вперемешку, и устаревшее «отклонено» после свежего «зачислено»
    вернуло бы закрытый долг в очередь — то есть разрешило бы заплатить
    второй раз по уже оплаченной заявке. Нашёл codex.
    """
    return _store().mark_rejected(int(sell_id))


def stale_claims(minutes: int = 15) -> list:
    """Заявки, занятые под выплату, но так и не получившие номер выплаты.

    Между «занять строку» и «записать номер выплаты» стоит вызов чужого API.
    Если процесс в этот момент умрёт, строка останется в 'paying' навсегда:
    кнопка её больше не займёт, а обход статусов не увидит — он смотрит только
    заявки с номером. Долг клиента при этом настоящий. Нашёл codex.

    Сама по себе такая строка НЕ разжимается автоматически: перевод мог уйти —
    запрос ушёл из процесса до его смерти. Решает человек, сверившись с
    кабинетом; отсюда — только список для тревоги.
    """
    return _store().stale_unreferenced(int(minutes))


def release_claim(sell_id) -> bool:
    """Вернуть зависшую заявку в очередь выплат. Решение человека, не автомата.

    Открывает только строку БЕЗ номера выплаты: там, где номер есть, выплата
    существует, и «вернуть в очередь» означало бы разрешить второй перевод.
    """
    return _store().release_unreferenced(int(sell_id))


def refresh_status(sell_id) -> dict:
    """Спросить провайдера, дошли ли рубли. Возвращает {"status": …} нормализованный."""
    row = _row(sell_id)
    if row is None:
        return {"status": "unknown"}
    try:
        ref = row["payout_ref"]
    except (KeyError, IndexError):
        ref = None
    if not ref:
        return {"status": "none"}
    from providers.vertu import VertuProvider
    res = VertuProvider().get_payout_status(ref) or {}
    st = res.get("status") or "unknown"
    if st != "unknown":
        _store().update_payout_status(int(sell_id),st)
    return {"status": st, "raw_status": res.get("raw_status"), "ref": ref}
