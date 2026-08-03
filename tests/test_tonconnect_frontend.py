#!/usr/bin/env python3
"""Кнопка «Подключить кошелёк» в Mini App: что она обещает клиенту.

Зачем этот тест. Подключение кошелька ценно ровно одним — адрес перестаёт быть
набранным вручную и подтверждается подписью. Если интерфейс поставит «✅
подтверждён» по одному факту подключения, клиент получит ЛОЖНУЮ уверенность:
адрес будет тот же, что он мог бы вставить руками, но с нашей отметкой
надёжности. Поэтому и адрес, и слово «подтверждён» обязаны приходить из ответа
сервера — он один видел подпись, проверенную ключом счёта из блокчейна.

Второе: подключение — удобство, а не условие. Нет SDK, нет проверочного кода,
кошелёк не выдал подпись, сервер отказал — во всех случаях клиент обязан
остаться с работающим ручным вводом, а не в тупике.

Как проверяем — как и соседний фронт-тест: вытаскиваем именно те функции,
которые управляют блоком, и гоняем их на заглушке DOM.

Запуск: /root/bot/venv/bin/python3 tests/test_tonconnect_frontend.py
"""
import hashlib
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
    # `async` — часть объявления: срезав его, тест вырезал бы функцию, которая
    # не компилируется (await вне async), и упал бы по причине, не имеющей
    # отношения к проверяемому поведению.
    m = re.search(r"(?:async\s+)?function\s+%s\s*\(" % re.escape(name), src)
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


WEBAPP = os.path.join(ROOT, "relay", "webapp.html")
src = open(WEBAPP, encoding="utf-8").read()

# ── Часть 1: чужой код в кошельковом флоу зафиксирован ───────────────────────
# Версия и сумма — не педантизм: подменённый бандл здесь видит адрес кошелька
# клиента и всё, что он подписывает.
SDK_REL = "relay-fastapi/static/js/tonconnect-ui-3.0.0.min.js"
SDK_SHA = "64964c3ae13c752bbabba990ddc51f7dd20759083368541d9199e04e3342656d"
sdk_path = os.path.join(ROOT, SDK_REL)
check("SDK кошелька лежит в нашей статике, а не на чужом CDN",
      os.path.isfile(sdk_path))
if os.path.isfile(sdk_path):
    with open(sdk_path, "rb") as f:
        got = hashlib.sha256(f.read()).hexdigest()
    check(f"файл SDK не подменялся (sha256 {SDK_SHA[:12]}…)", got == SDK_SHA)
check("страница грузит SDK со своего домена и с точной версией",
      'src="/static/js/tonconnect-ui-3.0.0.min.js"' in src)
check("страница не тянет кошельковый SDK с внешнего хоста",
      not re.search(r'src="https?://[^"]*tonconnect', src))
check("сбой загрузки SDK помечается, а не остаётся незамеченным",
      "__oeTonConnectFailed" in src)

if not shutil.which("node"):
    print("⚠️  node не установлен — поведенческую часть пропускаем (не провал)")
    if failures:
        print(f"\n{len(failures)} провал(ов): {failures}")
        sys.exit(1)
    sys.exit(0)

# ── Часть 2: поведение блока ─────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import assets as ASSETS  # noqa: E402

# Витрина — из реестра: список монет, вписанный сюда руками, отстал бы от него
# на следующей же сети, и тест позеленел бы на разошедшемся фронте.
OFFERINGS = json.dumps([
    {"code": c,
     "tag_name": ASSETS.TAGGED_CURRENCIES.get(c, ""),
     "tag_kind": ASSETS.tag_kind(c) or "",
     "tag_sep": ASSETS.tag_separator(c) or "",
     "wallet_connect": ASSETS.supports_wallet_connect(c)}
    for c in ("BTC", "USDT", "XRP", "TON")])

TON_ADDR = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI"
OTHER_ADDR = "UQAtQ0lXeaJGqPq9Y0PhWJzMOm3Q9DiwSaSlWEvJ0hnwuYVc"

DOM_STUB = r"""
function mkEl(id) {
  const attrs = {};
  return { id: id, value: '', textContent: '', innerHTML: '', checked: false,
           disabled: false, className: '', style: { display: '' },
           setAttribute: (k, v) => { attrs[k] = v; },
           getAttribute: (k) => (k in attrs ? attrs[k] : null),
           addEventListener: () => {} };
}
const _els = {};
for (const id of ['currency','address','dest_tag','tag-group','tag-label','tag-hint',
                  'network','no_tag','no-tag-label','tc-group','tc-connect','tc-msg']) {
  _els[id] = mkEl(id);
}
const document = { getElementById: (id) => _els[id] || null };
const window = { TON_CONNECT_UI: {}, location: { origin: 'https://obsidian-exchange.org' } };
const tg = { initData: 'stub', HapticFeedback: { notificationOccurred: () => {} } };
let _validated = 0;
function validateAddress() { _validated++; }
function updateTagField() {}
let _fetchReply = {};
let _fetchCalls = [];
function fetch(url, opts) {
  _fetchCalls.push(url);
  const r = _fetchReply[url];
  if (r === 'boom') return Promise.reject(new Error('сеть'));
  return Promise.resolve({ json: () => Promise.resolve(r || {}) });
}
"""

body = ("const __OFF = %s;\nwindow.__oeOfferings = __OFF;\n"
        "let tcUI = null;\nlet tcPending = false;\n" % OFFERINGS) + "\n".join(
    extract_function(src, n) for n in
    ("currentOffering", "tcAvailable", "tcSay", "tcRefresh", "tcHandleWallet"))


def run_js(scenario):
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


# Видимость: только там, где кошелёк действительно умеет подключиться.
res = run_js("""
const seen = {};
for (const c of ['BTC','USDT','XRP','TON']) {
  _els['currency'].value = c;
  tcRefresh();
  seen[c] = _els['tc-group'].style.display !== 'none';
}
_els['currency'].value = 'TON';
window.__oeTonConnectFailed = true;   // SDK не загрузился
tcRefresh();
const afterFail = _els['tc-group'].style.display !== 'none';
window.__oeTonConnectFailed = false;
delete window.TON_CONNECT_UI;         // SDK не подключён вовсе
tcRefresh();
const noSdk = _els['tc-group'].style.display !== 'none';
console.log(JSON.stringify({ seen, afterFail, noSdk }));
""")
check("кнопка показана у монеты с подключаемым кошельком", res["seen"]["TON"])
check("у остальных монет кнопки нет (список монет — из витрины)",
      not res["seen"]["BTC"] and not res["seen"]["USDT"] and not res["seen"]["XRP"])
check("SDK не загрузился → кнопки нет, ручной ввод остаётся", not res["afterFail"])
check("SDK отсутствует вовсе → кнопки нет", not res["noSdk"])

# Успешная проверка: адрес и «подтверждено» приходят от сервера.
res = run_js("""
_els['currency'].value = 'TON';
_fetchReply['/api/tonconnect/verify'] = { verified: true, address: %s, message: 'ок' };
tcHandleWallet({ account: { address: '0:aaa' },
                 connectItems: { tonProof: { proof: { signature: 'x' } } } })
  .then(() => console.log(JSON.stringify({
      address: _els['address'].value,
      msg: _els['tc-msg'].textContent,
      cls: _els['tc-msg'].className,
      validated: _validated,
      noTag: _els['no_tag'].checked,
      calls: _fetchCalls
  })));
""" % json.dumps(TON_ADDR))
check("адрес в поле — ИЗ ОТВЕТА СЕРВЕРА, а не из ответа кошелька",
      res["address"] == TON_ADDR)
check("подставленный адрес прогоняется через обычную проверку", res["validated"] >= 1)
check("клиенту сказано, что адрес подтверждён подписью",
      "подтверждён подписью" in res["msg"] and "valid" in res["cls"])
check("подключённый кошелёк — личный: memo не спрашиваем", res["noTag"] is True)
check("проверка идёт на сервер", "/api/tonconnect/verify" in res["calls"])

# Отказ сервера: никакой отметки «подтверждено», ручной ввод жив.
res = run_js("""
_els['currency'].value = 'TON';
_els['address'].value = 'НАБРАНО-РУКАМИ';
_fetchReply['/api/tonconnect/verify'] =
  { verified: false, address: null, message: 'Подпись не подтверждает владение адресом.' };
tcHandleWallet({ account: { address: '0:aaa' },
                 connectItems: { tonProof: { proof: { signature: 'x' } } } })
  .then(() => console.log(JSON.stringify({
      address: _els['address'].value,
      msg: _els['tc-msg'].textContent,
      cls: _els['tc-msg'].className,
      noTag: _els['no_tag'].checked
  })));
""")
check("сервер не подтвердил → поле адреса не трогаем",
      res["address"] == "НАБРАНО-РУКАМИ")
check("сервер не подтвердил → причина показана как ошибка",
      "не подтверждает" in res["msg"] and "invalid" in res["cls"])
check("сервер не подтвердил → клиента возвращают к ручному вводу",
      "вручную" in res["msg"])
check("сервер не подтвердил → за клиента ничего не отвечаем", res["noTag"] is False)

# Сервер сказал «подтверждено», но адреса не дал — верить нечему.
res = run_js("""
_els['currency'].value = 'TON';
_fetchReply['/api/tonconnect/verify'] = { verified: true, address: '', message: 'ок' };
tcHandleWallet({ account: { address: '0:aaa' },
                 connectItems: { tonProof: { proof: { signature: 'x' } } } })
  .then(() => console.log(JSON.stringify({
      address: _els['address'].value, cls: _els['tc-msg'].className })));
""")
check("«подтверждено» без адреса не подставляет ничего", res["address"] == "")
check("«подтверждено» без адреса — это отказ", "invalid" in res["cls"])

# Кошелёк подключился, но подписи не дал.
res = run_js("""
_els['currency'].value = 'TON';
tcHandleWallet({ account: { address: '0:aaa' }, connectItems: {} })
  .then(() => console.log(JSON.stringify({
      address: _els['address'].value, msg: _els['tc-msg'].textContent,
      calls: _fetchCalls })));
""")
check("кошелёк без подписи → на сервер не ходим", res["calls"] == [])
check("кошелёк без подписи → сказано ввести вручную", "вручную" in res["msg"])
check("кошелёк без подписи → поле адреса пустое", res["address"] == "")

# Сеть отвалилась на проверке.
res = run_js("""
_els['currency'].value = 'TON';
_els['address'].value = 'НАБРАНО-РУКАМИ';
_fetchReply['/api/tonconnect/verify'] = 'boom';
tcHandleWallet({ account: { address: '0:aaa' },
                 connectItems: { tonProof: { proof: { signature: 'x' } } } })
  .then(() => console.log(JSON.stringify({
      address: _els['address'].value, msg: _els['tc-msg'].textContent })));
""")
check("сбой сети не роняет шаг и не портит введённый адрес",
      res["address"] == "НАБРАНО-РУКАМИ" and "вручную" in res["msg"])

# Ответ сервера, из которого пришёл ЧУЖОЙ адрес, всё равно подставляется —
# это нормально: сервер и есть источник истины, он проверил подпись. Проверяем
# лишь, что фронт не берёт адрес из объекта кошелька.
res = run_js("""
_els['currency'].value = 'TON';
_fetchReply['/api/tonconnect/verify'] = { verified: true, address: %s };
tcHandleWallet({ account: { address: '0:deadbeef' },
                 connectItems: { tonProof: { proof: { signature: 'x' } } } })
  .then(() => console.log(JSON.stringify({ address: _els['address'].value })));
""" % json.dumps(OTHER_ADDR))
check("адрес кошелька из запроса игнорируется, берётся ответ сервера",
      res["address"] == OTHER_ADDR)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
