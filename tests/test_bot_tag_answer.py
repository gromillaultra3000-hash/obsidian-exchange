#!/usr/bin/env python3
"""Молчание про тег — не согласие: второстепенные потоки бота.

Основной поток заявки спрашивает тег отдельным шагом с кнопкой «тега нет».
Подарок, лимитный ордер, DCA и своп принимают адрес одной строкой — и молча
считали отсутствие тега за «его и не надо». Для личного кошелька это верно, для
биржевого нет: перевод без тега сеть подтверждает, а получателю не зачисляет, и
вернуть его нечем. Нашёл это внешний ревьюер, не свой критик.

Бот целиком здесь не поднимается (aiogram, БД, сеть): проверяем ЧИСТЫЕ функции
решения, вырезая их из исходника. Так тест ловит правило, а не окружение.

Запуск: /root/bot/venv/bin/python3 tests/test_bot_tag_answer.py
"""
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


SRC = open(os.path.join(ROOT, "bot", "main_bot.py"), encoding="utf-8").read()
HELPERS = ["_tag_name", "_tag_kind", "_tag_separator", "_address_carries_tag",
           "_canonical_address", "_parse_tag_input", "_strip_no_tag_marker",
           "_split_entered_destination", "_tag_answer_missing",
           "_swap_tag_unsupported", "_tag_required_text"]


def cut(name):
    m = re.search(r"^def %s\(" % re.escape(name), SRC, re.M)
    if not m:
        raise SystemExit(f"в боте нет {name}() — тест устарел, поправьте его")
    return SRC[m.start():SRC.index("\ndef ", m.end())]


class _Log:
    def exception(self, *a, **k):
        pass


BOT = types.ModuleType("bot_helpers")
BOT.__dict__["logger"] = _Log()
exec("\n".join(cut(n) for n in HELPERS), BOT.__dict__)
G = BOT.__dict__

TON = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI"
XRP = "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh"
BTC = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def decide(currency, raw):
    """Повторяет решение потока: (спросить_про_тег, адрес, тег, отказ_разбора)."""
    addr, no_tag = G["_strip_no_tag_marker"](currency, raw)
    clean, tag = G["_split_entered_destination"](currency, addr)
    if clean is None:
        return True, None, None, True
    return G["_tag_answer_missing"](currency, clean, tag, no_tag), clean, tag, False


for cur, addr in (("TON", TON), ("XRP", XRP)):
    ask, _a, _t, _bad = decide(cur, addr)
    check(f"{cur}: голый адрес → у клиента спрашивают про тег", ask)
    sep = G["_tag_separator"](cur)

    glued = f"{addr}{sep}{'order-42' if cur == 'TON' else '101'}"
    ask, clean, tag, _bad = decide(cur, glued)
    check(f"{cur}: тег указан → не переспрашиваем", not ask)
    # Тег может уехать двумя путями: отдельным значением либо внутри строки,
    # которую ядро понимает целиком. Оба годятся — не годится «потерялся».
    check(f"{cur}: тег разобран и не потерян",
          tag is not None or G["_address_carries_tag"](cur, clean))

    ask, clean, tag, _bad = decide(cur, f"{addr}{sep}безтега")
    check(f"{cur}: явный отказ принят как ответ", not ask)
    check(f"{cur}: явный отказ не превращается в тег «безтега»", tag is None)
    check(f"{cur}: адрес после отказа остался целым", clean == addr)

    ask, _c, _t, bad = decide(cur, f"{addr}{sep}")
    check(f"{cur}: пустой тег после разделителя — отказ, а не «тега нет»", bad or ask)

    stored = G["_canonical_address"](cur, addr, "m1" if cur == "TON" else 7)
    check(f"{cur}: тег доезжает до формы хранения", bool(stored) and stored != addr)

check("XRP: нечисловой тег — отказ разбора", decide("XRP", f"{XRP}:абв")[3])
check("XRP: X-адрес несёт тег сам — не переспрашиваем", not decide("XRP", "X7TYt4nPauxSispXtYbecsfAHuA4ciuXLfdxguAicta1ViD")[0])
check("TON: сырой адрес с двоеточием не режется по нему",
      decide("TON", "0:83dff552e6372da472fcbcc8c45ebcc669170255862da3b1d49f86e903a0f31a")[1]
      == "0:83dff552e6372da472fcbcc8c45ebcc669170255862da3b1d49f86e903a0f31a")
check("BTC: у валюты без тега ничего не спрашивают", not decide("BTC", BTC)[0])
check("BTC: маркер отказа не уродует адрес без тега",
      G["_strip_no_tag_marker"]("BTC", BTC)[0] == BTC)

# Своп: тег передать внешнему сервису нечем, поэтому адрес с тегом — отказ,
# а не «отправим как есть». Иначе перевод ляжет на общий счёт биржи.
X_ADDR = "X7TYt4nPauxSispXtYbecsfAHuA4ciuXLfdxguAicta1ViD"
check("своп: TON-адрес с memo не принимается",
      G["_swap_tag_unsupported"]("TON", TON, "order-42"))
check("своп: склейка «адрес#memo» не принимается",
      G["_swap_tag_unsupported"]("TON", f"{TON}#order-42", None))
check("своп: XRP X-адрес (тег внутри) не принимается",
      G["_swap_tag_unsupported"]("XRP", X_ADDR, None))
check("своп: XRP с тегом не принимается",
      G["_swap_tag_unsupported"]("XRP", XRP, 101))
check("своп: личный кошелёк без тега проходит",
      not G["_swap_tag_unsupported"]("TON", TON, None)
      and not G["_swap_tag_unsupported"]("XRP", XRP, None))
check("своп: у валюты без тега ограничения нет",
      not G["_swap_tag_unsupported"]("BTC", BTC, None))

txt = G["_tag_required_text"]("TON")
check("текст вопроса называет ОБА варианта ответа",
      "биржу" in txt and "личный кошелёк" in txt and "безтега" in txt)
check("текст вопроса объясняет цену ошибки", "не зачислятся" in txt)

# Каждая точка ввода адреса обязана дойти до решения — иначе поток снова начнёт
# принимать молчание. Список потоков собираем из исходника, а не руками.
entries = re.findall(r"@router\.message\((\w+)\.address\)\s*\nasync def (\w+)", SRC)
check(f"точки ввода адреса найдены ({len(entries)})", len(entries) >= 4)
for state, fn in entries:
    m = re.search(r"async def %s\(.*?(?=\n@router|\nasync def |\ndef )" % re.escape(fn),
                  SRC, re.S)
    body = m.group(0) if m else ""
    ok = "_tag_answer_missing" in body or "dest_tag" in body
    check(f"{fn} ({state}) получает ответ про тег", ok)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
