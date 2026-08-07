#!/usr/bin/env python3
"""Ставка выкупа: одно число, одна формула, все поверхности.

Владелец назначил 07.08.2026 единую ставку на выкуп крипты — 9% от рынка,
независимо от суммы. До этого выкуп считался по ступени ПОКУПКИ на 50 000 ₽ и
в двух местах по-разному: сайт брал голую ступень, бот применял к ней скидку
VIP и промокода. Один и тот же клиент видел в боте и на сайте разный курс
выкупа и получал тот, где создал заявку.

Здесь проверяется не только «девять», но и то, из-за чего вернуть расхождение
было бы легко: формула живёт в одном месте, поверхности берут число оттуда, а
не считают своё.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# Окружение чистим: тест о значениях по умолчанию не должен зависеть от того,
# что кто-то экспортировал в оболочке.
for _k in [k for k in os.environ if k.startswith("SELL_COMMISSION")]:
    os.environ.pop(_k)

from core import pricing  # noqa: E402

# ── 1. Ставка одна и не зависит от суммы ─────────────────────────────────────
check(pricing.sell_commission_percent() == 9,
      f"ставка выкупа не 9%, а {pricing.sell_commission_percent()}")
check(pricing.sell_commission_label() == "9%",
      f"витринная подпись ставки испорчена: {pricing.sell_commission_label()!r}")

# Лестница покупки к выкупу отношения не имеет: у неё четыре разных процента,
# и если выкуп когда-нибудь снова начнёт от неё зависеть, здесь это видно.
rates = {pricing.sell_rate(1000, "BTC"), pricing.sell_rate(1000, "LTC"),
         pricing.sell_rate(1000, "USDT")}
check(rates == {910.0},
      f"выкуп зависит от монеты там, где не должен: {rates}")
check(pricing.sell_rate(4_000_000) == 3_640_000.0,
      f"курс выкупа посчитан неверно: {pricing.sell_rate(4_000_000)}")

# ── 2. Отсутствие цены — отказ, а не ноль в выплате ──────────────────────────
for bad in (0, None, "", "abc", -100, float("inf"), float("nan")):
    check(pricing.sell_rate(bad) == 0.0,
          f"нечисловая рыночная цена {bad!r} дала курс {pricing.sell_rate(bad)}")

# ── 3. Оверрайд без релиза, но с проверкой вменяемости ───────────────────────
os.environ["SELL_COMMISSION_BTC"] = "7"
check(pricing.sell_commission_percent("BTC") == 7, "точечный оверрайд монеты не сработал")
check(pricing.sell_commission_percent("LTC") == 9, "оверрайд одной монеты протёк на другую")
check(pricing.sell_commission_label("BTC") == "7%", "подпись не подхватила оверрайд")

os.environ["SELL_COMMISSION_BTC"] = "7.5"
check(pricing.sell_commission_label("BTC") == "7.5%",
      "дробная ставка показана неверно: " + pricing.sell_commission_label("BTC"))

# Опечатка в переменной не должна становиться ценой: «900» вместо «9,00» дало бы
# отрицательную выплату, а «90» — курс в десять раз ниже рынка.
for junk in ("900", "90", "-5", "девять", ""):
    os.environ["SELL_COMMISSION_BTC"] = junk
    check(pricing.sell_commission_percent("BTC") == 9,
          f"негодное значение {junk!r} принято как ставка "
          f"({pricing.sell_commission_percent('BTC')})")
os.environ.pop("SELL_COMMISSION_BTC")

os.environ["SELL_COMMISSION_PERCENT"] = "12"
check(pricing.sell_commission_percent("LTC") == 12, "общий оверрайд не сработал")
os.environ.pop("SELL_COMMISSION_PERCENT")

# ── 3б. Общая подпись не врёт при точечном оверрайде (нашёл codex) ───────────
# Витрины, где монета ещё не выбрана (вход в раздел, главная, FAQ, пост),
# показывали ставку по умолчанию. С SELL_COMMISSION_BTC=7 такая витрина
# обещала «минус 9%», а биткойн выкупался по 7% — обещание, которого расчёт
# не выполняет, то есть ровно тот дефект, против которого вся эта задача.
check(pricing.sell_commission_label_for(["BTC", "LTC"]) == "9%",
      "при одинаковых ставках общая подпись перестала быть одним числом")
os.environ["SELL_COMMISSION_BTC"] = "7"
check(pricing.sell_commission_label_for(["BTC", "LTC"]) == "7–9%",
      "общая подпись скрыла точечный оверрайд: "
      + pricing.sell_commission_label_for(["BTC", "LTC"]))
check(pricing.sell_commission_label_for(["BTC"]) == "7%",
      "подпись для единственной монеты с оверрайдом неверна")
os.environ.pop("SELL_COMMISSION_BTC")
check(pricing.sell_commission_label_for([]) == "",
      "подпись без направлений продажи должна молчать, а не показывать умолчание")

# ── 4. Сайт и бот считают ОДНИМ движком ──────────────────────────────────────
# Именно этого не было: две реализации формулы, расходившиеся на скидках VIP.
calc_src = read("relay", "utils", "exchange_calc.py")
tree = ast.parse(calc_src)
get_sell = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "get_sell_rate"), None)
check(get_sell is not None, "get_sell_rate пропал из exchange_calc")
if get_sell:
    body = ast.dump(get_sell)
    check("sell_rate" in body,
          "get_sell_rate больше не зовёт общий pricing.sell_rate — формула снова своя")
    check("get_commission_percent" not in body,
          "выкуп на сайте снова считается по лестнице ПОКУПКИ")
    # Умножение на (1 - x/100) прямо здесь = вторая копия формулы.
    check(not any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)
                  for n in ast.walk(get_sell)),
          "в get_sell_rate вернулось собственное умножение — формула раздвоилась")

bot_src = read("bot", "main_bot.py")
bot_tree = ast.parse(bot_src)
sell_screen = next((n for n in ast.walk(bot_tree)
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "process_sell_currency"), None)
check(sell_screen is not None, "экран выбора монеты для продажи пропал из бота")
if sell_screen:
    calls = {n.func.id for n in ast.walk(sell_screen)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    check("sell_rate_for" in calls,
          "бот больше не зовёт общий расчёт выкупа")
    check("get_commission_percent" not in calls,
          "бот снова считает выкуп по лестнице покупки — курс разойдётся с сайтом")

# Скидка VIP на выкуп не применяется — она заработана оборотом ПОКУПОК, и
# применённая к 9% превратила бы маржу в 2% (пол лестницы).
sell_rate_for = next((n for n in ast.walk(bot_tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "sell_rate_for"), None)
check(sell_rate_for is not None, "sell_rate_for пропал из бота")
if sell_rate_for:
    names = {n.id for n in ast.walk(sell_rate_for) if isinstance(n, ast.Name)}
    check("get_user_vip" not in names and "_active_promos" not in names,
          "в расчёт выкупа вернулись персональные скидки")

# ── 5. Живой прогон обоих путей на одной цене ────────────────────────────────
# Курс берём из подменённого источника: тест не ходит в сеть.
from utils import exchange_calc  # noqa: E402

exchange_calc._rate_cache["BTC"] = {"rate": 5_000_000, "ts": 9e18}
site_rate = exchange_calc.get_sell_rate("BTC")
check(site_rate == pricing.sell_rate(5_000_000, "BTC") == 4_550_000.0,
      f"сайт посчитал выкуп {site_rate}, движок — {pricing.sell_rate(5_000_000, 'BTC')}")

# ── 6. Поверхности показывают ставку и берут её с сервера ────────────────────
main_src = read("relay-fastapi", "main.py")
check('"sell_commission": _sell_commission_label()' in main_src,
      "шаблоны сайта не получают ставку выкупа в общем контексте")
# Обе поверхности обязаны собирать общую подпись по СПИСКУ открытых монет, а не
# по умолчанию: иначе точечный оверрайд снова разойдётся с витриной.
check("sell_commission_label_for(_sell_currencies())" in main_src,
      "сайт строит общую подпись мимо списка направлений продажи")
check("_scl_for(sell_coins())" in bot_src,
      "бот строит общую подпись мимо списка направлений продажи")
check('"fee_label": _sell_commission_label()' in main_src,
      "/api/sell/options не отдаёт ставку — Mini App нечего показать")
check('"fee_percent"' in main_src,
      "разбивка выплаты не получает процент с сервера")

for tpl, why in (("dashboard_sell.html", "страница продажи"),
                 ("index.html", "главная"),
                 ("faq.html", "FAQ"),
                 ("how_it_works.html", "как это работает")):
    src = read("relay-fastapi", "templates", tpl)
    check("sell_commission" in src, f"{why} не называет ставку выкупа из источника")

# Фраза о ставке обязана исчезать целиком, когда ставки нет. Источник может
# отказать (сбой импорта — предусмотренный путь, он возвращает пустую строку), и
# незащищённая фраза превращается в «рыночный минус  — ставка не зависит от
# суммы»: обещание без числа рядом с кнопкой «продать». Нашёл codex.
guarded = set()
for node in ast.walk(bot_tree):
    if isinstance(node, ast.IfExp):
        for inner in ast.walk(node):
            if isinstance(inner, (ast.JoinedStr, ast.Constant)):
                guarded.add(id(inner))
for node in ast.walk(bot_tree):
    if not isinstance(node, ast.JoinedStr) or id(node) in guarded:
        continue
    text = "".join(v.value for v in node.values
                   if isinstance(v, ast.Constant) and isinstance(v.value, str))
    # Ищем именно фразу о курсе выкупа. Просто «минус» ловит и «каждый 5-й
    # обмен — минус 1 000 ₽» в рекламном посте: мина, красная на исправном
    # коде, перестаёт что-либо значить.
    if (re.search(r"(рынок|рыночный)\s+минус", text)
            and any(isinstance(v, ast.FormattedValue) for v in node.values)):
        check(False, f"бот собирает фразу о ставке без защиты от её отсутствия: {text[:60]!r}")

for tpl in ("dashboard_sell.html", "index.html", "faq.html", "how_it_works.html"):
    src = read("relay-fastapi", "templates", tpl)
    check("{% if sell_commission" in src,
          f"{tpl} печатает ставку выкупа без проверки, что она вообще есть")

webapp = read("relay", "webapp.html")
check("fee_label" in webapp and "sell-fee-note" in webapp,
      "Mini App не показывает ставку выкупа до ввода суммы")
check("sell-breakdown" in webapp, "в Mini App нет разбивки выплаты")

# Ни одна витрина не должна печатать ставку числом мимо источника — именно так
# «19–27%» пережили смену тарифа в трёх местах сразу.
for path in (("relay-fastapi", "templates", "dashboard_sell.html"),
             ("relay-fastapi", "templates", "index.html"),
             ("relay-fastapi", "templates", "how_it_works.html"),
             ("relay", "webapp.html")):
    src = read(*path)
    # Комментарии (Jinja и HTML) — это объяснение, а не обещание клиенту.
    body = re.sub(r"\{#.*?#\}|<!--.*?-->", "", src, flags=re.S)
    stale = re.findall(r"минус\s*<?[a-z]*>?\s*(\d{1,2})\s*%", body)
    check(not stale,
          f"{path[-1]}: ставка выкупа вписана числом {stale} мимо источника")

# ── 7. Рекламный пост: выкуп назван и подпись влезает в лимит Telegram ───────
post = next((n for n in ast.walk(bot_tree)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "compose_daily_post"), None)
check(post is not None, "рекламный пост пропал")
if post:
    post_calls = {n.func.id for n in ast.walk(post)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    check("sell_rate_for" in post_calls,
          "пост не рекламирует выкуп — направление работает, а зовём только покупать")
    # Ставку ищем среди ЧИСЕЛ, а не в тексте функции: комментарий рядом,
    # объясняющий, почему литерала быть не должно, сам содержит «0.19» и делал
    # проверку по строке всегда красной.
    numbers = {n.value for n in ast.walk(post)
               if isinstance(n, ast.Constant) and isinstance(n.value, float)}
    check(not any(0 < v < 1 for v in numbers),
          f"в посте снова доля-литерал вместо ставки из лестницы: {numbers}")

    # Caption у медиа-сообщения — 1024 символа. Пост длиннее уходит в ошибку
    # отправки, то есть рассылка молча перестаёт выходить, а заметно это только
    # по её отсутствию. Считаем сам собираемый текст, а не всю функцию.
    body_node = next((n.value for n in post.body
                      if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "text" for t in n.targets)), None)
    check(body_node is not None, "в посте не нашлось сборки текста")
    if body_node is not None:
        fixed = sum(len(n.value) for n in ast.walk(body_node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str))
        slots = sum(1 for n in ast.walk(body_node) if isinstance(n, ast.FormattedValue))
        # 16 символов на подставленное значение — с запасом: самый длинный из
        # них, курс BTC с разделителями, занимает 9.
        worst = fixed + slots * 16
        check(worst < 1024,
              f"подпись поста в худшем случае {worst} символов при лимите 1024 "
              f"({fixed} текста + {slots} подстановок)")

if FAILS:
    print(f"❌ Ставка выкупа: {len(FAILS)} провал(ов)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✅ Ставка выкупа: 9% из одного источника, одна формула на бот/сайт/Mini App, "
      "витрины берут число с сервера")
