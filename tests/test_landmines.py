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
import json
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


# ─────────────────────────────────────────────────────────────────────
# 11. Тесты обязаны проверять СВОЙ код, а не боевой
# ─────────────────────────────────────────────────────────────────────
# /root — одновременно репозиторий и прод, поэтому проверки идут в git worktree.
# Изоляция держится ровно до первого модуля, который вписывает в sys.path
# зашитый «/root/relay»: дальше копия исполняет свой файл, но импортирует
# зависимости из БОЕВОГО каталога. Так и было в offerings.py — тест витрины
# гонял мастеровый core.assets, зелёный результат ничего не значил.
_TESTED_IMPORTS = ("core.assets", "core.address", "services.offerings")


def check_tests_import_their_own_tree():
    relay_dir = os.path.join(ROOT, "relay")
    if not os.path.isdir(relay_dir):
        return

    # Сначала — сами файлы тестов. Проверка ниже импортирует модули САМА и
    # потому всегда попадает в своё дерево; она не видела, что тест внутри
    # прописал боевой путь руками. Два набора так и проверяли ПРОД, оставаясь
    # зелёными на заведомо сломанном коде ветки (30.07.2026).
    tdir = os.path.dirname(os.path.abspath(__file__))
    for fn in sorted(os.listdir(tdir)):
        if not fn.startswith("test_") or not fn.endswith(".py"):
            continue
        src = _read(os.path.join(tdir, fn))
        for i, ln in enumerate(src.splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            m = re.search(r"""sys\.path\.insert\([^)]*["'](/root/[^"']+)["']""", ln)
            if m:
                fail("изоляция тестов",
                     f"tests/{fn}: стр. {i} — путь к коду прописан абсолютно "
                     f"({m.group(1)}). Набор проверяет ТО ДЕРЕВО, а не своё: "
                     f"правки в worktree он не видит и зеленеет на сломанном коде")
    import subprocess
    # Каждый модуль — в СВОЁМ интерпретаторе. В общем процессе первый удачный
    # импорт core.assets осел бы в sys.modules и прикрыл собой подмену у всех
    # последующих: проверка была бы зелёной ровно потому, что порядок удачный.
    for mod in _TESTED_IMPORTS:
        code = (
            "import sys, json, importlib;"
            f"sys.path.insert(0, {relay_dir!r});"
            f"importlib.import_module({mod!r});"
            "print(json.dumps({n: m.__file__ for n, m in sys.modules.items() "
            "if getattr(m, '__file__', None) and '/relay/' in m.__file__}))"
        )
        try:
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, timeout=60, cwd=ROOT)
        except Exception as e:
            fail("изоляция тестов", f"не удалось проверить импорт {mod}: {e}")
            continue
        if out.returncode != 0:
            fail("изоляция тестов",
                 f"импорт {mod} падает: {out.stderr.strip()[-300:]}")
            continue
        try:
            loaded = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception:
            fail("изоляция тестов", f"неразборчивый ответ по {mod}: {out.stdout[:200]!r}")
            continue
        alien = {n: p for n, p in loaded.items()
                 if not os.path.abspath(p).startswith(ROOT + os.sep)}
        if alien:
            names = ", ".join(f"{n} ← {p}" for n, p in sorted(alien.items())[:4])
            fail("изоляция тестов",
                 f"при импорте {mod} подтянулись модули из ЧУЖОГО дерева: {names}. "
                 f"Проверяем мы {ROOT}, значит где-то в цепочке зашит абсолютный "
                 f"путь к боевому каталогу — тест будет зелёным, проверив не тот "
                 f"код. Путь в sys.path выводить от __file__ модуля.")


# ─────────────────────────────────────────────────────────────────────
# 12. Монета в реестре обязана иметь СВОЙ источник курса
# ─────────────────────────────────────────────────────────────────────
# Список валют и список котировок — разные таблицы в разных файлах. Монета,
# добавленная в реестр и забытая в котировках, получала цену чужой монеты:
# в боте стоял молчаливый дефолт на USDT (XRP котировался бы по цене тезера,
# клиент получил бы вдвое больше монет за свои деньги), на сайте — KeyError
# на живом клиенте. Ни то, ни другое не ловилось ничем.
_RATE_TABLES = (
    ("bot/main_bot.py", "_COIN_SOURCES"),
    ("relay/utils/exchange_calc.py", "_COINGECKO_IDS"),
    ("relay/utils/exchange_calc.py", "_FALLBACK_RATES"),
)


def _dict_literal_keys(src, name):
    """Ключи словаря верхнего уровня по имени. None — если не разобрали."""
    try:
        tree = ast.parse(src)
    except Exception:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return None
        keys = set()
        for k in node.value.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
            else:
                return None      # вычисляемый ключ — статикой не разберём
        return keys
    return None


def check_every_currency_has_a_price_source():
    assets_src = _read(os.path.join(ROOT, "relay", "core", "assets.py"))
    if not assets_src:
        return
    currencies = _currency_registry_keys(assets_src)
    if currencies is None:
        return               # разбор реестра уже проверяется отдельной миной
    for rel, table in _RATE_TABLES:
        src = _read(os.path.join(ROOT, rel))
        if not src:
            continue
        keys = _dict_literal_keys(src, table)
        if keys is None:
            fail("источник курса", f"не удалось разобрать {table} в {rel}")
            continue
        missing = sorted(c for c in currencies if c not in keys)
        if missing:
            fail("источник курса",
                 f"{rel}: в {table} нет {', '.join(missing)}, хотя валюта есть в "
                 f"assets.CURRENCY_NETWORKS. Монета без своей котировки получит "
                 f"чужую цену или уронит расчёт у живого клиента.")


# ─────────────────────────────────────────────────────────────────────
# 13. Поверхность, не собирающая тег, не должна предлагать валюту с тегом
# ─────────────────────────────────────────────────────────────────────
# Витрина (services.offerings) общая на бот, сайт и Mini App. Резерв, заданный
# ради бота, открывает валюту ВЕЗДЕ. Бот умеет спросить destination tag; форма
# кабинета и Mini App принимают одно поле адреса. Без защиты клиент оформил бы
# на сайте перевод на биржевой classic-адрес без тега: заявка создаётся, оплата
# проходит, перевод попадает на общий счёт биржи и не зачисляется никому.
# Нашёл это внешний ревью (codex) — свой критик пропустил.
# Функции, которые пишут заявку в orders, но получают адрес уже собранным
# выше по стеку. У каждой всё равно обязан быть свой резолв — см. комментарий
# в _finalize_order: именно «за тег отвечает вызывающий» и развело четыре места.
# Свести адрес и тег умеют эти три. Четвёртое — единственное ЯВНОЕ исключение:
# подарочная заявка создаётся до того, как получатель известен, и пишет
# заведомо невыплачиваемую заглушку; настоящий адрес с тегом появляется при
# выкупе. Исключение названо функцией, а не молчаливым пропуском, — чтобы новая
# точка не проскочила, сославшись на «у нас особый случай».
_RESOLVERS = ("_resolve_destination(", "_canonical_address(", "canonical_address(",
              "_gift_placeholder_address(")


def check_tagless_surfaces_refuse_tagged_currencies():
    """Каждая точка создания заявки обязана сама свести адрес и тег.

    Витрина `services.offerings` общая на бот, сайт и Mini App: резерв,
    заданный ради одной поверхности, открывает валюту ВЕЗДЕ. Точка, которая
    просто запишет введённый адрес, создаст заявку на биржевой classic-адрес
    без тега — перевод подтвердится сетью и не зачислится никому.

    Первую такую дыру (сайт и Mini App) нашёл внешний ревью codex, свой критик
    пропустил. Вторую — эта проверка: legacy-обработчик handle_webapp в боте
    брал currency прямо из клиентских данных и тег не спрашивал вовсе.
    """
    for rel in ("relay-fastapi/main.py", "bot/main_bot.py"):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            fail("тег на поверхности", f"{rel} не разбирается")
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if "INSERT INTO orders" not in body:
                continue
            # Комментарии вон: первая версия проверки засчитала за вызов СЛОВО
            # canonical_address из поясняющего комментария рядом. Проверка,
            # которую обманывает комментарий, — не проверка.
            code = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
            if not any(r in code for r in _RESOLVERS):
                fail("тег на поверхности",
                     f"{rel}: {node.name}() (стр. {node.lineno}) создаёт заявку, "
                     f"но не сводит адрес и тег назначения. Для валюты с тегом "
                     f"(XRP) это заявка на биржевой адрес БЕЗ тега: перевод "
                     f"подтвердится сетью и не зачислится получателю. Вызвать "
                     f"canonical_address перед вставкой — она идемпотентна, "
                     f"даже если выше по стеку это уже сделали.")


# ─────────────────────────────────────────────────────────────────────
# 14. Код нельзя грузить по зашитому боевому пути
# ─────────────────────────────────────────────────────────────────────
# `/root` — одновременно репозиторий и прод. Изолирует только git worktree, и
# то лишь файлы: если модуль делает sys.path.insert(0, "/root/relay") или
# грузит файл по абсолютному пути, копия исполняет СВОЙ верхний уровень, но
# импортирует зависимости из БОЕВОГО каталога. Дальше всё выглядит исправным:
# тесты зелёные, py_compile молчит, diff чистый — а проверялся другой код.
# Так вышло дважды подряд: сначала bot/main_bot.py и relay-fastapi/main.py,
# потом шимы relay-fastapi/services/* и десяток модулей relay/. Память тут не
# помогает — путь пишется машинально, поэтому правило машинное.
#
# Ловим ровно места ЗАГРУЗКИ КОДА: sys.path, spec_from_file_location и open()
# исходника/шаблона. Данные (общая БД /root/exchange.db, /root/relay/logs,
# /root/wallet_data) намеренно живут по абсолютному пути и общие у копий —
# их правило не касается.
_CODE_SUFFIXES = (".py", ".html", ".htm", ".j2", ".jinja", ".jinja2")
_PATH_CALLS = ("sys.path.insert", "sys.path.append", "path.insert", "path.append",
               "spec_from_file_location")


def _call_name(node):
    """Пунктирное имя вызываемого: sys.path.insert, os.path.join, open."""
    parts = []
    cur = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def check_no_code_loaded_from_hardcoded_path():
    """Ни один модуль не грузит код по абсолютному пути в боевой каталог."""
    skip_dirs = {"venv", "__pycache__", "backups", "node_modules", ".git", "tests"}
    for top in ("bot", "relay", "relay-fastapi"):
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                src = _read(full)
                if not src:
                    continue
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue          # синтаксис — забота py_compile, не наша
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name = _call_name(node)
                    is_path = name.endswith(_PATH_CALLS)
                    is_open = name == "open" or name.endswith(".open")
                    if not (is_path or is_open):
                        continue
                    for arg in list(node.args) + [k.value for k in node.keywords]:
                        if not (isinstance(arg, ast.Constant)
                                and isinstance(arg.value, str)):
                            continue
                        val = arg.value
                        if not val.startswith("/root/"):
                            continue
                        if is_open and not val.endswith(_CODE_SUFFIXES):
                            continue   # данные по общему пути — это норма
                        fail("зашитый боевой путь",
                             f"{rel}: стр. {arg.lineno}, {name}({val!r}) — код "
                             f"грузится по абсолютному пути в боевой каталог. "
                             f"Копия проекта (worktree, проверочный клон) будет "
                             f"исполнять свой файл, но тянуть зависимости из "
                             f"прода: проверка пройдёт по ЧУЖОМУ коду и ничего "
                             f"не докажет. Выводить путь от __file__.")


# ─────────────────────────────────────────────────────────────────────
# 15. Ссылка на обозреватель — только из core.txid
# ─────────────────────────────────────────────────────────────────────
# Карта «валюта → обозреватель» жила в четырёх местах: бот (/mystatus и
# /myhistory), /api личного кабинета, инлайн-JS страницы /pay и Mini App. Копии
# разошлись — каждая знала три-четыре монеты из шести, а бот вдобавок угадывал
# «всё, что не BTC и не LTC, — tronscan». Выполненная ETH- или XRP-заявка
# показывала клиенту либо пустоту, либо чужую сеть, где транзакции нет.
# Кнопка «🔍 Транзакция в блокчейне» — единственное доказательство выдачи,
# которое клиент проверяет сам; сломанное доказательство хуже отсутствующего.
_EXPLORER_HOSTS = ("mempool.space/tx", "blockchair.com/litecoin/transaction",
                   "tronscan.org/#/transaction", "etherscan.io/tx", "xrpscan.com/tx")


def check_explorer_links_have_one_source():
    """Адрес обозревателя встречается только в core/txid.py."""
    owner = os.path.join("relay", "core", "txid.py")
    skip_dirs = {"venv", "__pycache__", "backups", "node_modules", ".git", "tests", "docs"}
    for top in ("bot", "relay", "relay-fastapi"):
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if not fn.endswith((".py", ".html", ".j2", ".jinja2")):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                if rel == owner:
                    continue
                src = _read(os.path.join(dirpath, fn))
                # Комментарий, объясняющий беду, не должен считаться бедой:
                # берём только строки, где адрес стоит внутри кавычек.
                for host in _EXPLORER_HOSTS:
                    for m in re.finditer(re.escape(host), src):
                        line = src[:m.start()].count("\n") + 1
                        head = src.rfind("\n", 0, m.start())
                        prefix = src[head + 1:m.start()]
                        if '"' not in prefix and "'" not in prefix and "`" not in prefix:
                            continue      # текст комментария, а не ссылка
                        fail("ссылка на обозреватель",
                             f"{rel}: стр. {line}, своя ссылка на {host}. Карта "
                             f"обозревателей уже расходилась в четырёх копиях: "
                             f"монета появлялась в проекте, а копию не правили, и "
                             f"клиент получал пустую кнопку или чужую сеть. "
                             f"Источник один — core.txid.explorer_url(); клиенту "
                             f"сервер отдаёт готовое поле tx_url.")


# ─────────────────────────────────────────────────────────────────────
# 16. Курсы для фронта берутся у витрины, а не перечисляются руками
# ─────────────────────────────────────────────────────────────────────
# /api/rates и витрина (services.offerings) — один экран для клиента: список
# монет приходит из витрины, а цена к ним — из этого словаря. Пока монеты
# дописывались в него руками, XRP открылся витриной и попал в выпадающий список
# Mini App, а курса к нему не было: строка «получите ≈ …» оставалась прочерком
# до самой оплаты. Нашли это ОБА гейта независимо — значит, дефект виден снаружи.
def check_rates_api_follows_the_showcase():
    """Тело /api/rates обязано перебирать витрину, а не список монет."""
    rel = "relay-fastapi/main.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "api_rates":
            continue
        body = "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])
        code = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
        if not re.search(r"for\s+\w+\s+in\s+_allowed_currencies\(\)", code):
            fail("курс для витрины",
                 f"{rel}: api_rates() (стр. {node.lineno}) не перебирает "
                 f"_allowed_currencies(). Значит монеты перечислены руками, и "
                 f"открытая витриной монета попадёт клиенту в список без цены: "
                 f"расчёт «сколько получу» останется пустым, а заявку сервер "
                 f"примет. Строить карту курсов из витрины.")
        return
    fail("курс для витрины", f"{rel}: функция api_rates не найдена — проверка ослепла")


# ─────────────────────────────────────────────────────────────────────
# 17. Отказ от тега — явный ответ, а не пустое поле
# ─────────────────────────────────────────────────────────────────────
# Бот спрашивает тег отдельным шагом, и «тега нет» там — нажатая кнопка. Сайт и
# Mini App принимали пустое поле как согласие: клиент, не понявший вопроса,
# оформлял перевод на биржевой адрес без тега — сеть такой перевод подтверждает,
# а биржа кладёт монеты на общий счёт и получателю не зачисляет. Разница между
# «тега нет» и «не ответил» должна доезжать до сервера, поэтому у резолвера есть
# отдельный признак, и каждая поверхность обязана его передавать.
def check_no_tag_is_explicit():
    """_resolve_destination принимает признак явного отказа, и его передают все."""
    rel = "relay-fastapi/main.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == "_resolve_destination":
            found = True
            names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            if "no_tag" not in names:
                fail("явный отказ от тега",
                     f"{rel}: у _resolve_destination нет параметра no_tag. Значит "
                     f"пустое поле тега снова считается согласием, и заявка на "
                     f"биржевой адрес уйдёт без тега — деньги попадут на общий "
                     f"счёт биржи.")
                return
    if not found:
        fail("явный отказ от тега", f"{rel}: _resolve_destination не найден — проверка ослепла")
        return
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_resolve_destination"]
    if not calls:
        fail("явный отказ от тега", f"{rel}: резолвер никто не зовёт — проверка ослепла")
    for c in calls:
        if not any(k.arg == "no_tag" for k in c.keywords):
            fail("явный отказ от тега",
                 f"{rel}: стр. {c.lineno}, вызов _resolve_destination без no_tag. "
                 f"Поверхность не отличает «тега нет» от «клиент не ответил» — "
                 f"по умолчанию будет принято молчание.")

    # Бот: то же правило, но точек ввода адреса тут несколько, и второстепенные
    # (подарок, лимитный ордер, DCA, своп) молчание клиента принимали за «тега
    # нет». Проверка ходит не по списку функций, а по ДЕКОРАТОРУ состояния:
    # список отстал бы от кода на следующем же потоке, а декоратор `.address`
    # и есть определение «сюда клиент присылает адрес».
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    if not bot:
        return
    try:
        btree = ast.parse(bot)
    except SyntaxError:
        return
    entries = []
    for fn in ast.walk(btree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not (isinstance(f, ast.Attribute) and f.attr == "message"):
                continue
            if any(isinstance(a, ast.Attribute) and a.attr == "address" for a in dec.args):
                entries.append(fn)
    if not entries:
        fail("явный отказ от тега",
             "bot/main_bot.py: обработчиков ввода адреса не найдено — проверка ослепла")
    for fn in entries:
        body = ast.dump(fn)
        asks_here = "_tag_answer_missing" in body
        # Основной поток спрашивает тег отдельным шагом — это тот же явный ответ.
        asks_step = "dest_tag" in body
        if not (asks_here or asks_step):
            fail("явный отказ от тега",
                 f"bot/main_bot.py: {fn.name}() принимает адрес, но про тег не "
                 f"спрашивает никак. У валюты с тегом молчание клиента станет "
                 f"«тега нет», и перевод на биржевой адрес не зачислится "
                 f"получателю — сеть его при этом подтвердит.")


# ─────────────────────────────────────────────────────────────────────
# 18. Меню продажи не предлагает монету, которую некуда принять
# ─────────────────────────────────────────────────────────────────────
# Клавиатура выбора монеты одна на покупку и продажу, а списки монет разные:
# купить можно то, чем мы владеем (резерв), продать — только то, для чего у нас
# есть адрес приёма. Монета, открытая резервом (XRP), появлялась в меню продажи
# и упиралась в «❌ Неверная валюта» — врало сообщение, а не клиент.
def check_sell_menu_offers_only_receivable_coins():
    rel = "bot/main_bot.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == "build_currency_kb":
            body = "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])
            code = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
            if "SELL_RECEIVE_ADDRESSES" not in code:
                fail("меню продажи",
                     f"{rel}: build_currency_kb() (стр. {node.lineno}) не отсеивает "
                     f"монеты без адреса приёма. Клавиатура общая на покупку и "
                     f"продажу: монета, открытая резервом, окажется в меню "
                     f"продажи и ответит «Неверная валюта» на верную валюту.")
            return
    fail("меню продажи", f"{rel}: build_currency_kb не найдена — проверка ослепла")


# ─────────────────────────────────────────────────────────────────────
# 19. Неразобранный ввод — не согласие на его отсутствие
# ─────────────────────────────────────────────────────────────────────
# _parse_tag_input по договору возвращает None и на «тега нет», и на «тег есть,
# но я его не понял» — различить их обязан вызывающий. Легаси-путь Mini App
# звал парсер прямо в аргументах _canonical_address: тег «abc» превращался в
# None, из адреса собиралась классическая (бестеговая) форма, заявка уходила.
# Сеть такой перевод подтвердит, а биржа зачислит его на общий счёт — деньги
# невозвратны, при том что клиент тег указал. Правило машинное: результат
# парсера обязан лечь в переменную и получить явный отказ по `is None`.
def check_unparsed_input_is_not_silence():
    rel = "bot/main_bot.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    PARSER = "_parse_tag_input"

    def _calls_to(node, name):
        return [n for n in ast.walk(node)
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == name]

    if not _calls_to(tree, PARSER):
        fail("неразобранный ввод",
             f"{rel}: {PARSER} никто не зовёт — проверка ослепла")
        return

    # Вызов внутри аргументов сборщика адреса — ровно та форма, где отказ
    # негде поставить: результат нигде не назван и проверить его нечем.
    for call in _calls_to(tree, "_canonical_address"):
        for arg in list(call.args) + [k.value for k in call.keywords]:
            if _calls_to(arg, PARSER):
                fail("неразобранный ввод",
                     f"{rel}: стр. {call.lineno}, {PARSER}() вызван прямо в "
                     f"аргументах _canonical_address. Неразобранный тег молча "
                     f"станет «тега нет», и адрес соберётся без него.")

    def _rejects_none(fn, name):
        """В функции есть if с `name is None`, из тела которого выходят."""
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            hits = [c for c in ast.walk(node.test)
                    if isinstance(c, ast.Compare)
                    and isinstance(c.left, ast.Name) and c.left.id == name
                    and any(isinstance(o, ast.Is) for o in c.ops)
                    and any(isinstance(v, ast.Constant) and v.value is None
                            for v in c.comparators)]
            if not hits:
                continue
            for stmt in node.body:
                if any(isinstance(x, ast.Return) for x in ast.walk(stmt)):
                    return True
        return False

    checked = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                    and getattr(node.value.func, "id", "") == PARSER:
                bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        for name in sorted(bound):
            checked += 1
            if not _rejects_none(fn, name):
                fail("неразобранный ввод",
                     f"{rel}: {fn.name}() (стр. {fn.lineno}) кладёт {PARSER}() "
                     f"в «{name}» и не отказывает при `{name} is None`. "
                     f"Непонятый тег уйдёт в заявку как отсутствие тега.")
    if not checked:
        fail("неразобранный ввод",
             f"{rel}: ни один результат {PARSER}() не назван — проверка ослепла")


# ─────────────────────────────────────────────────────────────────────
# 20. Обработчик, до которого не доходит ни маршрут, ни вызов
# ─────────────────────────────────────────────────────────────────────
# Команда объявляется дважды, живёт первая, вторая остаётся лежать под
# комментарием «отключён дубликат». Она выглядит рабочей: то же имя, тот же
# текст ответа — и правка ложится именно в неё. Так этап 0.1 «доставил»
# оператору тег в /order: код написан, тест зелёный, а живой обработчик
# по-прежнему печатал слитый X-адрес. Файл — единственный источник маршрутов
# бота, поэтому недостижимость проверяется механически.
def check_no_unreachable_handlers():
    rel = "bot/main_bot.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    handlers = [n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name.startswith("cmd_")]
    if not handlers:
        fail("недостижимый обработчик",
             f"{rel}: функций cmd_* нет — проверка ослепла")
        return
    for fn in handlers:
        routed = any("router." in ast.unparse(d) for d in fn.decorator_list)
        if routed or fn.name in called:
            continue
        fail("недостижимый обработчик",
             f"{rel}: {fn.name}() (стр. {fn.lineno}) не подключена к роутеру и "
             f"никем не вызывается. Правка в такой функции выглядит внесённой, "
             f"но живой обработчик работает по-старому.")


# ─────────────────────────────────────────────────────────────────────
# 21. Чёрный список адресов сравнивается по счёту, а не по строке
# ─────────────────────────────────────────────────────────────────────
# У счёта XRPL две равноправные формы записи (classic `r…` и X-адрес), и это
# один и тот же счёт. Строгое `address=?` значит, что бан обходится сменой
# формы: админ заблокировал classic, клиент оформил заявку X-адресом того же
# счёта — совпадения нет, крипта ушла. То же и наоборот. Правило: любой SQL по
# blocked_addresses идёт через нормализацию к идентичности счёта.
# ─────────────────────────────────────────────────────────────────────
# 28. Страж сравнивает СТРОКУ адреса, а обходится он сменой формы
# ─────────────────────────────────────────────────────────────────────
# Один счёт записывается по-разному, и сравнение строк этого не ловит. За один
# день класс выстрелил дважды: чёрный список пропускал заблокированный счёт
# XRPL в classic-форме, а `payout_circuit` считал повторы выплат по строке —
# один счёт с разными тегами давал разные строки, и лимит PAYOUT_ADDR_REPEAT_MAX
# не сработал бы НИ РАЗУ. Страж, который выглядит установленным и не срабатывает,
# хуже отсутствующего: на него рассчитывают.
# ─────────────────────────────────────────────────────────────────────
# 29. Витрина уехала вперёд, а текст остался
# ─────────────────────────────────────────────────────────────────────
# Перечисления «BTC · LTC · USDT» жили в тарифах бота, в «о сервисе», в описании
# продажи и в шапке таблицы тарифов на сайте. Новая монета добавлялась в витрину
# и НЕ добавлялась в тексты: кнопка предлагала XRP, а текст рядом сообщал, что мы
# продаём три монеты. Клиент верит тексту — тот выглядит официальнее кнопки.
#
# Правило намеренно УЗКОЕ. Первая версия запрещала любое перечисление тикеров и
# дала 41 срабатывание — на комментариях, на генераторе баннера, на историческом
# «комиссия BTC / LTC». Мина, которая кричит без причины, хуже отсутствующей:
# её начинают глушить целиком. Поэтому проверяются НАЗВАННЫЕ поверхности, где
# текст обещает клиенту ассортимент, — и от них требуется спросить витрину.
# ─────────────────────────────────────────────────────────────────────
# 30. Авто-выплата не смогла — и заявка осталась молчать
# ─────────────────────────────────────────────────────────────────────
# Витрину открывает резерв, а выдавать монету автоматика умеет не всегда: у XRP
# и TON авто-выплаты нет вовсе, у EVM она под отдельным гейтом. Это осознанный
# режим «принимаем, выдаём руками», и держится он ровно на одном: когда
# `process_payout` возвращает None, заявка обязана уйти РАБОТНИКУ. Уберут эту
# ветку — и деньги клиента останутся приняты без единого следа о том, что их
# кто-то должен выдать. Внешние ревью уже шесть раз читали этот режим как
# «направление невозможно выполнить»; правильный ответ — не спор, а машинная
# гарантия, что человеческий путь на месте.
def check_failed_autopayout_reaches_a_human():
    tag = "выплата без человека"
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    if not bot:
        fail(tag, "bot/main_bot.py не прочитан — проверка ослепла")
        return
    lines = bot.splitlines()
    calls = [i for i, l in enumerate(lines) if "process_payout_async(" in l
             and not l.lstrip().startswith("#") and "async def" not in l]
    if not calls:
        fail(tag, "не найден вызов движка выплаты — проверка ослепла")
        return
    # Первая версия правила искала любое упоминание notify_workers_paid в 25
    # строках после вызова — и была зелёной на сломанном коде: ветку «не смогла»
    # убирали, а упоминание оставалось в соседнем `except`. Проверять надо не
    # соседство, а именно тот блок, который исполняется при неудаче.
    def _human_call_in(block):
        code = "\n".join(l for l in block if not l.lstrip().startswith("#"))
        return any(c in code for c in ("notify_workers_paid(", "notify_admins(",
                                       ".answer(", "send_message("))

    def _indent(l):
        return len(l) - len(l.lstrip())

    def _block_after(start):
        """Тело блока, открытого строкой start: до первого возврата отступа."""
        base = _indent(lines[start])
        out = []
        for l in lines[start + 1:]:
            if not l.strip():
                out.append(l)
                continue
            if _indent(l) <= base:
                break
            out.append(l)
        return out

    for i in calls:
        m = re.match(r"\s*(\w+)\s*=\s*await\s+process_payout_async\(", lines[i])
        if not m:
            fail(tag, f"bot/main_bot.py: стр. {i + 1} — результат выплаты никуда "
                      f"не присваивается, значит неудачу вообще не проверяют")
            continue
        var = m.group(1)
        falsy = None
        for j in range(i + 1, min(i + 12, len(lines))):
            if re.match(rf"\s*if\s+not\s+{var}\s*:\s*$", lines[j]):
                falsy = _block_after(j)                 # охранная форма
                break
            if re.match(rf"\s*if\s+{var}\s*:\s*$", lines[j]):
                want = _indent(lines[j])
                for k in range(j + 1, len(lines)):
                    if lines[k].strip() and _indent(lines[k]) <= want:
                        if re.match(r"\s*else\s*:\s*$", lines[k]):
                            falsy = _block_after(k)
                        break
                break
        if falsy is None:
            fail(tag, f"bot/main_bot.py: стр. {i + 1} — у вызова авто-выплаты нет "
                      f"ветки на случай неудачи: заявка останется оплаченной и "
                      f"никем не замеченной, хотя деньги клиента уже у нас")
        elif not _human_call_in(falsy):
            fail(tag, f"bot/main_bot.py: стр. {i + 1} — ветка неудачи есть, но в "
                      f"ней никто не зовёт человека (ни работника, ни админа, ни "
                      f"ответа инициатору): сбой останется только в журнале")


# ─────────────────────────────────────────────────────────────────────
# 31. Общий список валют обслуживает разборщик одной монеты
# ─────────────────────────────────────────────────────────────────────
# `TAGGED_CURRENCIES` — список валют, у которых к адресу прилагается тег. Пока
# в нём была одна монета, все поверхности спокойно звали `parse_xrp_destination`
# напрямую: список общий, разборщик частный, но результат совпадал. Добавление
# TON превратило это в четыре тихих отказа сразу — канонизация заявки, тег в
# кабинете, панель выдачи работнику и вопрос «указывать ли тег»: адрес TON
# XRP-разборщику непонятен, и все четыре места сообщили бы «адрес не разобран»
# про совершенно исправный адрес.
#
# Дефект не в TON и не в XRP, а в форме: ветвление по валюте расползлось по
# поверхностям вместо того, чтобы жить рядом с самими разборщиками. Поэтому
# правило: вне `core/address.py` монето-специфичных разборщиков быть не должно —
# только диспетчеры `parse_destination` / `canonical_destination` / `is_valid_tag`.
def check_tagged_currencies_use_the_dispatcher():
    tag = "чужой разборщик тега"
    private = ("parse_xrp_destination", "canonical_xrp_destination",
               "is_valid_xrp_tag", "parse_ton_destination",
               "canonical_ton_destination")
    for rel in (os.path.join("relay", "core", "assets.py"),
                os.path.join("bot", "main_bot.py"),
                os.path.join("relay-fastapi", "main.py")):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            fail(tag, f"{rel} не прочитан — проверка ослепла")
            continue
        for n, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#") or '"""' in line:
                continue            # объяснение — не вызов
            for name in private:
                if name + "(" in line:
                    fail(tag, f"{rel}: стр. {n} — прямой вызов {name}(): "
                              f"валюты с тегом перечислены общим списком, а "
                              f"разбирает их правило одной монеты. Следующая "
                              f"монета получит «адрес не разобран» на исправном "
                              f"адресе. Нужен диспетчер core.address."
                              f"parse_destination / canonical_destination / "
                              f"is_valid_tag")
    # Диспетчер обязан знать КАЖДУЮ валюту из общего списка — иначе он молча
    # вернёт None, и отказ будет выглядеть как «клиент ввёл плохой адрес».
    disp = _read(os.path.join(ROOT, "relay", "core", "address.py"))
    assets = _read(os.path.join(ROOT, "relay", "core", "assets.py"))
    if disp and assets:
        body = _slice(disp, "def parse_destination(", "\ndef ")
        m = re.search(r"TAGGED_CURRENCIES\s*=\s*\{(.*?)\}", assets, re.S)
        for cur in re.findall(r'"([A-Z]{2,6})"\s*:', m.group(1) if m else ""):
            if f'"{cur}"' not in body:
                fail(tag, f"core/address.py: parse_destination не знает {cur}, "
                          f"хотя тот числится в TAGGED_CURRENCIES — заявка по "
                          f"этой монете не создастся, а причиной будет назван "
                          f"адрес клиента")


# ─────────────────────────────────────────────────────────────────────
# 32. Форма тега додумана, а не спрошена у реестра
# ─────────────────────────────────────────────────────────────────────
# Диспетчер разбора появился (мина 31), но ВИД значения остался додуманным по
# единственной валюте, какая была: тег числовой, а внутри адреса он отделён
# двоеточием. У TON и то и другое иначе — memo это произвольный текст, а
# двоеточие живёт в самом сыром адресе (`0:hex64`) как его часть. Отсюда
# четыре тихих отказа: `int(raw)` в боте и в кабинете превращал memo «order-42»
# в «тега нет» и собирал адрес без него (перевод на биржу уходит на общий
# счёт — деньги невозвратны); `rpartition(":")` в подарочном сценарии резал
# сырой TON-адрес пополам; прибитая в HTML цифровая клавиатура не давала
# набрать memo с телефона вовсе.
#
# Правило: вид тега и разделитель — свойства валюты, лежат в реестре рядом с
# самим списком, и каждая валюта из списка обязана иметь оба. Поверхности
# спрашивают реестр, а не догадываются.
def check_tag_shape_comes_from_the_registry():
    tag = "форма тега додумана"
    assets = _read(os.path.join(ROOT, "relay", "core", "assets.py"))
    if not assets:
        fail(tag, "relay/core/assets.py не прочитан — проверка ослепла")
        return

    def _keys(name):
        m = re.search(name + r"\s*=\s*\{(.*?)\}", assets, re.S)
        return set(re.findall(r'"([A-Z]{2,6})"\s*:', m.group(1) if m else ""))

    tagged = _keys("TAGGED_CURRENCIES")
    if not tagged:
        fail(tag, "relay/core/assets.py: не найден TAGGED_CURRENCIES — проверка ослепла")
        return
    for reg, what in (("TAG_KINDS", "вид значения"),
                      ("TAG_SEPARATORS", "разделитель внутри адреса")):
        missing = tagged - _keys(reg)
        if missing:
            fail(tag, f"relay/core/assets.py: у {', '.join(sorted(missing))} нет "
                      f"записи в {reg} ({what}), хотя валюта числится в "
                      f"TAGGED_CURRENCIES. Поверхности возьмут поведение "
                      f"предыдущей монеты: числовое поле там, где нужен текст, "
                      f"и чужой разделитель в разборе адреса")

    # Разбор ввода тега — тоже диспетчер: `int()` над сырым вводом означает,
    # что текстовый memo молча станет «тега нет».
    for rel in (os.path.join("bot", "main_bot.py"),
                os.path.join("relay-fastapi", "main.py")):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            fail(tag, f"{rel} не прочитан — проверка ослепла")
            continue
        if "parse_tag_input" not in src:
            fail(tag, f"{rel}: ввод тега не проходит через core.address."
                      f"parse_tag_input — значит, его форма где-то додумана")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            fail(tag, f"{rel}: не разбирается — проверка ослепла")
            continue

        def _mentions_tag(node):
            """Есть ли в поддереве имя/строка/ключ со словом «tag»."""
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and "tag" in sub.id.lower():
                    return True
                if isinstance(sub, ast.Attribute) and "tag" in sub.attr.lower():
                    return True
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and "tag" in sub.value.lower():
                    return True
            return False

        # Приведение тега к числу ищем по СМЫСЛУ выражения, а не по имени
        # переменной: список имён устарел бы на первом же переименовании и
        # мина позеленела бы на сломанном коде.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "int" and node.args):
                continue
            targets = []
            for parent in ast.walk(tree):
                if isinstance(parent, ast.Assign) and parent.value is node:
                    targets = parent.targets
            if _mentions_tag(node.args[0]) or any(_mentions_tag(t) for t in targets):
                fail(tag, f"{rel}: стр. {node.lineno} — ввод тега приводится к "
                          f"числу напрямую. У TON memo текстовый: он превратится "
                          f"в None, а None по договору читается как «тега нет», "
                          f"и адрес соберётся без memo. Разбор — "
                          f"core.address.parse_tag_input(raw, currency)")

        # Расщепление адреса по прибитому литералу-разделителю.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("partition", "rpartition", "split", "rsplit")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            recv = node.func.value
            name = getattr(recv, "id", "") or getattr(recv, "attr", "")
            if re.search(r"addr|dest", name, re.I):
                fail(tag, f"{rel}: стр. {node.lineno} — адрес расщепляется по "
                          f"прибитому {node.args[0].value!r}. Разделитель — "
                          f"свойство валюты (assets.tag_separator): сырой "
                          f"TON-адрес `0:hex64` сам содержит двоеточие и будет "
                          f"разрезан пополам")

    # Клавиатура и пример на обеих поверхностях — из витрины (tag_kind), а не
    # из разметки: прибитый в HTML numeric не даёт набрать memo с телефона.
    for rel in (os.path.join("relay", "webapp.html"),
                os.path.join("relay-fastapi", "templates", "dashboard_exchange.html")):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            fail(tag, f"{rel} не прочитан — проверка ослепла")
            continue
        m = re.search(r"<input[^>]*id=[\"']dest_tag[\"'][^>]*>", src, re.S)
        if not m:
            fail(tag, f"{rel}: не найдено поле dest_tag — проверка ослепла")
            continue
        if "inputmode" in m.group(0):
            fail(tag, f"{rel}: у поля dest_tag клавиатура прибита в разметке. "
                      f"Она одна на все валюты, а memo у TON текстовый — с "
                      f"цифровой панели его не набрать")
        if "tag_kind" not in src:
            fail(tag, f"{rel}: витринное tag_kind нигде не читается — вид поля "
                      f"тега додуман по одной валюте")


# ─────────────────────────────────────────────────────────────────────
# 33. Кошелёк написан, но админ его не видит
# ─────────────────────────────────────────────────────────────────────
# Реестр кошельков — единственное место, где владелец видит «сколько у нас
# есть» по каждой сети. Модуль, не вписанный в него, работает вхолостую: код
# есть, тесты зелёные, а на поверхности сети нет вовсе. Это ровно та болезнь,
# от которой сторожит мина 10 (валюта с кошельком обязана быть на витрине),
# только с другого конца — и она уже сбывалась: XRP пролежал так месяцами.
#
# Для TON цена особенно прямая: витрина монеты закрыта до `/setreserve TON N`,
# а резерв владелец задаёт по факту остатка. Не видно баланса — резерв ставится
# вслепую либо не ставится никогда, и вся работа по монете не доходит до денег.
def check_wallet_modules_are_registered():
    tag = "кошелёк вне реестра"
    wallet_dir = os.path.join(ROOT, "relay", "wallet")
    reg = _read(os.path.join(wallet_dir, "registry.py"))
    if not reg:
        fail(tag, "relay/wallet/registry.py не прочитан — проверка ослепла")
        return
    m = re.search(r"CHAINS\s*:[^=]*=\s*\[(.*?)\]", reg, re.S)
    if not m:
        fail(tag, "relay/wallet/registry.py: не найден список CHAINS — проверка ослепла")
        return
    listed = m.group(1)
    # Адаптер зовёт свой модуль внутри функции, а в CHAINS стоит имя функции —
    # поэтому ищем упоминание модуля в файле И его адаптер в самом списке.
    for fn in sorted(os.listdir(wallet_dir)):
        if not fn.endswith("_wallet.py"):
            continue
        mod = fn[:-3]
        if f"import {mod}" not in reg and f"{mod} import" not in reg:
            fail(tag, f"relay/wallet/{fn}: реестр кошельков про него не знает. "
                      f"Баланс этой сети не увидит никто, и решение «открывать "
                      f"ли монету клиентам» будет приниматься вслепую")
            continue
        chain = mod.replace("_wallet", "")
        if not re.search(r"_%s\b" % re.escape(chain), listed) \
                and f'"{chain.upper()}"' not in listed:
            fail(tag, f"relay/wallet/{fn}: адаптер написан, но в список CHAINS "
                      f"не добавлен — реестр его не обойдёт, поверхность пуста")
    # Общего контракта имён у модулей нет (у TRON `tron_status`, у XRP
    # `get_balance`) — реестр их адаптирует, и это нормально. Проверяем не
    # имена, а существование того, что адаптер РЕАЛЬНО зовёт: опечатка или
    # переименование в модуле иначе всплывёт только на живой админ-странице,
    # где сеть покажет «balance:AttributeError» вместо остатка.
    try:
        tree = ast.parse(reg)
    except SyntaxError:
        fail(tag, "relay/wallet/registry.py не разбирается — проверка ослепла")
        return
    wanted = {}                      # модуль → {имена, которые из него зовут}
    aliases = {}                     # локальное имя → модуль
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for al in node.names:
            if node.module == "wallet" and al.name.endswith("_wallet"):
                aliases[al.asname or al.name] = al.name
            elif (node.module or "").startswith("wallet."):
                wanted.setdefault(node.module.split(".", 1)[1], set()).add(al.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            wanted.setdefault(aliases[node.value.id], set()).add(node.attr)
    # Ненастроенная сеть обязана нести подсказку «чем это лечится»: пустая
    # строка в панели /wallet превращает решение владельца в умолчание.
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    hint = re.search(r"create_hint\s*=\s*\{(.*?)\n    \}", bot or "", re.S)
    if not hint:
        fail(tag, "bot/main_bot.py: не найдена карта create_hint — проверка ослепла")
    else:
        known = set(re.findall(r'"([A-Z]{2,6})"\s*:', hint.group(1)))
        for chain in re.findall(r'"chain":\s*"([A-Z]{2,6})"', reg) + \
                re.findall(r'_btc_like\("([A-Z]{2,6})"', reg):
            if chain not in known:
                fail(tag, f"bot/main_bot.py: в /wallet нет подсказки для {chain}. "
                          f"Ненастроенная сеть покажется как «не создан» с пустой "
                          f"строкой, и владелец не узнает, чем это включается")

    # «Выдадим сами» — обещание, которое даётся владельцу в момент /setreserve,
    # то есть ДО оплаты клиентом. Пока оно выводилось перечнем исключений
    # («всё, кроме XRP, умеем»), каждая новая монета получала его молча.
    # Решение обязано приходить из общей логики, где перечислены ВСЕ монеты.
    if bot:
        try:
            btree = ast.parse(bot)
        except SyntaxError:
            btree = None
        fn = next((n for n in ast.walk(btree or ast.Module(body=[], type_ignores=[]))
                   if isinstance(n, ast.FunctionDef) and n.name == "_hot_wallet_state"), None)
        if fn is None:
            fail(tag, "bot/main_bot.py: нет _hot_wallet_state — проверка ослепла")
        else:
            body = ast.get_source_segment(bot, fn) or ""
            if "payout_contour" not in body:
                fail(tag, "bot/main_bot.py: _hot_wallet_state решает сама, не "
                          "спрашивая payout_contour. Монета, которой движок не "
                          "умеет, получит «выдадим сами», и узнается это после "
                          "оплаты клиентом")
            for node in ast.walk(fn):
                # `if cur != "XXX": return True` — ровно та форма умолчания
                if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                        and any(isinstance(o, (ast.NotEq, ast.NotIn)) for o in node.test.ops)):
                    continue
                for stmt in node.body:
                    if isinstance(stmt, ast.Return) and "True" in (
                            ast.get_source_segment(bot, stmt) or ""):
                        fail(tag, f"bot/main_bot.py: стр. {node.lineno} — "
                                  f"готовность выдать выводится из «валюта не "
                                  f"такая-то». Это умолчание: следующая монета "
                                  f"получит обещание автоматической выдачи молча")

    for mod, names in sorted(wanted.items()):
        src = _read(os.path.join(wallet_dir, mod + ".py"))
        if not src:
            fail(tag, f"registry.py импортирует wallet.{mod}, которого нет")
            continue
        for name in sorted(names):
            if not re.search(r"^def %s\s*\(" % re.escape(name), src, re.M):
                fail(tag, f"relay/wallet/registry.py зовёт {mod}.{name}(), "
                          f"которой в модуле нет. Реестр покажет по этой сети "
                          f"ошибку вместо остатка, и увидит её только владелец "
                          f"на живой странице")


def check_coin_lists_come_from_the_shopfront():
    tag = "текст отстал от витрины"
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    if not bot:
        fail(tag, "bot/main_bot.py не прочитан — проверка ослепла")
        return
    if "def coins_line(" not in bot:
        fail(tag, "bot/main_bot.py: нет coins_line() — списка монет из витрины; "
                  "тексты снова начнут перечислять ассортимент руками")
    for fn, human in (("def build_welcome_caption(", "тарифы в приветствии"),
                      ("async def menu_about(", "«о сервисе»"),
                      ("async def menu_reviews(", "экран отзывов/условий")):
        body = _nodoc(_slice(bot, fn, "\nasync def ", "\ndef "))
        if not body:
            fail(tag, f"bot/main_bot.py: не найдена {fn} — проверка ослепла")
            continue
        if not re.search(r"(?:BTC|LTC|USDT|ETH|XRP)\s*(?:·|,|/)\s*(?:BTC|LTC|USDT|ETH|XRP)",
                         body):
            continue          # ассортимент здесь не перечисляется — и хорошо
        if "coins_line" not in body:
            fail(tag, f"bot/main_bot.py: «{human}» перечисляет монеты руками "
                      f"вместо coins_line() — витрина уедет вперёд, текст "
                      f"останется, и клиент прочитает, что монету мы не продаём, "
                      f"рядом с кнопкой, которая её предлагает")

    for rel, human in ((os.path.join("relay-fastapi", "templates", "rates.html"),
                        "таблица тарифов на сайте"),
                       (os.path.join("relay-fastapi", "templates", "dashboard_sell.html"),
                        "описание продажи в кабинете")):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            continue
        body = re.sub(r"\{#.*?#\}", "", src, flags=re.S)
        if not re.search(r"(?:BTC|LTC|USDT|ETH|XRP)\s*(?:·|,|/)\s*(?:BTC|LTC|USDT|ETH|XRP)",
                         body):
            continue
        if "offered_currencies" not in body:
            fail(tag, f"{rel}: «{human}» перечисляет монеты руками вместо "
                      f"offered_currencies из общего контекста — список отстанет "
                      f"от витрины при первой же новой монете")


def check_guards_compare_accounts_not_strings():
    tag = "страж сравнивает строку"
    relay = os.path.join(ROOT, "relay")
    if relay not in sys.path:
        sys.path.insert(0, relay)
    try:
        from core.address import account_key
    except Exception as e:
        fail(tag, f"нет core.address.account_key — общей нормализации счёта: "
                  f"{type(e).__name__}: {e}")
        return

    # Свойство: разные записи одного счёта дают ОДИН ключ.
    try:
        from xrpl.core import addresscodec as _ac
        classic = "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe"
        keys = {account_key(classic),
                account_key(_ac.classic_address_to_xaddress(classic, 1, False)),
                account_key(_ac.classic_address_to_xaddress(classic, 99999, False))}
        if len(keys) != 1:
            fail(tag, f"account_key даёт разные ключи для одного счёта XRPL: {keys} "
                      f"— значит и блокировка, и лимит повторов обходятся сменой тега")
    except ImportError:
        pass          # xrpl есть только в bot/venv; правило ниже всё равно работает
    evm = "0xAbC0000000000000000000000000000000000001"
    if account_key(evm) != account_key(evm.lower()):
        fail(tag, "account_key различает регистр EVM-адреса — один счёт считается "
                  "двумя, и лимит повторов выплат не сработает")

    # Стражи обязаны спрашивать общий источник, а не сравнивать строки сами.
    for rel, fn, human in (
        ("relay/services/payout_circuit.py", "def _addr_payouts_24h(",
         "лимит повторных выплат на адрес"),
    ):
        src = _read(os.path.join(ROOT, rel))
        body = _nodoc(_slice(src, fn, "\ndef "))
        if not body:
            fail(tag, f"{rel}: не найдена {fn} — проверка ослепла")
            continue
        if "account_key" not in body:
            fail(tag, f"{rel}: «{human}» не приводит адрес к счёту "
                      f"(core.address.account_key) — один счёт в разных формах "
                      f"считается разными, и страж не срабатывает никогда")
        if re.search(r"crypto_address\s*=\s*\?", body):
            fail(tag, f"{rel}: «{human}» отбирает по РАВЕНСТВУ строки адреса в SQL. "
                      f"Так нормализовать хранимое нельзя: у XRPL один счёт с "
                      f"разными тегами — разные строки, у EVM — разный регистр")


def check_blocklist_matches_account_not_string():
    rel = "bot/main_bot.py"
    src = _read(os.path.join(ROOT, rel))
    if not src:
        return
    lines = src.splitlines()
    norm = ("_blocklist_forms", "_blocklist_key")
    hits = 0
    for i, ln in enumerate(lines, 1):
        if "blocked_addresses" not in ln or ln.lstrip().startswith("#"):
            continue
        # Интересуют только запросы, которые СОПОСТАВЛЯЮТ адрес: выборка списка
        # для показа админу ничего не сравнивает и нормализовать в ней нечего.
        stmt = "\n".join(lines[i - 1:i + 3])
        if not re.search(r"WHERE\s+address|INSERT[^(]*\(\s*address", stmt, re.I):
            continue
        hits += 1
        # Нормализация стоит рядом с запросом: либо в самой строке, либо в
        # подготовке параметров выше (окно — тело того же блока with/try).
        window = "\n".join(lines[max(0, i - 8):i + 2])
        window = "\n".join(re.sub(r"#.*$", "", w) for w in window.splitlines())
        # Отбор по адресу в самом SQL опасен ОСОБО: приводить к счёту можно
        # только присланное, а в таблице могла лежать X-форма — тот же счёт в
        # classic-виде под неё не подпадёт, и блокировка обойдётся сменой формы
        # записи. Вывести все X-адреса из classic нельзя (по одному на каждый
        # тег). Значит сравнивать надо в Python, нормализуя И хранимое.
        if re.search(r"WHERE\s+address\s+IN|WHERE\s+address\s*=", stmt, re.I) \
                and "SELECT" in stmt.upper() and "INSERT" not in stmt.upper() \
                and "DELETE" not in stmt.upper():
            fail("чёрный список",
                 f"{rel}: стр. {i}, совпадение ищется SQL-запросом по строке "
                 f"адреса. Хранимую запись так не нормализовать: лежит X-форма — "
                 f"тот же счёт в classic-виде её не найдёт, и блокировка "
                 f"обходится сменой формы. Читать список и сравнивать ключи "
                 f"счетов в Python.")
        if not any(n in window for n in norm):
            fail("чёрный список",
                 f"{rel}: стр. {i}, запрос к blocked_addresses без приведения "
                 f"адреса к идентичности счёта ({' / '.join(norm)}). У XRPL две "
                 f"формы записи одного счёта — блокировка обходится сменой формы.")
    if not hits:
        fail("чёрный список",
             f"{rel}: обращений к blocked_addresses нет — проверка ослепла")


# ─────────────────────────────────────────────────────────────────────
# 22. Клиенту говорят «истекло» по заявке, за которую он уже заплатил
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: клиент присылает чек, Слой 0 держит заявку живой (и правильно
# делает — cleanup_expired_orders не истекает заявки с чеком), а каждая клиентская
# поверхность продолжает судить об исходе по 15-минутному таймеру: «время истекло,
# средства не переводите» и кнопка «Оплатить» рядом. Клиент читает это как отказ
# и платит второй раз за тот же обмен. В логах при этом ни одной ошибки —
# страница отработала ровно так, как написана.
# Правило: там, где поверхность объявляет исход или зовёт платить, признак чека
# должен быть СПРОШЕН и спрошен РАНЬШЕ срока.
def _nocomment_js(s):
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in s.splitlines())


def _nodoc(body: str) -> str:
    """Срезает docstring функции. Правило, которому хватает описания рядом с
    кодом, проверяет описание, а не код: ровно так три проверки этого набора
    зеленели на заведомо сломанных мутациях."""
    m = re.match(r"\s*(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n\s*(\"\"\"|\'\'\')",
                 body)
    if not m:
        return body
    q = m.group(1)
    end = body.find(q, m.end())
    return body if end == -1 else body[:m.start(1)] + body[end + 3:]


def _slice(src, start, *ends):
    i = src.find(start)
    if i < 0:
        return ""
    j = len(src)
    for e in ends:
        k = src.find(e, i + len(start))
        if 0 <= k < j:
            j = k
    return src[i:j]


# ─────────────────────────────────────────────────────────────────────
# 23. Колонку читают там, где её никто не создаёт
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: `orders.receipt_sent_at` пишет core/receipts.py и читают
# клиентские списки заявок, но ни init_db() бота, ни миграция relay-fastapi её
# не добавляли — в боевой базе она появилась руками. На свежей базе первый же
# SELECT истории падал бы на «no such column», унося ВЕСЬ список заявок клиента.
# Два процесса делят один файл БД и стартуют в любом порядке, поэтому набор
# колонок у них обязан быть один: тот, кто стартовал первым, и есть миграция.
# ─────────────────────────────────────────────────────────────────────
# 24. Деньги приняты, обещанное не выдано — и об этом молчат обе стороны
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: оплаченные заявки без выдачи копились до 99 часов. Видели их
# три места по-своему (`/pending` — только paid, `/review` — только чеки, сторож
# — третьим запросом), и ни одно не показывало ВОЗРАСТ: сорок строк выглядят
# одинаково, человек берёт верхнюю. Клиенту же после «Оплата подтверждена!
# Отправляем…» не говорили вообще ничего — он либо шёл в поддержку, либо считал,
# что его обманули. Правило: очередь у всех одна, в ней виден возраст, и порог
# «пора беспокоиться» у персонала и у клиента — один и тот же.
# ─────────────────────────────────────────────────────────────────────
# 25. Идентификатор попытки строят в одном месте, а читают в другом
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: провайдерам слался `obsidian_{order_id}` — идентификатор
# ЗАЯВКИ. Заявка одна, попыток по ней несколько (ретрай, эскалация, повторный
# заход), и Montera на второй отвечала 422 «внешний id уже существует»: вместо
# попытки получался минус одна попытка. Опаснее другое: разбор вебхука жил
# КОПИЯМИ в семи местах и брал «всё после первого подчёркивания». Сделать
# идентификатор уникальным и не поправить разбор — значит принять оплату и не
# узнать её: деньги пришли, заявка осталась pending. Поэтому построение и
# разбор обязаны быть одним модулем.
# ─────────────────────────────────────────────────────────────────────
# 26. Провайдер сказал «сделка умерла» — и это услышал только журнал
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: `vertu_poll_task` на Declined/Revoked писала
# `payment_sessions.status='failed'`, строку в аудит — и всё. Заявка оставалась
# `pending` навсегда, клиент смотрел на реквизиты, ведущие в никуда, персонал не
# знал, что разбирать. Так висели 22 заявки на 99 400 ₽. Отдельная половина:
# трейдер мог просить видео, но у Vertu канала для этого НЕТ — просьба уходит в
# чат диспута, которого никто не читает. Кодом канал не создать; честно только
# одно — не притворяться, что он есть, и звать человека.
# ─────────────────────────────────────────────────────────────────────
# 27. Монету продаём, а выплату по ней сверка не видит
# ─────────────────────────────────────────────────────────────────────
# Было 30.07.2026: `payout_discovery` умел BTC, LTC и USDT-TRC20. Для XRP
# авто-выплаты нет вовсе (`process_payout` его не знает, `/payout` отвечает
# «отправлять вручную») — то есть ручная выдача там ЕДИНСТВЕННЫЙ путь, а
# механизм, который ловит ручные выдачи, про эту монету не знал ничего. Заявка
# оставалась `paid` навсегда с нулевым шансом закрыться: клиент без TXID,
# реф-бонус и VIP-объём не начислены, сторож считает её зависшей вечно.
# Правило: если монету можно купить, её выплату обязано быть видно.
def check_every_currency_is_reconcilable():
    tag = "сверка не видит монету"
    import importlib.util
    relay = os.path.join(ROOT, "relay")
    if relay not in sys.path:
        sys.path.insert(0, relay)
    try:
        spec = importlib.util.spec_from_file_location(
            "_pd_mine", os.path.join(relay, "core", "payout_discovery.py"))
        pd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pd)
        from core import assets as _assets
    except Exception as e:
        fail(tag, f"не удалось загрузить сверку/реестр валют: {type(e).__name__}: {e}")
        return

    known = sorted(_assets.CURRENCY_NETWORKS)
    if not known:
        fail(tag, "реестр валют пуст — проверка ослепла")
        return

    # Подменяем читателей цепи: важно не «что вернулось», а ушёл ли запрос
    # вообще хоть куда-то. Валюта, для которой сверка молча отдаёт [], выглядит
    # работающей и не находит НИ ОДНОЙ выплаты.
    seen = []
    # Список читателей собираем из самого модуля: перечисленный руками, он
    # отставал бы от кода — новая цепь появлялась, в списке её не было, и
    # проверка «сходили ли мы хоть куда-то» видела настоящий сетевой вызов
    # вместо шпиона. Ровно так и вышло при добавлении TON.
    readers = [n for n in dir(pd) if n.startswith("_incoming_") and callable(getattr(pd, n))]
    if not readers:
        fail(tag, "в сверке не найдено ни одного читателя цепи — проверка ослепла")
        return
    for name in readers:
        setattr(pd, name, (lambda n: (lambda *a, **k: seen.append(n) or []))(name))
    for cur in known:
        seen.clear()
        try:
            pd.incoming_transfers(cur, "адрес-клиента")
        except Exception as e:
            fail(tag, f"{cur}: сверка падает на чтении цепи: {type(e).__name__}: {e}")
            continue
        if not seen:
            fail(tag, f"{cur}: продаём, но выплату по ней сверка не читает ни из "
                      f"одной цепи — выдача «мимо бота» останется невидимой "
                      f"навсегда, а заявка «paid» вечной")

    # Свой кошелёк тоже должен быть известен: без него ни одна выплата не
    # опознаётся как НАША, и авто-закрытие не сработает ни разу.
    src = _read(os.path.join(relay, "core", "payout_discovery.py"))

    # Валюта с НЕСКОЛЬКИМИ сетями обязана получать сеть заявки. У USDT их две,
    # и монета в них разная по природе: TRC-20 живёт в TRON, ERC-20 — токен в
    # Ethereum. Без сети половина выплат ищется не в той цепи и не находится
    # никогда, а выглядит это как «переводов нет».
    import inspect
    multi = [c for c, nets in _assets.CURRENCY_NETWORKS.items() if len(nets) > 1]
    if multi:
        try:
            sig = inspect.signature(pd.incoming_transfers)
        except (TypeError, ValueError):
            sig = None
        if sig is not None and "network" not in sig.parameters:
            fail(tag, f"incoming_transfers не принимает сеть, а у {', '.join(multi)} "
                      f"их несколько — выплата в неканонической сети невидима навсегда")
        body = _nodoc(_slice(src, "def incoming_transfers(", "\ndef "))
        for c in multi:
            if f'"{c}"' in body and "network" not in body:
                fail(tag, f"{c}: у валюты несколько сетей, а маршрутизация сверки "
                          f"их не различает")

    own = _slice(src, "def _own_wallet_addresses(", "\ndef ")
    for cur in known:
        if f'"{cur}"' not in own and cur not in ("BTC", "LTC"):
            fail(tag, f"{cur}: _own_wallet_addresses не знает адреса нашего "
                      f"кошелька — своя же выплата будет выглядеть чужой и "
                      f"заявка не закроется автоматически никогда")


def check_dead_deal_is_not_silent():
    tag = "смерть сделки"
    main = _read(os.path.join(ROOT, "relay-fastapi", "main.py"))
    caps = _read(os.path.join(ROOT, "relay", "core", "provider_caps.py"))
    if not main:
        fail(tag, "relay-fastapi/main.py не прочитан — проверка ослепла")
        return
    if not caps:
        fail(tag, "нет relay/core/provider_caps.py — возможности провайдера "
                  "снова угадываются на месте, и персонал будет ждать сигнала, "
                  "которого не бывает")

    body = _nodoc(_slice(main, "def handle_dead_session(", "\nasync def ", "\ndef "))
    if not body:
        fail(tag, "relay-fastapi/main.py: нет handle_dead_session — смерть сделки "
                  "у провайдера снова видна только в журнале")
    else:
        for need, why in (
            ("notify_telegram", "клиенту не говорят ничего, а он смотрит на "
                                "реквизиты, по которым уже не примут"),
            ("notify_admins_tg", "персоналу не говорят ничего, разбирать некому"),
            ("sent_notifications", "уведомление не одноразовое — опрос ходит раз "
                                   "в 30 секунд и завалит клиента дублями"),
            # Не «упоминается provider_caps» — импорта мало, нужен ВЫЗОВ:
            # ровно так это правило и проскочило первую проверку мутациями.
            ("verification_note(", "персоналу не сказано, ждать ли от этого "
                                   "провайдера запроса доп. проверки — а у "
                                   "половины его нет вовсе"),
        ):
            if need not in body:
                fail(tag, f"handle_dead_session: {why} (нет {need})")
        # Статус заявки трогать нельзя: «сделка не состоялась» у провайдера НЕ
        # доказывает, что клиент не платил.
        if re.search(r"UPDATE\s+orders\s+SET\s+status=", body):
            fail(tag, "handle_dead_session меняет статус заявки — человеку, чьи "
                      "деньги уже у трейдера, будет сказано «оплаты не было»")

    # Ветка «сделка умерла» в опросе обязана звать общий обработчик, а не
    # обновлять сессию своими руками и расходиться с ним.
    poll = _slice(main, "async def vertu_poll_task(", "\nasync def ", "\ndef ")
    if not poll:
        fail(tag, "relay-fastapi/main.py: не найдена vertu_poll_task — проверка ослепла")
    elif "handle_dead_session" not in poll:
        fail(tag, "vertu_poll_task: ветка неуспеха не зовёт handle_dead_session — "
                  "смерть сделки снова останется между строкой в журнале и "
                  "полем в payment_sessions")

    # Клиентские поверхности должны знать, что реквизиты мертвы.
    if "def _session_dead(" not in main:
        fail(tag, "relay-fastapi/main.py: нет _session_dead — /pay и Mini App "
                  "продолжат показывать реквизиты закрытой сделки")
    if '"dead"' not in main:
        fail(tag, "relay-fastapi/main.py: признак мёртвой сессии не отдаётся "
                  "клиентским страницам")
    if "C.dead" not in _slice(main, "function render()", "\nfunction startTimer"):
        fail(tag, "relay-fastapi/main.py: render() страницы /pay не смотрит на "
                  "мёртвую сессию — клиент увидит живой таймер над реквизитами, "
                  "по которым платёж уже не примут")
    wa = _read(os.path.join(ROOT, "relay", "webapp.html"))
    if wa and not re.search(r"\bdead\b", _nocomment_js(wa)):
        fail(tag, "relay/webapp.html: Mini App не знает о мёртвой сессии и "
                  "оставляет реквизиты на экране")


def check_attempt_id_is_symmetric():
    tag = "идентификатор попытки"
    root_rel = os.path.join(ROOT, "relay", "core", "attempt_id.py")
    if not _read(root_rel):
        fail(tag, "нет relay/core/attempt_id.py — построение и разбор снова "
                  "разъедутся по файлам, и первый же суффикс потеряет платёж")
        return

    # Свойство, а не текст: что построили — то и обязаны прочитать.
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_aid", root_rel)
        aid = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aid)
        for oid in ("1", "1234", "99955118"):
            back = aid.parse(aid.make(oid))
            if back != oid:
                fail(tag, f"attempt_id: построили попытку по заявке {oid}, "
                          f"разобрали {back!r} — вебхук пойдёт искать не ту заявку")
        if aid.make("7") == aid.make("7"):
            fail(tag, "attempt_id.make даёт одинаковый результат на повторе — "
                      "ровно та коллизия, из-за которой ретрай сгорал на 422")
        if aid.parse("obsidian_1234") != "1234":
            fail(tag, "attempt_id.parse не понимает старую форму без суффикса — "
                      "вебхуки по уже созданным у провайдера сделкам потеряются")
    except Exception as e:
        fail(tag, f"attempt_id не проверяется свойством: {type(e).__name__}: {e}")

    # Ни одной своей копии — ни построения, ни разбора.
    build = re.compile(r"obsidian_\{order_id\}")
    parse = re.compile(r"split\('_', ?1\)\[1\]|replace\('obsidian_'")
    targets = [os.path.join("relay-fastapi", "main.py"), os.path.join("bot", "main_bot.py")]
    pdir = os.path.join(ROOT, "relay", "providers")
    if os.path.isdir(pdir):
        targets += [os.path.join("relay", "providers", f)
                    for f in sorted(os.listdir(pdir)) if f.endswith(".py")]
    for rel in targets:
        src = _read(os.path.join(ROOT, rel))
        if not src:
            continue
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        if build.search(code):
            fail(tag, f"{rel}: идентификатор попытки строится из номера заявки "
                      f"(obsidian_{{order_id}}) — повтор по той же заявке уходит "
                      f"провайдеру как дубль и сгорает")
        if parse.search(code):
            fail(tag, f"{rel}: свой разбор идентификатора вместо attempt_id.parse. "
                      f"Он берёт «всё после первого подчёркивания» и о суффикс "
                      f"уникальности ломается молча — оплата придёт в никуда")


def check_debt_queue_is_visible():
    tag = "очередь долгов"
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    main = _read(os.path.join(ROOT, "relay-fastapi", "main.py"))
    wa = _read(os.path.join(ROOT, "relay", "webapp.html"))
    tpl = _read(os.path.join(ROOT, "relay-fastapi", "templates", "dashboard_orders.html"))
    if not (bot and main and wa and tpl):
        fail(tag, "не прочитан один из файлов поверхностей — проверка ослепла")
        return
    if not _read(os.path.join(ROOT, "relay", "core", "payout_queue.py")):
        fail(tag, "нет relay/core/payout_queue.py — единого источника очереди "
                  "разбора; каждая поверхность снова считает долг по-своему")
        return

    # 1. Обе поверхности персонала берут очередь из общего модуля и показывают
    #    ВОЗРАСТ. Свой запрос по status='paid' здесь — это вторая правда,
    #    которая разойдётся с первой ровно тогда, когда это будет дорого.
    for fn, human in (("async def cmd_review_queue(", "/review"),
                      ("async def cmd_pending(", "/pending")):
        b = _slice(bot, fn, "\nasync def ", "\ndef ", "\n@router.")
        b = "\n".join(re.sub(r"#.*$", "", ln) for ln in b.splitlines())
        if not b:
            fail(tag, f"bot/main_bot.py: не найдена {human} — проверка ослепла")
            continue
        if not re.search(r"\.queue\s*\(", b):
            fail(tag, f"bot/main_bot.py: {human} не ВЫЗЫВАЕТ payout_queue.queue() — "
                      f"импорта мало: список берётся откуда-то ещё, и две правды "
                      f"об одном долге разойдутся ровно тогда, когда это дорого")
        if "age_human" not in b:
            fail(tag, f"bot/main_bot.py: {human} не показывает возраст заявки. "
                      f"Без него сорок строк очереди выглядят одинаково, и "
                      f"человек берёт верхнюю, а не ту, что ждёт вторые сутки")
        if re.search(r"status\s*=\s*'paid'", b):
            fail(tag, f"bot/main_bot.py: {human} снова отбирает заявки своим "
                      f"условием status='paid' вместо общей очереди")

    # 1б. Решённое человеком не возвращается в очередь. Оператор посмотрел чек
    #     и отказал — долга больше нет; если такая заявка остаётся в /review и
    #     продолжает поднимать тревогу, работа оператора снова порождает шум,
    #     от которого её и лечили. Статуса для различения мало: `cancelled`
    #     ставит и сам клиент, и тогда решения по его деньгам как раз НЕ было.
    pq = _read(os.path.join(ROOT, "relay", "core", "payout_queue.py"))
    cw = _read(os.path.join(ROOT, "relay", "core", "conversion_watch.py"))
    for src, rel in ((pq, "relay/core/payout_queue.py"),
                     (cw, "relay/core/conversion_watch.py")):
        if src and "receipt_rejected" not in src:
            fail(tag, f"{rel}: отклонённая оператором заявка не отличается от "
                      f"нерешённой — она останется в очереди навсегда и будет "
                      f"звать человека посмотреть на его же решение")
    bot_src = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    rej = _slice(bot_src, "async def cb_review_reject(", "\nasync def ", "\ndef ", "\n@router.")
    if rej and "receipt_rejected" not in rej:
        fail(tag, "bot/main_bot.py: кнопка «Отклонить» не оставляет следа решения "
                  "— очередь не узнает, что по заявке уже решили")

    # 2. Клиенту говорят. Одноразово, и по ТОМУ ЖЕ порогу, что видит оператор.
    b = _nodoc(_slice(bot, "async def payout_delay_notice_task(", "\nasync def ", "\ndef "))
    if not b:
        fail(tag, "bot/main_bot.py: нет payout_delay_notice_task — клиент, чьи "
                  "деньги у нас, снова узнаёт о задержке только из тишины")
    else:
        if "payout_queue" not in b:
            fail(tag, "bot/main_bot.py: уведомление о задержке считает порог само, "
                      "мимо payout_queue — клиенту скажут «всё по плану» тогда, "
                      "когда у оператора строка уже красная")
        if "payout_delayed" not in b or "sent_notifications" not in b:
            fail(tag, "bot/main_bot.py: уведомление о задержке не одноразовое "
                      "(нет метки в sent_notifications) — клиент получит одно и "
                      "то же извинение каждые десять минут")
    if "payout_delay_notice_task()" not in bot.split("async def payout_delay_notice_task")[0] \
            and "create_task(payout_delay_notice_task())" not in bot:
        fail(tag, "bot/main_bot.py: payout_delay_notice_task определена, но не "
                  "запущена через create_task — код, который выглядит работающим "
                  "и не работает")

    # 3. Признак задержки доезжает до КАЖДОЙ клиентской поверхности. Молчащая
    #    поверхность здесь — это «Оплачена» и тишина на вторые сутки.
    if "def _payout_delayed(" not in main:
        fail(tag, "relay-fastapi/main.py: нет _payout_delayed() — сайт и Mini App "
                  "не отличат «выплачиваем» от «застряло на сутки»")
    elif not re.search(r"client_state\s*\(",
                       _nodoc(_slice(main, "def _payout_delayed(", "\ndef ", "\n@app."))):
        # Не «упоминается payout_queue» — упоминается он и в строке лога рядом,
        # а ВЫЗЫВАЕТСЯ ли. Порог, посчитанный здесь заново, — вторая правда:
        # клиенту «всё по плану» ровно тогда, когда у оператора строка красная.
        fail(tag, "relay-fastapi/main.py: _payout_delayed не вызывает "
                  "payout_queue.client_state() — порог считается сам, и у "
                  "клиента с оператором будет разная правда о заявке")
    for name, start in (("get_user_orders (кабинет)", "def get_user_orders("),
                        ("/api/history (Mini App)", "async def api_history(")):
        b = _slice(main, start, "\n@app.", "\ndef ", "\nasync def ")
        if b and not re.search(r'["\']delayed["\']', _nodoc(b)):
            fail(tag, f"relay-fastapi/main.py: {name} не отдаёт признак задержки — "
                      f"в списке заявок зависшая выплата выглядит как обычная "
                      f"«Оплачена»")
    for src, rel, human in ((wa, "relay/webapp.html", "Mini App"),
                            (tpl, "relay-fastapi/templates/dashboard_orders.html", "кабинет")):
        clean = re.sub(r"\{#.*?#\}", "", src, flags=re.S)
        clean = "\n".join(re.sub(r"//.*$", "", ln) for ln in clean.splitlines())
        if not re.search(r"\bdelayed\b", clean):
            fail(tag, f"{rel}: {human} не смотрит на признак задержки — клиент "
                      f"видит «Оплачена» и не знает, что заявка стоит")
    if "C.delayed" not in _slice(main, "function viewPaid()", "\nfunction "):
        fail(tag, "relay-fastapi/main.py: страница /pay обещает «обычно 5–15 "
                  "минут» и на застрявшей заявке — это обещание, которого мы не "
                  "держим, а клиент по нему считает время")


def check_migrations_agree():
    tag = "миграции разъехались"
    bot = _read(os.path.join(ROOT, "bot", "main_bot.py"))
    main = _read(os.path.join(ROOT, "relay-fastapi", "main.py"))
    if not bot or not main:
        fail(tag, "не прочитан bot/main_bot.py или relay-fastapi/main.py")
        return
    bot_cols = set(re.findall(r"ALTER TABLE orders ADD COLUMN (\w+)", bot))
    m = re.search(r"needed = \{(.*?)\n    \}", main, re.S)
    if not m:
        fail(tag, "relay-fastapi/main.py: не найден список миграций orders — "
                  "проверка ослепла")
        return
    web_cols = set(re.findall(r'["\'](\w+)["\']\s*:', m.group(1)))
    if not bot_cols:
        fail(tag, "bot/main_bot.py: не найдено ни одной миграции orders — "
                  "проверка ослепла")
        return
    # Та же беда, но с ТАБЛИЦАМИ. `sent_notifications` — журнал, на котором
    # держится вся идемпотентность уведомлений и защита от двойной выплаты, —
    # не создавался НИГДЕ: в боевую базу попал руками. На свежей базе первый же
    # INSERT валился, унося вместе с уведомлением и защиту от повтора.
    shared = ("sent_notifications", "order_receipts")
    for t in shared:
        for src, rel, other in ((bot, "bot/main_bot.py", "relay-fastapi"),
                                (main, "relay-fastapi/main.py", "бот")):
            uses = re.search(rf"(FROM|INTO|UPDATE)\s+{t}\b", src)
            creates = re.search(rf"CREATE TABLE IF NOT EXISTS\s+{t}\b", src)
            if uses and not creates:
                fail(tag, f"{rel}: работает с таблицей {t}, но не создаёт её. "
                          f"Процессы стартуют в любом порядке: если этот окажется "
                          f"первым, запрос упадёт — а вместе с ним пропадёт то, "
                          f"ради чего таблица нужна ({other} её создаёт или нет — "
                          f"полагаться на это нельзя)")

    for name, cols, other in (("bot/main_bot.py", bot_cols - web_cols, "relay-fastapi"),
                              ("relay-fastapi/main.py", web_cols - bot_cols, "бот")):
        if cols:
            fail(tag, f"{name}: колонки {sorted(cols)} мигрирует только он, а "
                      f"{other} — нет. Оба процесса делят один файл БД и "
                      f"стартуют в любом порядке: чей старт был первым, тот и "
                      f"определил схему, и читающий упадёт на «no such column»")


def check_receipt_beats_the_timer():
    tag = "чек против таймера"
    files = {}
    for rel in ("relay-fastapi/main.py", "relay/webapp.html",
                "relay-fastapi/templates/dashboard_orders.html", "bot/main_bot.py"):
        files[rel] = _read(os.path.join(ROOT, rel))
        if not files[rel]:
            fail(tag, f"{rel}: файл не прочитан — проверка ослепла")
            return
    main = files["relay-fastapi/main.py"]
    bot = files["bot/main_bot.py"]

    # 1. Источник факта. Он обязан РАЗЛИЧАТЬ «файл у нас» и «чек дошёл до
    #    партнёра»: на первом обещать выплату нельзя (это может быть фото
    #    вместо PDF), на втором нельзя показывать реквизиты (заплатят дважды).
    # Docstring вырезаем: он перечисляет ровно те состояния, которые мы ищем, и
    # мина, довольная собственным описанием рядом, — не мина.
    body = _nodoc(_slice(main, "def _receipt_state(", "\ndef ", "\n@app."))
    body = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
    if not body.strip():
        fail(tag, "relay-fastapi/main.py: нет _receipt_state() — единственного "
                  "источника факта о чеке для клиентских поверхностей")
    else:
        for need, why in ((r"order_receipts", "не читает таблицу чеков"),
                          (r"receipt_sent_at", "не отличает дошедший чек от лежащего файла"),
                          (r"""["']sent["']""", "не возвращает состояние 'sent'"),
                          (r"""["']stored["']""", "не возвращает состояние 'stored'")):
            if not re.search(need, body):
                fail(tag, f"relay-fastapi/main.py: _receipt_state() {why} — "
                          f"поверхности получат один и тот же ответ на разные "
                          f"случаи и один из них обязательно соврут клиенту")

    # 2. Списки заявок. Поле receipt должно приходить из ЗАПРОСА к чекам, а не
    #    быть константой: «поле есть, а факта нет» выглядит исправленным.
    for name, start in (("get_user_orders (история кабинета)", "def get_user_orders("),
                        ("/api/history (история Mini App)", "async def api_history(")):
        b = _slice(main, start, "\n@app.", "\ndef ", "\nasync def ")
        if not b:
            fail(tag, f"relay-fastapi/main.py: не найдена {name} — проверка ослепла")
            continue
        m = re.search(r'["\']receipt["\']\s*:\s*([^\n]*)', b)
        if not m:
            fail(tag, f"relay-fastapi/main.py: {name} не отдаёт поле receipt — "
                      f"список заявок клиента не отличит «ждём оплату» от "
                      f"«оплачено, проверяем» и предложит заплатить ещё раз")
        elif "with_receipt" not in m.group(1):
            fail(tag, f"relay-fastapi/main.py: {name} отдаёт receipt мимо запроса "
                      f"к чекам — `{m.group(1).strip()[:70]}`")

    # 3. Локальный таймер не подделывает вердикт сервера: раньше страница /pay
    #    писала C.status='expired', и это же значение глушило её собственный
    #    опрос — настоящий исход она не узнавала уже никогда.
    for i, ln in enumerate(_nocomment_js(main).splitlines(), 1):
        if re.search(r"C\.status\s*=\s*['\"]expired['\"]", ln):
            fail(tag, f"relay-fastapi/main.py: стр. {i} — локальный таймер "
                      f"присваивает C.status='expired'. Это догадка клиента, "
                      f"выданная за ответ сервера; опрос статуса глохнет навсегда")

    # 4. Порядок ветвей на каждой поверхности. Три правила, и все три — про
    #    деньги: (а) исход, объявленный СЕРВЕРОМ, старше чека, иначе отменённая
    #    оператором заявка вечно обещает выплату; (б) чек старше локального
    #    таймера, иначе заплатившему говорят «истекло»; (в) значит закрытая
    #    заявка с чеком идёт первой, потом чек, и только потом срок.
    for rel, where, start, ends, seq in (
        ("relay-fastapi/main.py", "render() страницы /pay", "function render()",
         ("function startTimer",),
         ((r"viewReceiptClosed", "закрытая заявка с чеком"),
          (r"viewReceipt\(\)", "чек на проверке"),
          (r"viewExpired", "истёкший срок"))),
        ("relay/webapp.html", "applyStatus() Mini App", "const applyStatus",
         ("const poll", "function poll"),
         ((r"_receipt\s*&&\s*\(\s*st\s*===\s*'expired'", "закрытая заявка с чеком"),
          (r"_receipt\s*===\s*'sent'", "чек на проверке"),
          (r"if\s*\(\s*st\s*===\s*'expired'", "истёкший срок"))),
    ):
        b = _nocomment_js(_slice(files[rel], start, *ends))
        if not b:
            fail(tag, f"{rel}: не найден {where} — проверка ослепла")
            continue
        pos = []
        for pat, human in seq:
            m = re.search(pat, b)
            i = m.start() if m else -1
            if i < 0:
                fail(tag, f"{rel}: в {where} нет ветки «{human}». Без неё этот "
                          f"случай попадёт в соседнюю ветку и клиент услышит "
                          f"про свои деньги неправду")
            pos.append((i, human))
        for (i1, h1), (i2, h2) in zip(pos, pos[1:]):
            if i1 >= 0 and i2 >= 0 and i1 > i2:
                fail(tag, f"{rel}: в {where} ветка «{h2}» стоит раньше «{h1}» — "
                          f"перехватит её случаи. Порядок обязан идти от самого "
                          f"твёрдого факта (решение сервера) к самой слабой "
                          f"догадке (локальный таймер)")

    # 5. Слово «Оплатить» в списке заявок клиента. Заявке с дошедшим чеком оно
    #    предлагает заплатить второй раз за тот же обмен, поэтому рядом обязан
    #    стоять признак чека.
    for rel, what in (("relay/webapp.html", "история Mini App"),
                      ("relay-fastapi/templates/dashboard_orders.html", "история кабинета")):
        src = re.sub(r"\{#.*?#\}", "", files[rel], flags=re.S)
        lines = _nocomment_js(src).splitlines()
        hits = 0
        # Имена, про которые правило 6 уже доказало, что они СЧИТАЮТСЯ из чека.
        derived = ("eceipt", "hasFile", "onReview", "on_review")
        for i, ln in enumerate(lines):
            if "Оплатить" not in ln:
                continue
            # Ближайший гейт над кнопкой — условие с session_token. Смотрим
            # только его и саму строку: чек, упомянутый десятью строками выше в
            # подписи статуса, кнопку ни от чего не удерживает.
            gate = ""
            for j in range(i, max(0, i - 6), -1):
                if "session_token" in lines[j]:
                    gate = lines[j]
                    break
            if not gate:
                continue
            hits += 1
            if not any(d in gate or d in ln for d in derived):
                fail(tag, f"{rel}: стр. {i + 1} — «Оплатить» в «{what}» выдаётся "
                          f"без оглядки на чек. По этой ссылке клиент, уже "
                          f"оплативший заявку, платит второй раз")
        if not hits:
            fail(tag, f"{rel}: не найдена кнопка оплаты в «{what}» — проверка ослепла")

    # 6. Мёртвая переменная. Признак чека, вычисленный и не влияющий ни на что,
    #    выглядит как исправление, но им не является: достаточно присвоить
    #    False, и все подписи вернутся к «ждёт оплаты» — молча.
    for rel, names in (("relay/webapp.html", ("onReview", "hasFile")),
                       ("bot/main_bot.py", ("on_review",))):
        src = _nocomment_js(files[rel]) if rel.endswith(".html") else "\n".join(
            re.sub(r"#.*$", "", ln) for ln in files[rel].splitlines())
        rows = src.splitlines()
        for n in names:
            found = False
            for i, ln in enumerate(rows):
                if not re.search(rf"\b{n}\s*=\s*[^=]", ln):
                    continue
                found = True
                # Выражение тянем ровно до закрытия скобок, а не «плюс две
                # строки»: иначе `onReview = false;` оправдывался бы соседним
                # объявлением, в котором чек упомянут.
                expr, depth = "", 0
                for k in range(i, min(len(rows), i + 6)):
                    expr += " " + rows[k]
                    depth += rows[k].count("(") - rows[k].count(")")
                    if depth <= 0:
                        break
                if "eceipt" not in expr:
                    fail(tag, f"{rel}: стр. {i + 1} — `{ln.strip()[:60]}` считается "
                              f"мимо факта чека. Подпись «На проверке» станет "
                              f"украшением, а заявка с чеком снова будет "
                              f"числиться ждущей оплаты")
            if not found:
                fail(tag, f"{rel}: переменной {n} нет — проверка ослепла")

    # 7. Списки клиент открывает сам, а ТОЛКАЮЩЕЕ уведомление приходит ему в
    #    чат — и именно оно опаснее всего: «заявка ждёт оплаты», «заявка
    #    истекла, создайте новую», «скидка, создайте новую» человеку, чьи деньги
    #    уже у трейдера. На боевых данных 30.07 так ушли и напоминание (57 чеков
    #    из 64 приходят ДО его окна), и win-back по трём заявкам с чеками.
    # Ищем не слово «order_receipts» где-нибудь рядом (его хватает и проверке
    # существования таблицы), а РАБОТАЮЩЕЕ условие отбора: NOT EXISTS по чекам,
    # и чтобы собранный кусок SQL был реально подставлен в запрос.
    push = r"NOT EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+order_receipts"
    for rel, fn, human, pat in (
        ("bot/main_bot.py", "async def my_orders(", "«Мои заявки»", r"receipts_for\s*\("),
        ("bot/main_bot.py", "async def abandoned_order_reminder(",
         "напоминание «заявка ждёт оплаты»", push),
        ("bot/main_bot.py", "async def winback_promo_task(",
         "win-back «создайте новую заявку»", push),
        ("relay-fastapi/main.py", "async def cleanup_expired_orders(",
         "уведомление «заявка истекла»", push),
    ):
        b = _slice(files[rel], fn, "\nasync def ", "\ndef ", "\n@router.", "\n@app.")
        b = "\n".join(re.sub(r"#.*$", "", ln) for ln in b.splitlines())
        if not b:
            fail(tag, f"{rel}: не найдена {fn} — проверка ослепла")
            continue
        if not re.search(pat, b):
            fail(tag, f"{rel}: {human} не отсеивает заявки с чеком — клиента, "
                      f"который уже заплатил и прислал чек, зовут сделать это "
                      f"ещё раз")
            continue
        # Условие не должно быть ВЫКЛЮЧАЕМЫМ. Собранное в переменную, оно либо
        # не подставится в запрос, либо окажется пустой строкой при первом же
        # «database is locked» — и канал откроется снова, молча. Такой отбор
        # выглядит сделанным ровно до того дня, когда он понадобится.
        m = re.search(r"""(\w+)\s*=\s*\(?\s*["']AND\s+NOT EXISTS""", b)
        if m:
            var = m.group(1)
            if ("{" + var + "}") not in b:
                fail(tag, f"{rel}: в «{human}» условие про чек собрано в "
                          f"{var}, но в запрос не подставлено — отбор "
                          f"выглядит сделанным и не работает")
            elif re.search(var + r"\s*=(?:[^\n]*\n){0,4}[^\n]*else\s*[\"']{2}", b):
                fail(tag, f"{rel}: в «{human}» условие про чек выключается "
                          f"веткой else «пусто» — на любом сбое БД канал "
                          f"откроется снова, и клиента с чеком опять позовут "
                          f"платить. Таблицу создаёт init_db(), условие "
                          f"обязано быть безусловным")

    # 8. HTTP 200 — не то же самое, что «сделано». Подтверждение оплаты идёт по
    #    WHERE status='pending' и по закрытой заявке меняет НОЛЬ строк; оператор
    #    при этом читал «✅ подтверждён» и уходил, а деньги клиента оставались
    #    там же. Ответ обязан нести исход, а бот — его читать.
    b = _slice(main, "async def payment_callback(", "\n@app.", "\nasync def ", "\ndef ")
    if not b:
        fail(tag, "relay-fastapi/main.py: не найден /payment/callback — проверка ослепла")
    elif "rowcount" not in b:
        fail(tag, "relay-fastapi/main.py: /payment/callback не смотрит, сколько строк "
                  "изменил, и отвечает успехом всегда. По закрытой заявке это "
                  "ложное «подтверждено» человеку, который держит в руках деньги "
                  "клиента")
    b = _slice(bot, 'Command("confirm")', "\n@router.")
    b = "\n".join(re.sub(r"#.*$", "", ln) for ln in b.splitlines())
    if not b or "payment/callback" not in b:
        fail(tag, "bot/main_bot.py: не найден /confirm — проверка ослепла")
    elif not re.search(r'get\(\s*["\']ok["\']', b):
        fail(tag, "bot/main_bot.py: /confirm рапортует об успехе по одному коду "
                  "HTTP, не читая исход из ответа — оператор получит «✅ "
                  "подтверждён» там, где не изменилось ни одной строки")


# ─────────────────────────────────────────────────────────────────────
# Проверка подписи ключом из той же посылки = отсутствие проверки
# ─────────────────────────────────────────────────────────────────────
# Кошелёк присылает подпись и рядом публичный ключ, которым её предлагается
# проверять. Взять ключ оттуда — значит принять любую подпись: подписал своим,
# приложил свой. Внешне это работающая интеграция: честный кошелёк проходит,
# тесты зелёные, в логах «verified». Поэтому ключ обязан приходить ТОЛЬКО из
# блокчейна, а положительный вердикт — существовать в единственном месте, за
# всеми проверками. Заодно: успех не должен рождаться в except-ветке, а адрес
# в ответе — приходить из тела запроса (тогда клиенту вернётся то, что он сам
# прислал, с нашей отметкой «подтверждено»).
def check_wallet_proof_is_checked_against_the_chain():
    tag = "подпись кошелька проверяется ключом из цепи"
    path = os.path.join(CANON, "core", "tonconnect.py")
    src = _read(path)
    if not src:
        return                      # модуля ещё нет — проверять нечего
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    vp = fns.get("verify_proof")
    if vp is None:
        fail(tag, "core/tonconnect.py: нет verify_proof — проверка ослепла")
        return

    def _is_ok_verdict(node):
        """Узел означает «подтверждено»?"""
        if isinstance(node, ast.Constant) and node.value is True:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id.endswith("verdict") and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "ok":
            return True
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "verified" \
                        and isinstance(v, ast.Constant) and v.value is True:
                    return True
        return False

    # 1. Ключ — из параметра-источника, а не из проверяемого сообщения.
    params = {a.arg for a in list(vp.args.args) + list(vp.args.kwonlyargs)}
    if "public_key_of" not in params:
        fail(tag, "core/tonconnect.py: verify_proof больше не принимает источник "
                  "ключа — значит ключ берётся откуда-то изнутри, скорее всего "
                  "из самой посылки кошелька")
        return
    sig_calls = [n for n in ast.walk(vp)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and "ed25519" in n.func.id.lower()]
    if not sig_calls:
        fail(tag, "core/tonconnect.py: verify_proof не проверяет подпись ed25519 — "
                  "вердикт выносится без криптографии")
        return
    for call in sig_calls:
        if not call.args or not isinstance(call.args[0], ast.Name):
            fail(tag, "core/tonconnect.py: ключ подставляется в проверку подписи "
                      "выражением на месте — источник не прослеживается")
            continue
        keyvar = call.args[0].id
        sources = [a.value for a in ast.walk(vp)
                   if isinstance(a, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == keyvar for t in a.targets)]
        if len(sources) != 1:
            fail(tag, f"core/tonconnect.py: ключ {keyvar!r} присваивается "
                      f"{len(sources)} раз — проверить его происхождение нельзя")
            continue
        v = sources[0]
        from_chain = (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                      and v.func.id == "public_key_of")
        if not from_chain:
            fail(tag, f"core/tonconnect.py: ключ {keyvar!r} для проверки подписи "
                      "взят не у блокчейна (public_key_of), а из данных запроса — "
                      "такая проверка принимает любую подпись")

    # 2. Успех — в одном месте и только в verify_proof.
    #    Голый `return True` считаем вердиктом лишь там, где функция вообще
    #    выносит вердикты: у криптопримитива True означает «подпись сошлась»,
    #    и запрещать его — правило по написанию, а не по смыслу.
    def _returns_verdicts(fn):
        return any(isinstance(n, ast.Return) and n.value is not None
                   and (isinstance(n.value, ast.Dict)
                        or (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)
                            and n.value.func.id.endswith("verdict")))
                   for n in ast.walk(fn))

    ok_returns = [(fn.name, n) for fn in fns.values() if _returns_verdicts(fn)
                  for n in ast.walk(fn)
                  if isinstance(n, ast.Return) and n.value is not None
                  and _is_ok_verdict(n.value)]
    if len(ok_returns) != 1 or ok_returns[0][0] != "verify_proof":
        fail(tag, "core/tonconnect.py: «подтверждено» возвращается из "
                  f"{[n for n, _ in ok_returns]} — успешный исход обязан быть "
                  "единственным и достижимым только после всех проверок")

    # 3. Успех не рождается в обработчике ошибки.
    for h in ast.walk(tree):
        if isinstance(h, ast.ExceptHandler):
            for n in ast.walk(h):
                if isinstance(n, ast.Return) and n.value is not None and _is_ok_verdict(n.value):
                    fail(tag, "core/tonconnect.py: сбой при проверке подписи "
                              "оборачивается в «подтверждено» — fail-open")

    # 4. Поверхность: источник ключа не подсовывается запросом, адрес в ответе —
    #    из вердикта, а не из тела.
    mp = os.path.join(ROOT, "relay-fastapi", "main.py")
    msrc = _read(mp)
    if not msrc:
        return
    mtree = ast.parse(msrc)
    endpoints = [n for n in ast.walk(mtree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and "tonconnect_verify" in n.name]
    if not endpoints:
        fail(tag, "relay-fastapi/main.py: эндпоинта проверки кошелька нет — "
                  "доказательство владения не доходит ни до одной поверхности")
        return
    for ep in endpoints:
        for call in [n for n in ast.walk(ep) if isinstance(n, ast.Call)]:
            for kw in call.keywords:
                if kw.arg == "public_key_of" and not isinstance(kw.value, (ast.Name, ast.Attribute)):
                    fail(tag, "relay-fastapi/main.py: источник ключа собирается "
                              "выражением в обработчике — он обязан быть ссылкой "
                              "на модуль кошелька, иначе туда легко попадёт "
                              "значение из запроса")
        for ret in [n for n in ast.walk(ep) if isinstance(n, ast.Return)]:
            if not isinstance(ret.value, ast.Dict):
                continue
            for k, v in zip(ret.value.keys, ret.value.values):
                if not (isinstance(k, ast.Constant) and k.value == "address"):
                    continue
                src_names = {n.id for n in ast.walk(v) if isinstance(n, ast.Name)}
                if not src_names & {"verdict", "result"}:
                    fail(tag, "relay-fastapi/main.py: адрес в ответе берётся не из "
                              "вердикта — клиент получит обратно свою же строку с "
                              "отметкой «подтверждено»")

    # 5. Интерфейс: та же ловушка, только видна клиенту. Подключение кошелька
    #    ценно ровно доказательством; если поле адреса заполняется из ответа
    #    КОШЕЛЬКА, клиент получает свой же адрес с нашей отметкой надёжности.
    app = _read(os.path.join(CANON, "webapp.html"))
    if not app:
        return
    m = re.search(r"async\s+function\s+tcHandleWallet\s*\(", app)
    if not m:
        if "tonconnect" in app.lower():
            fail(tag, "relay/webapp.html: подключение кошелька есть, а обработчика "
                      "tcHandleWallet нет — проверка ослепла")
        return
    i = app.index("{", m.end())
    depth, j = 0, i
    while j < len(app):
        depth += 1 if app[j] == "{" else (-1 if app[j] == "}" else 0)
        if depth == 0:
            break
        j += 1
    fn = app[m.start():j + 1]
    assigns = re.findall(r"\.value\s*=\s*([^;\n]+)", fn)
    for expr in assigns:
        if "data" not in expr:
            fail(tag, f"relay/webapp.html: адрес в поле подставляется из {expr.strip()!r} "
                      f"— в ответе кошелька лежит ровно то, что он сам прислал; "
                      f"подтвердить его мог только сервер")
    if not re.search(r"data\s*&&\s*data\.verified|data\?\.verified|data\.verified\s*&&", fn):
        fail(tag, "relay/webapp.html: подстановка адреса не гейтится вердиктом "
                  "сервера — «подтверждено» появится и без проверенной подписи")
    if re.search(r"(account|wallet|w)\.account\.address", fn):
        fail(tag, "relay/webapp.html: обработчик читает адрес из объекта кошелька — "
                  "именно эту строку и нельзя показывать как подтверждённую")


# ─────────────────────────────────────────────────────────────────────
# Строка назначения проверяется как голый адрес
# ─────────────────────────────────────────────────────────────────────
# У валют с тегом назначение хранится ОДНОЙ строкой (`UQ…#memo`, X-адрес), и в
# таком же виде клиент вставляет его с биржи — форма это прямо разрешает и
# прячет отдельное поле тега. Голый валидатор адреса на такой строке отвечает
# «не прошла контрольную сумму»: клиент получает отказ на правильном адресе при
# спрятанном поле тега, а страж перед выплатой — «адрес в БД невалиден» на
# заявке, которую сам же и записал, и уводит её человеку. Проверять назначение
# имеет право только тот, кто знает про склейку.
def check_destination_is_not_checked_as_bare_address():
    tag = "назначение проверяется целиком, а не как голый адрес"
    for rel, guard in ((os.path.join("bot", "main_bot.py"), None),
                       (os.path.join("relay", "utils", "exchange_calc.py"), None),
                       (os.path.join("relay-fastapi", "main.py"), "_resolve_destination")):
        src = _read(os.path.join(ROOT, rel))
        if not src:
            continue
        tree = ast.parse(src)
        allowed = set()
        if guard:
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == guard:
                    allowed |= {id(n) for n in ast.walk(fn)}
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = (call.func.attr if isinstance(call.func, ast.Attribute)
                    else getattr(call.func, "id", ""))
            if name != "validate_address" or id(call) in allowed:
                continue
            where = f" (вне {guard})" if guard else ""
            fail(tag, f"{rel}: validate_address{where} — назначение с тегом "
                      f"склеено в одну строку, и голая проверка адреса отвергнет "
                      f"её как опечатку; нужен validate_destination")

    # Разделитель, объявленный реестром, обязан разбираться ядром: иначе
    # поверхность прячет поле тега, увидев его, а разбор не состоится.
    sys.path.insert(0, CANON)
    try:
        from core import assets as _as
        from core import address as _ad
    except Exception as e:
        fail(tag, f"реестр валют не импортируется: {type(e).__name__}: {e}")
        return
    for cur, sep in getattr(_as, "TAG_SEPARATORS", {}).items():
        probe = f"ЗАВЕДОМО-НЕ-АДРЕС{sep}1"
        try:
            _ad.parse_destination(probe, cur)
        except Exception as e:
            fail(tag, f"core.address: разбор {cur}-назначения со склейкой "
                      f"падает ({type(e).__name__}) — поверхность такую строку "
                      f"принимает, ядро её не переживает")
    if not hasattr(_as, "validate_destination"):
        fail(tag, "core.assets: нет validate_destination — проверять назначение "
                  "целиком нечем, поверхности вернутся к голому адресу")


def main():
    for fn in (check_no_diverging_duplicates, check_config_keys_are_read,
               check_no_fail_open_in_guards, check_session_expiry_uses_expires_at,
               check_every_provider_has_receipt_verdict,
               check_alert_throttle_is_durable, check_deploy_restarts_only_on_change,
               check_manual_payout_uses_agreed_quote, check_no_dead_state_machines,
               check_wallet_currencies_are_offered,
               check_tests_import_their_own_tree,
               check_every_currency_has_a_price_source,
               check_tagless_surfaces_refuse_tagged_currencies,
               check_no_code_loaded_from_hardcoded_path,
               check_explorer_links_have_one_source,
               check_rates_api_follows_the_showcase,
               check_no_tag_is_explicit,
               check_sell_menu_offers_only_receivable_coins,
               check_unparsed_input_is_not_silence,
               check_no_unreachable_handlers,
               check_blocklist_matches_account_not_string,
               check_guards_compare_accounts_not_strings,
               check_coin_lists_come_from_the_shopfront,
               check_failed_autopayout_reaches_a_human,
               check_tagged_currencies_use_the_dispatcher,
               check_tag_shape_comes_from_the_registry,
               check_wallet_modules_are_registered,
               check_wallet_proof_is_checked_against_the_chain,
               check_destination_is_not_checked_as_bare_address,
               check_receipt_beats_the_timer,
               check_migrations_agree,
               check_debt_queue_is_visible,
               check_attempt_id_is_symmetric,
               check_dead_deal_is_not_silent,
               check_every_currency_is_reconcilable):
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
