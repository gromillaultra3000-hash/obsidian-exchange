#!/usr/bin/env python3
"""Поле тега на сайте и в Mini App: спрятать — не то же самое, что очистить.

Зачем этот тест. Скрытый `<input>` продолжает уходить с формой. Клиент,
набравший destination tag для XRP и передумавший на BTC, отправлял бы вместе с
заявкой уже ненужный тег, а сервер честно отвечает «для этой валюты тег не
используется» — отказ на исправной заявке, причину которой клиент не видит.
Нашёл это внешний ревьюер, не свой критик и не глаза; значит, нужна машина.

Как проверяем. Разбирать HTML целиком в node бессмысленно (там Telegram
WebApp, fetch, localStorage). Вытаскиваем ИМЕННО те функции, которые управляют
полем тега, и гоняем их на крошечной заглушке DOM — так тест ловит логику, а
не окружение, и не ломается от правок соседнего кода.

Запуск: /root/bot/venv/bin/python3 tests/test_tag_field_frontend.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def extract_function(src, name):
    """Тело функции `function name(...) { ... }` со сбалансированными скобками."""
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    if not m:
        raise SystemExit(f"в исходнике нет функции {name}() — тест устарел, поправьте его")
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise SystemExit(f"не закрылась функция {name}()")


DOM_STUB = r"""
// Заглушка DOM: ровно то, чем пользуются проверяемые функции.
function mkEl(id) {
  const attrs = {};
  return { id: id, value: '', textContent: '', innerHTML: '', checked: false,
           style: { display: '' },
           setAttribute: (k, v) => { attrs[k] = v; },
           getAttribute: (k) => (k in attrs ? attrs[k] : null) };
}
const _els = {};
for (const id of ['currency','address','dest_tag','tag-group','tag-label','tag-hint',
                  'network','no_tag','no-tag-label']) {
  _els[id] = mkEl(id);
}
const document = { getElementById: (id) => _els[id] || null };
const window = {};
"""


def run_js(body, scenario):
    js = DOM_STUB + "\n" + body + "\n" + scenario + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise SystemExit(f"node упал:\n{r.stderr}")
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


if not shutil.which("node"):
    print("⚠️  node не установлен — проверку фронта пропускаем (не провал)")
    sys.exit(0)

X_ADDR = "X7TYt4nPauxSispXtYbecsfAHuA4ciuXLfdxguAicta1ViD"
CLASSIC = "rrpDp2dLMs7KyhZhg5RbReRagjWuvH7qB"
TON_ADDR = "UQAs9VlT6S9pyC_dpJv0Xh0Cq6HxvMSjTX0aKGl_j8V5MjSf"

# Витрину собираем ИЗ РЕЕСТРА, а не руками: у тега два свойства (вид значения и
# разделитель внутри адреса), и вписанная сюда копия отстала бы от реестра на
# следующей валюте — тест бы позеленел на разошедшемся фронте.
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import assets as ASSETS  # noqa: E402


def offering(code):
    return {"code": code,
            "tag_name": ASSETS.TAGGED_CURRENCIES.get(code, ""),
            "tag_kind": ASSETS.tag_kind(code) or "",
            "tag_sep": ASSETS.tag_separator(code) or ""}


OFFERINGS = json.dumps([offering(c) for c in ("BTC", "USDT", "XRP", "TON")])

# ── Сайт: /dashboard/exchange ───────────────────────────────────────────────
site_src = open(os.path.join(ROOT, "relay-fastapi/templates/dashboard_exchange.html"),
                encoding="utf-8").read()
site_body = "const OFFERINGS = %s;\n" % OFFERINGS + "\n".join(
    extract_function(site_src, n)
    for n in ("currentOffering", "currentTagName", "addressCarriesTag", "onAddressChange"))

res = run_js(site_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
onAddressChange();
const shownForXrp = _els['tag-group'].style.display !== 'none';
_els['dest_tag'].value = '777';
_els['currency'].value = 'BTC';     // клиент передумал
onAddressChange();
console.log(JSON.stringify({
  shownForXrp: shownForXrp,
  hiddenForBtc: _els['tag-group'].style.display === 'none',
  submitted: _els['dest_tag'].value
}));
""" % json.dumps(CLASSIC))

check("сайт: у XRP с classic-адресом поле тега показано", res["shownForXrp"])
check("сайт: у BTC поле тега спрятано", res["hiddenForBtc"])
check("сайт: после смены XRP→BTC тег НЕ уходит с формой", res["submitted"] == "")

res = run_js(site_body, """
_els['currency'].value = 'XRP';
_els['dest_tag'].value = '777';
_els['address'].value = %s;          // X-адрес уже содержит тег внутри
onAddressChange();
console.log(JSON.stringify({
  hidden: _els['tag-group'].style.display === 'none',
  submitted: _els['dest_tag'].value
}));
""" % json.dumps(X_ADDR))

check("сайт: X-адрес прячет поле тега", res["hidden"])
check("сайт: X-адрес стирает ранее введённый тег (иначе два разных значения)",
      res["submitted"] == "")

# ── Mini App: relay/webapp.html ─────────────────────────────────────────────
app_src = open(os.path.join(ROOT, "relay/webapp.html"), encoding="utf-8").read()
app_body = "\n".join(
    extract_function(app_src, n)
    for n in ("currentOffering", "currentTagName", "addressCarriesTag", "updateTagField"))

# В Mini App витрина лежит в window.__oeOfferings, а в тело запроса тег попадает
# через проверку видимости. Выражение НЕ переписываем сюда руками: копия жила
# бы своей жизнью, и правка обработчика теста не уронила бы (замечание внешнего
# ревью). Берём те самые строки из исходника.
def extract_block(src, first_line, last_prefix):
    """Кусок кода от строки `first_line` до строки, начинающейся с `last_prefix`."""
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines) if first_line in ln), None)
    if start is None:
        raise SystemExit(f"в исходнике нет строки {first_line!r} — тест устарел")
    for j in range(start, min(start + 12, len(lines))):
        if lines[j].strip().startswith(last_prefix):
            return "\n".join(ln.strip() for ln in lines[start:j + 1])
    raise SystemExit(f"после {first_line!r} не нашлась строка {last_prefix!r} — тест устарел")


SUBMIT_EXPR = extract_block(app_src, "const tagEl = document.getElementById('dest_tag')",
                            "const noTag")

res = run_js("window.__oeOfferings = %s;\n" % OFFERINGS + app_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
updateTagField();
_els['dest_tag'].value = '777';
_els['currency'].value = 'USDT';    // клиент передумал
updateTagField();
%s
console.log(JSON.stringify({ stored: _els['dest_tag'].value, destTag: destTag }));
""" % (json.dumps(CLASSIC), SUBMIT_EXPR))

check("Mini App: после смены XRP→USDT значение тега стёрто", res["stored"] == "")
check("Mini App: в тело запроса тег не попадает", res["destTag"] == "")

res = run_js("window.__oeOfferings = %s;\n" % OFFERINGS + app_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
updateTagField();
_els['dest_tag'].value = '777';
%s
console.log(JSON.stringify({ destTag: destTag }));
""" % (json.dumps(CLASSIC), SUBMIT_EXPR))

check("Mini App: у XRP введённый тег доезжает до запроса", res["destTag"] == "777")

# ── Галочка «тега нет»: пустое поле не должно сходить за согласие ───────────
# Сервер принимает заявку без тега только по явному «нет тега» (в боте это
# отдельная кнопка). Галочка обязана вести себя как ответ: пропадать вместе с
# полем и не соседствовать с набранным тегом — иначе клиент отправит оба.
res = run_js("window.__oeOfferings = %s;\n" % OFFERINGS + app_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
updateTagField();
_els['no_tag'].checked = true;
// Выражение сборки запроса — из исходника; в блоке, чтобы его можно было
// выполнить дважды (const в одной области видимости повторно не объявить).
let withBox, afterSwitch;
{ %s
  withBox = { destTag: destTag, noTag: noTag }; }
_els['currency'].value = 'USDT';    // клиент передумал
updateTagField();
{ %s
  afterSwitch = noTag; }
console.log(JSON.stringify({ withBox: withBox, afterSwitch: afterSwitch,
                             boxState: _els['no_tag'].checked }));
""" % (json.dumps(CLASSIC), SUBMIT_EXPR, SUBMIT_EXPR))

check("Mini App: галочка «тега нет» доезжает до запроса", res["withBox"]["noTag"] is True)
check("Mini App: смена валюты снимает галочку", res["boxState"] is False)
check("Mini App: после смены валюты «тега нет» не уходит с заявкой",
      res["afterSwitch"] is False)

res = run_js("window.__oeOfferings = %s;\n" % OFFERINGS + app_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
_els['no_tag'].checked = true;
_els['dest_tag'].value = '777';     // и тег, и «тега нет» одновременно
updateTagField();
console.log(JSON.stringify({ box: _els['no_tag'].checked, tag: _els['dest_tag'].value }));
""" % json.dumps(CLASSIC))

check("Mini App: набранный тег снимает галочку «тега нет»", res["box"] is False)
check("Mini App: сам тег при этом сохраняется", res["tag"] == "777")

res = run_js(site_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
_els['no_tag'].checked = true;
onAddressChange();
const beforeX = _els['no_tag'].checked;
_els['address'].value = %s;          // X-адрес несёт тег внутри
onAddressChange();
console.log(JSON.stringify({ beforeX: beforeX, afterX: _els['no_tag'].checked }));
""" % (json.dumps(CLASSIC), json.dumps(X_ADDR)))

check("сайт: галочка «тега нет» держится на classic-адресе", res["beforeX"] is True)
check("сайт: X-адрес снимает галочку (тег уже внутри адреса)", res["afterX"] is False)


# ── Вид тега: числовая клавиатура на текстовом memo = набрать нельзя ────────
# У XRP тег числовой, у TON memo — произвольный текст. Клавиатура и пример
# должны приходить из витрины (tag_kind), иначе клиент TON с телефона получит
# цифровую панель и правильный memo просто не наберёт.
res = run_js(site_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
onAddressChange();
const xrpMode = _els['dest_tag'].getAttribute('inputmode');
_els['currency'].value = 'TON';
_els['address'].value = %s;
onAddressChange();
console.log(JSON.stringify({ xrpMode: xrpMode,
  tonMode: _els['dest_tag'].getAttribute('inputmode'),
  tonShown: _els['tag-group'].style.display !== 'none',
  tonPlaceholder: _els['dest_tag'].getAttribute('placeholder') }));
""" % (json.dumps(CLASSIC), json.dumps(TON_ADDR)))

check("сайт: у XRP клавиатура числовая", res["xrpMode"] == "numeric")
check("сайт: у TON клавиатура текстовая", res["tonMode"] == "text")
check("сайт: у TON поле memo показано", res["tonShown"])
check("сайт: пример у TON не числовой", "12345" not in (res["tonPlaceholder"] or ""))

# Разделитель тега внутри адреса — тоже свойство валюты: у TON это «#», а
# двоеточие живёт в его СЫРОМ адресе (`0:hex64`) как часть адреса. Прибитый
# разделитель `:` разрезал бы такой адрес пополам.
res = run_js(site_body, """
_els['currency'].value = 'TON';
_els['address'].value = '0:' + 'a'.repeat(64);
onAddressChange();
const rawShown = _els['tag-group'].style.display !== 'none';
_els['address'].value = %s + '#order-42';
onAddressChange();
console.log(JSON.stringify({ rawShown: rawShown,
  gluedHidden: _els['tag-group'].style.display === 'none' }));
""" % json.dumps(TON_ADDR))

check("сайт: сырой TON-адрес `0:hex` не принят за «тег внутри адреса»", res["rawShown"])
check("сайт: склейка «адрес#memo» прячет поле тега", res["gluedHidden"])

res = run_js("window.__oeOfferings = %s;\n" % OFFERINGS + app_body, """
_els['currency'].value = 'XRP';
_els['address'].value = %s;
updateTagField();
const xrpMode = _els['dest_tag'].getAttribute('inputmode');
_els['currency'].value = 'TON';
_els['address'].value = '0:' + 'a'.repeat(64);
updateTagField();
const rawShown = _els['tag-group'].style.display !== 'none';
const tonMode = _els['dest_tag'].getAttribute('inputmode');
_els['address'].value = %s + '#order-42';
updateTagField();
console.log(JSON.stringify({ xrpMode: xrpMode, tonMode: tonMode, rawShown: rawShown,
  gluedHidden: _els['tag-group'].style.display === 'none' }));
""" % (json.dumps(CLASSIC), json.dumps(TON_ADDR)))

check("Mini App: у XRP клавиатура числовая", res["xrpMode"] == "numeric")
check("Mini App: у TON клавиатура текстовая", res["tonMode"] == "text")
check("Mini App: сырой TON-адрес `0:hex` не принят за «тег внутри адреса»", res["rawShown"])
check("Mini App: склейка «адрес#memo» прячет поле тега", res["gluedHidden"])


# ── Логика привязана к вводу адреса, а не только существует ─────────────────
# Проверять функции, которые никто не вызывает, — самообман: в Mini App
# `updateTagField` была исправна, но у поля адреса висел только валидатор
# формата, и X-адрес не прятал поле тега. Проверяем саму привязку.
def handler_of(src, element_id, event="oninput"):
    m = re.search(r'id="%s"[^>]*?%s="([a-zA-Z_$][\w$]*)\s*\(' % (re.escape(element_id), event),
                  src, re.S)
    if not m:
        m = re.search(r'%s="([a-zA-Z_$][\w$]*)\s*\([^>]*?id="%s"' % (event, re.escape(element_id)),
                      src, re.S)
    return m.group(1) if m else None


def reaches_tag_field(src, entry, target, depth=3):
    """Ведёт ли обработчик к функции поля тега (напрямую или через вызов)."""
    if not entry:
        return False
    if entry == target:
        return True
    if depth <= 0:
        return False
    try:
        body = extract_function(src, entry)
    except SystemExit:
        return False
    if re.search(r"\b%s\s*\(" % re.escape(target), body):
        return True
    return any(reaches_tag_field(src, name, target, depth - 1)
               for name in set(re.findall(r"\b([a-zA-Z_$][\w$]*)\s*\(", body)) - {entry})


app_handler = handler_of(app_src, "address")
site_handler = handler_of(site_src, "address")
check("Mini App: ввод адреса пересчитывает поле тега",
      reaches_tag_field(app_src, app_handler, "updateTagField"))
check("сайт: ввод адреса пересчитывает поле тега",
      reaches_tag_field(site_src, site_handler, "onAddressChange"))

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
