#!/usr/bin/env python3
"""Рендер анимированных HTML-макетов пака ObsidianExchange в статичные PNG.

Один кадр на карточку (анимации в Telegram всё равно уходят картинкой).
Захват через Playwright/Chromium с device_scale_factor=2 (чёткие 2x).
Небольшая пауза перед скриншотом — чтобы canvas-частицы/градиенты прорисовались.

⚠️ Анимации перед съёмкой ОСТАНАВЛИВАЮТСЯ на фиксированной фазе (FREEZE_MS).
Без этого кадр ловится в случайный момент: у карточек есть блоки, которые
циклически появляются и исчезают (комиссии, строка-переключатель), и они
могли попасть в кадр наполовину прозрачными или вовсе пустыми. Дефект при этом
выглядит как «дизайнер так задумал» — рендер отрабатывает без единой ошибки.

Перед публикацией пака полезно прогнать /root/scratch_ux/check_layout.py —
он ловит содержимое, обрезанное границами сцены.

Запуск:  /root/bot/venv/bin/python3 /root/bot/render_promo.py
Источник: /root/scratch_ux/obsidian_*.html  →  выход: /root/bot/images/
"""
from __future__ import annotations
import sys
from pathlib import Path

SRC = Path("/root/scratch_ux")
OUT = Path("/root/bot/images")

# Фаза, на которой замирают анимации. 2000 мс подобраны так, чтобы у всех
# циклических блоков в кадре был ПЕРВЫЙ слайд на полной непрозрачности.
FREEZE_MS = 2000

# (html-файл, размер сцены W, H, имя выходного PNG)
CARDS = [
    ("obsidian_bot_promo_card.html",   1080, 1080, "post_banner.png"),
    ("obsidian_forum_banner_main.html",1200,  300, "forum_banner.png"),
    ("obsidian_referral_card.html",    1080, 1080, "referral_card.png"),
    ("obsidian_voucher_card.html",     1080, 1080, "voucher_card.png"),
    ("obsidian_site_hero.html",        1536, 1024, "promo_banner.png"),
    ("obsidian_mini_app_concept.html",  430,  932, "miniapp_preview.png"),
]


def main() -> int:
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        for html, w, h, out in CARDS:
            src = SRC / html
            if not src.exists():
                print(f"SKIP {html} — нет файла"); continue
            page = browser.new_page(viewport={"width": w + 48, "height": h + 48},
                                    device_scale_factor=2)
            page.goto(src.as_uri())
            page.wait_for_timeout(1400)  # дать canvas/градиентам прорисоваться
            page.evaluate("()=>document.getAnimations().forEach(a=>a.pause())")
            page.evaluate(
                """(t)=>{document.getAnimations().forEach(a=>{try{a.currentTime=t}catch(e){}});
                         return new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}""",
                FREEZE_MS)
            dst = OUT / out
            # скриншот строго по элементу сцены (без полей body)
            scene = page.locator(".scene").first
            scene.screenshot(path=str(dst))
            page.close()
            kb = dst.stat().st_size // 1024
            print(f"OK  {out:22s} {w}x{h}@2x  {kb} KB")
            ok += 1
        browser.close()
    print(f"\nГотово: {ok}/{len(CARDS)} карточек → {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
