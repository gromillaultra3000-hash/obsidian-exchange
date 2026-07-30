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
               check_receipt_beats_the_timer,
               check_migrations_agree,
               check_debt_queue_is_visible):
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
