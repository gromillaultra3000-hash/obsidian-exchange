#!/usr/bin/env python3
"""Обещания клиенту совпадают с расчётом, а не просто «берутся из функции».

Мина в test_landmines.py проверяет ФОРМУ: что текст не набран руками. Форма
может быть верной, а число — нет: хелпер способен молча отдать пустоту, взять
чужую лестницу или потерять ступень. Здесь проверяется СОДЕРЖАНИЕ — что в
клиентском тексте стоят ровно те проценты и пороги, по которым считается
заявка и начисляется скидка.

Бот целиком не поднимается (aiogram, БД, сеть): чистые функции вырезаются из
исходника, как в test_bot_tag_answer.py.

Запуск: /root/bot/venv/bin/python3 tests/test_promise_texts.py
"""
import ast
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core.pricing import (COMMISSION_TIERS, VIP_TIERS, tiers_for_display,
                          vip_tier_for, vip_tiers_for_display)

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── ступени: витрина и расчёт ─────────────────────────────────────────
def test_display_matches_calculation():
    """Каждая ступень витрины подтверждается расчётом на её же границах."""
    tiers = tiers_for_display()
    from core.pricing import commission_percent
    ok = True
    for t in tiers:
        lo, hi, pct = t["from_rub"], t["to_rub"], t["percent"]
        if commission_percent(lo) != pct:
            ok = False
        if hi is not None and commission_percent(hi - 1) != pct:
            ok = False
        # Ровно на верхней границе действует уже СЛЕДУЮЩАЯ ступень — из-за
        # этого подписи «до 5 000 ₽» и были неправдой.
        if hi is not None and commission_percent(hi) == pct and hi != lo:
            ok = False
    check("витрина ступеней совпадает с расчётом на границах", ok)
    check("ступеней столько же, сколько в источнике",
          len(tiers) == len(COMMISSION_TIERS))
    check("подписи не обещают включительную верхнюю границу",
          not any(re.match(r"^до ", t["label"]) for t in tiers))


def test_vip_display_matches_accrual():
    """Пороги в тексте скидки — те же, по которым скидка начисляется."""
    ok = True
    for t in vip_tiers_for_display():
        name, disc = vip_tier_for(t["from_rub"])
        if name != t["name"] or abs(disc) != t["discount"]:
            ok = False
        below = vip_tier_for(t["from_rub"] - 1)
        if below[0] == t["name"]:
            ok = False          # порог обещан ниже, чем срабатывает
    check("пороги VIP в тексте совпадают с начислением", ok)
    check("Standard в витрине скидок не показывается",
          all(t["name"] != "Standard" for t in vip_tiers_for_display()))
    check("в витрине скидок все ступени с ненулевой скидкой",
          len(vip_tiers_for_display()) == len([1 for _, _, d in VIP_TIERS if d]))


# ── тексты бота ───────────────────────────────────────────────────────
SRC = open(os.path.join(ROOT, "bot", "main_bot.py"), encoding="utf-8").read()


def cut(names):
    """Вырезает функции из main_bot.py и исполняет их в изолированном модуле."""
    tree = ast.parse(SRC)
    want, order = set(names), []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in want:
            order.append(ast.get_source_segment(SRC, node))
    mod = types.ModuleType("bot_texts")
    mod.__dict__["logger"] = types.SimpleNamespace(
        error=lambda *a, **k: None, warning=lambda *a, **k: None,
        info=lambda *a, **k: None, debug=lambda *a, **k: None)
    mod.__dict__["_VIP_ICONS"] = {"Silver": "🥈", "Gold": "🥇", "Platinum": "💎"}
    exec("\n\n".join(order), mod.__dict__)
    return mod


BOT = cut(["tariff_lines", "vip_lines", "_vip_display", "_max_vip_discount"])


def test_bot_tariff_lines():
    text = BOT.tariff_lines()
    for t in tiers_for_display():
        check(f"в тексте бота есть ступень «{t['label']} → {t['percent']}%»",
              t["label"] in text and f"{t['percent']}%" in text)
    check("текст бота не содержит процентов, которых нет в расчёте",
          set(re.findall(r"(\d{1,2})%", text)) ==
          {str(t["percent"]) for t in tiers_for_display()})


def test_bot_vip_lines():
    text = BOT.vip_lines()
    for t in vip_tiers_for_display():
        check(f"в тексте бота есть ступень скидки {t['name']}",
              t["name"] in text and t["from_label"] in text
              and f"{t['discount']}%" in text)
    check("«до N%» в текстах — максимум из источника",
          BOT._max_vip_discount() == max(t["discount"]
                                         for t in vip_tiers_for_display()))


def test_bot_texts_fail_quiet():
    """Сбой источника не подставляет старые числа, а убирает обещание."""
    broken = cut(["tariff_lines", "vip_lines", "_vip_display", "_max_vip_discount"])
    # Прячем core.pricing от вырезанных функций: импорт внутри них упадёт.
    import builtins
    real_import = builtins.__import__

    def deny(name, *a, **k):
        if name == "core.pricing":
            raise ImportError("источник недоступен")
        return real_import(name, *a, **k)

    builtins.__import__ = deny
    try:
        check("сбой тарифов → пустая строка, а не устаревшая лестница",
              broken.tariff_lines() == "")
        check("сбой тарифов → виден заданный фолбэк",
              broken.tariff_lines(fallback="в калькуляторе") == "в калькуляторе")
        check("сбой VIP → пустая строка", broken.vip_lines() == "")
        check("сбой VIP → «до 0%», а не выдуманный максимум",
              broken._max_vip_discount() == 0)
    finally:
        builtins.__import__ = real_import


# ── шаблоны сайта ─────────────────────────────────────────────────────
def test_site_renders_tiers():
    """Страницы сайта отрисовывают ровно ступени из источника."""
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        print("… jinja2 нет — рендер страниц пропущен")
        return
    env = Environment(loader=FileSystemLoader(
        os.path.join(ROOT, "relay-fastapi", "templates")))
    ctx = dict(
        offered_currencies=("BTC", "LTC"), sell_currencies=("BTC",),
        swap_currencies=("BTC", "LTC", "USDT"),
        documented_currencies=("BTC", "LTC", "USDT"),
        commission_tiers=tiers_for_display(), vip_tiers=vip_tiers_for_display(),
        offerings_json="[]", min_amount=2000, max_amount=300000,
        bot_username="b", support_username="s", reviews_username="r",
        public_relay="", web_user=None, total_orders=0, success_rate=99.2,
        request=types.SimpleNamespace(url=types.SimpleNamespace(path="/")),
        rates={}, v5=False,
    )
    for page, needles in (
        ("rates.html", [t["label"] for t in tiers_for_display()]),
        ("faq.html", [t["from_label"] for t in vip_tiers_for_display()]),
        ("index.html", [f"{t['percent']}%" for t in tiers_for_display()]),
    ):
        try:
            html = env.get_template(page).render(**ctx)
        except Exception as e:
            check(f"{page} рендерится", False)
            print(f"    {type(e).__name__}: {e}")
            continue
        missing = [n for n in needles if n not in html]
        check(f"{page} показывает все ступени из источника", not missing)
        if missing:
            print(f"    нет в выводе: {missing}")

    # Пустой источник — страница не должна врать статикой
    ctx_empty = dict(ctx, commission_tiers=[], vip_tiers=[])
    html = env.get_template("rates.html").render(**ctx_empty)
    check("при пустом источнике на странице курсов нет процентов",
          not re.search(r"\d{1,2}%\s*</td>", html))


if __name__ == "__main__":
    test_display_matches_calculation()
    test_vip_display_matches_accrual()
    test_bot_tariff_lines()
    test_bot_vip_lines()
    test_bot_texts_fail_quiet()
    test_site_renders_tiers()
    print()
    if failures:
        print(f"❌ Провалено проверок: {len(failures)}")
        for f in failures:
            print("  •", f)
        sys.exit(1)
    print("✅ Обещания клиенту совпадают с расчётом на всех поверхностях.")
