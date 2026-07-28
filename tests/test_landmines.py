#!/usr/bin/env python3
"""Проверки на «мины» — дефекты, которые выглядят как рабочий код.

Все три случая ниже реально произошли 19.07.2026 и стоили месяца тихих потерь.
Объединяет их то, что код КАЖЕТСЯ исправным: тесты зелёные, ошибок в логах нет,
ревью взглядом ничего не замечает. Поэтому ловим их детерминированно.

Намеренно БЕЗ ИИ. Локальная модель на 7B давала бы ложные срабатывания на каждом
деплое и при этом пропускала тонкое — а хуже всего создавала бы ощущение, что код
проверен. Здесь только точные правила под конкретные классы дефектов.

Запуск: python3 tests/test_landmines.py
"""
import os
import re
import sys
import ast
import hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "relay")
FAILURES = []


def fail(check, msg):
    FAILURES.append((check, msg))


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────
# 1. Дублирующиеся модули, перекрытые sys.path
# ─────────────────────────────────────────────────────────────────────
# Было: relay-fastapi/services/payment_service.py на 169 строк короче боевого,
# без цепочки эскалации. Не грузился (path перекрывал), но убери одну строку
# sys.path.insert — и прод молча поехал бы на старом коде.
def check_no_diverging_duplicates():
    dup_dir = os.path.join(ROOT, "relay-fastapi", "services")
    if not os.path.isdir(dup_dir):
        return
    for name in os.listdir(dup_dir):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        dup, canon = os.path.join(dup_dir, name), os.path.join(CANON, "services", name)
        if not os.path.exists(canon):
            continue
        dup_src = _read(dup)
        # Шим — законный вариант: он переадресует на канонический файл.
        if "/root/relay/services/" in dup_src and len(dup_src) < 2000:
            continue
        if hashlib.sha256(dup_src.encode()).hexdigest() != \
           hashlib.sha256(_read(canon).encode()).hexdigest():
            fail("дубли-мины",
                 f"relay-fastapi/services/{name} разошёлся с relay/services/{name}. "
                 f"Он не грузится (path), но станет боевым при любой правке импортов. "
                 f"Сделай его шимом или синхронизируй.")


# ─────────────────────────────────────────────────────────────────────
# 2. Мёртвые ключи конфигурации
# ─────────────────────────────────────────────────────────────────────
# Было: PROVIDER_CONFIG['weight'] не читал никто. Правка веса выглядела бы
# сделанной, а распределение трафика не менялось.
def check_config_keys_are_read():
    src = _read(os.path.join(CANON, "services", "smart_router.py"))
    m = re.search(r"^PROVIDER_CONFIG\s*=\s*\{", src, re.M)
    if not m:
        return
    try:
        node = next(n for n in ast.parse(src).body
                    if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "PROVIDER_CONFIG" for t in n.targets))
    except StopIteration:
        return
    keys = set()
    for v in node.value.values:
        if isinstance(v, ast.Dict):
            keys.update(k.value for k in v.keys if isinstance(k, ast.Constant))
    py = []
    for base in ("relay", "relay-fastapi", "bot"):
        for dp, _, fs in os.walk(os.path.join(ROOT, base)):
            if "venv" in dp or "__pycache__" in dp:
                continue
            py += [os.path.join(dp, f) for f in fs if f.endswith(".py")]
    blob = "\n".join(_read(p) for p in py)
    for key in sorted(keys):
        if key in ("weight",):
            continue  # известен как мёртвый, помечен комментарием в коде
        if not re.search(rf'["\']{re.escape(key)}["\']\s*\]|get\(\s*["\']{re.escape(key)}["\']', blob):
            fail("мёртвый конфиг",
                 f"PROVIDER_CONFIG['{key}'] нигде не читается — правка этого поля "
                 f"ничего не изменит, но будет выглядеть сделанной.")


# ─────────────────────────────────────────────────────────────────────
# 3. Fail-open в стражах денег
# ─────────────────────────────────────────────────────────────────────
# Было: except Exception → {"action": "ok"} в circuit-breaker выплат. Сбой
# проверки означал РАЗРЕШЕНИЕ отправить крипту.
_MONEY_FILES = ("payout_circuit.py", "payout_guard.py", "sell_guard.py",
                "safety.py", "money.py")
_ALLOW = re.compile(r'["\']action["\']\s*:\s*["\'](ok|allow|confirmed)["\']')


def check_no_fail_open_in_guards():
    for base in (os.path.join(CANON, "services"), os.path.join(CANON, "core")):
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if name not in _MONEY_FILES:
                continue
            path = os.path.join(base, name)
            try:
                tree = ast.parse(_read(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                seg = ast.get_source_segment(_read(path), node) or ""
                if _ALLOW.search(seg):
                    fail("fail-open",
                         f"{name}:{node.lineno} — обработчик исключения возвращает "
                         f"разрешающий вердикт. Сбой проверки должен ЗАПРЕЩАТЬ "
                         f"движение денег, а не разрешать.")


# ─────────────────────────────────────────────────────────────────────
# 4. Экспирация сессий мимо expires_at
# ─────────────────────────────────────────────────────────────────────
# Было: жёсткие 900 с при окне сессии 30 мин — клиент терял кнопку «я оплатил»
# на половине срока. 260 сессий из 426 за месяц.
def check_session_expiry_uses_expires_at():
    for base in ("relay", "relay-fastapi"):
        p = os.path.join(ROOT, base, "services", "polling_service.py")
        if not os.path.exists(p):
            continue
        src = _read(p)
        if "/root/relay/services/" in src and len(src) < 2000:
            continue  # шим
        if "status='expired'" not in src:
            continue
        if "expires_at" not in src:
            fail("экспирация",
                 f"{base}/services/polling_service.py помечает сессии expired, "
                 f"не читая expires_at — сессия умрёт раньше срока.")
        if re.search(r"age_seconds\s*[<>]=?\s*\d{3,}", src):
            fail("экспирация",
                 f"{base}/services/polling_service.py: порог экспирации зашит "
                 f"числом. Срок задаёт expires_at сессии, а не константа.")


def check_every_provider_has_receipt_verdict():
    """Каждый провайдер должен быть либо в _ROUTES, либо в _NO_CHANNEL.

    20.07.2026 заявка на 30 000 ₽ ушла в Declined: клиент заплатил через Vertu,
    а канала доставки чека у Vertu не было — эндпоинт /v1/wt_receipts/ в API
    существовал, но реализован не был. Пропуск был незаметен, потому что нигде
    не требовалось явно ответить на вопрос «а чем мы доказываем оплату у этого
    провайдера». Теперь новый провайдер обязан ответить — хотя бы «нечем».
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(base, "relay"))
    try:
        from core.receipts import _ROUTES, _NO_CHANNEL
        from services.smart_router import PROVIDER_CONFIG
    except Exception as e:
        fail("чеки", f"не удалось загрузить маршрутизатор чеков: {type(e).__name__}: {e}")
        return

    known = set(_ROUTES) | set(_NO_CHANNEL)
    for cls_name in PROVIDER_CONFIG:
        # BrabusProvider -> brabus, XPayConnectProvider -> xpay(connect)
        short = cls_name.replace("Provider", "").lower()
        if short in known or any(k in short or short in k for k in known):
            continue
        fail("чеки",
             f"{cls_name}: не определено, как доставить провайдеру чек об оплате. "
             f"Добавьте обработчик в core/receipts.py _ROUTES либо, если API "
             f"такого не умеет, внесите в _NO_CHANNEL — тогда чек уйдёт оператору "
             f"вручную, а клиенту не скажут ложное «принято».")


def check_no_dead_state_machines():
    """Состояние, которое только читают и никогда не пишут, = мёртвый путь.

    27.07.2026: команда /approve обещала 2FA-подтверждение крупной выплаты, но
    словарь pending_large_payouts никто не наполнял — единственным возможным
    ответом было «Нет ожидающей выплаты с таким ID». Такой код опаснее
    отсутствующего: на бумаге у крупных сумм есть страховка, в реальности её
    нет, и это незаметно, пока не полезешь читать.
    """
    src = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    if not src:
        return
    for name in re.findall(r'^([a-z_][a-z_0-9]*)\s*=\s*\{\}\s*(?:#.*)?$', src, re.M):
        writes = len(re.findall(rf'\b{name}\[[^\]]+\]\s*=(?!=)', src))
        writes += len(re.findall(rf'\b{name}\.(?:setdefault|update|pop)\(', src))
        reads = len(re.findall(rf'\b{name}\.get\(|\b{name}\[', src))
        if writes == 0 and reads > 0:
            fail("мёртвый путь",
                 f"{name}: состояние читается ({reads} раз), но не записывается "
                 f"НИКОГДА — команда/обработчик поверх него недостижим. Либо "
                 f"подключите запись, либо уберите путь, чтобы он не выглядел "
                 f"работающей страховкой.")


def check_manual_payout_uses_agreed_quote():
    """Ручные пути выплаты обязаны брать объём из зафиксированной котировки.

    27.07.2026: process_payout научили платить обещанное, а панель работника
    (/worker) продолжала считать объём по СВЕЖЕМУ курсу. Из-за строгого стража
    к работнику уходит большинство заявок — то есть обещание «курс действует
    15 минут» не выполнялось как раз на самом частом пути. Единое решение —
    payout_verdict(); прямой пересчёт rub/get_rate_with_markup в местах выдачи
    означает, что путь снова разошёлся.
    """
    src = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    if not src or "def payout_verdict" not in src:
        return
    for fn_name in ("cmd_worker_panel", "worker_send_start", "notify_workers_paid"):
        m = re.search(r"(?:async )?def " + fn_name + r"\(.*?\n(?=\n(?:async )?def |\n@)", src, re.S)
        if not m:
            continue
        body = m.group(0)
        if "payout_verdict" in body:
            continue
        if re.search(r"get_rate_with_markup|/\s*rate", body):
            fail("выплаты",
                 f"{fn_name}: объём крипты считается по текущему курсу вместо "
                 f"зафиксированной котировки. Использовать payout_verdict(), иначе "
                 f"клиент получит не то, что ему обещали при создании заявки.")


def check_alert_throttle_is_durable():
    """Троттлинг алертов не должен жить в памяти процесса.

    27.07.2026: `last_sent = {}` внутри conversion_watch_task обнулялся при
    каждом рестарте, а деплой-таймер перезапускал relay-fastapi каждые 15 минут.
    Правило «не чаще раза в 6 часов» превратилось в «4 раза в час»: сигнал о том,
    что 13 947 ₽ клиентских денег не выданы, пришёл админу ~80 раз и перестал
    читаться. Состояние алертов обязано лежать в БД (core/alert_throttle).
    """
    src = _read(os.path.join(ROOT, "relay-fastapi", "main.py"))
    if not src:
        return
    m = re.search(r"async def conversion_watch_task\(.*?\n(?=\nasync def |\ndef |\n@)",
                  src, re.S)
    body = m.group(0) if m else ""
    if re.search(r"^\s*last_sent\s*=\s*\{\}", body, re.M):
        fail("алерты",
             "conversion_watch_task держит троттлинг в памяти (last_sent={}). "
             "Сервис перезапускается деплоем — окно молчания обнулится и админ "
             "утонет в дублях. Использовать core.alert_throttle.should_send.")
    elif "alert_throttle" not in body:
        fail("алерты",
             "conversion_watch_task шлёт алерты без долговечного троттлинга "
             "(core.alert_throttle.should_send).")


def check_deploy_restarts_only_on_change():
    """Деплой не должен перезапускать сервисы, когда код не менялся.

    Безусловный `systemctl restart` каждые 15 минут рвёт запросы клиентов в
    полёте и обнуляет любое состояние в памяти процесса — включая троттлинг
    алертов выше. Гейт по раскатанному реву обязателен.
    """
    src = _read(os.path.join(ROOT, "deploy.sh"))
    if not src:
        return  # скрипт вне репозитория — проверять нечего
    if "restart relay-fastapi" not in src:
        return
    guarded = ".deploy_state" in src and re.search(r'if \[ "\$DEPLOYED" = "\$NEW_REV" \]', src)
    if not guarded:
        fail("деплой",
             "deploy.sh перезапускает сервисы без проверки, изменился ли код. "
             "Нужен гейт по раскатанному реву (файл состояния .deploy_state).")


# Кошелёк умеет отправлять эти валюты → валюта ОБЯЗАНА быть в реестре обмена.
# Соответствие явное: по имени файла его не вывести (btc_wallet платит и LTC,
# tron_wallet — это USDT-TRC20).
_WALLET_CURRENCIES = {
    "btc_wallet.py": ("BTC", "LTC"),
    "tron_wallet.py": ("USDT",),
    "evm_wallet.py": ("ETH",),
    "xrp_wallet.py": ("XRP",),
}


def _currency_registry_keys(src):
    """Ключи CURRENCY_NETWORKS из assets.py через ast (без импорта модуля)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "CURRENCY_NETWORKS":
                if isinstance(node.value, ast.Dict):
                    return {k.value for k in node.value.keys
                            if isinstance(k, ast.Constant)}
    return None


def check_wallet_currencies_are_offered():
    """Валюта с готовым кошельком обязана предлагаться клиенту.

    Самый дорогой тихий сбой этого проекта — не падение, а работа, до которой
    никто не дошёл. XRP пролежал так: полный модуль кошелька, флаг выплат,
    резервы, лимит отправки, зелёный тест — и НОЛЬ упоминаний в assets.py,
    то есть заявку на XRP нельзя было оформить в принципе. Ни один тест этого
    не ловил, потому что каждый слой по отдельности исправен.
    """
    src = _read(os.path.join(ROOT, "relay", "core", "assets.py"))
    if not src:
        return
    offered = _currency_registry_keys(src)
    if offered is None:
        fail("реестр валют", "не удалось разобрать CURRENCY_NETWORKS в assets.py")
        return
    wallet_dir = os.path.join(ROOT, "relay", "wallet")
    for module, currencies in sorted(_WALLET_CURRENCIES.items()):
        if not os.path.exists(os.path.join(wallet_dir, module)):
            continue          # кошелька нет — предлагать нечего
        missing = [c for c in currencies if c not in offered]
        if missing:
            fail("реестр валют",
                 f"кошелёк {module} умеет отправлять {', '.join(missing)}, "
                 f"но в assets.CURRENCY_NETWORKS этой валюты нет — клиент не "
                 f"может оформить заявку, вся работа по кошельку не приносит "
                 f"ничего. Добавить валюту в реестр вместе с валидацией адреса.")


def main():
    for fn in (check_no_diverging_duplicates, check_config_keys_are_read,
               check_no_fail_open_in_guards, check_session_expiry_uses_expires_at,
               check_every_provider_has_receipt_verdict,
               check_alert_throttle_is_durable, check_deploy_restarts_only_on_change,
               check_manual_payout_uses_agreed_quote, check_no_dead_state_machines,
               check_wallet_currencies_are_offered):
        try:
            fn()
        except Exception as e:
            fail("сама проверка", f"{fn.__name__}: {type(e).__name__}: {e}")

    if FAILURES:
        print(f"❌ Найдено мин: {len(FAILURES)}\n")
        for check, msg in FAILURES:
            print(f"  [{check}] {msg}\n")
        return 1
    print("✅ Мин не найдено: дублей нет, конфиг читается, стражи fail-closed, "
          "экспирация по expires_at.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
