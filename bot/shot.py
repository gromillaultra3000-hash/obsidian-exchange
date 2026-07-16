#!/usr/bin/env python3
"""«Глаза» для ИИ-агентов: рендер ЖИВЫХ страниц проекта в PNG.

Позволяет Claude Code и Codex реально увидеть сайт/Mini App/кабинет так, как их
видит пользователь, а не только читать разметку. Использует playwright/chromium
(тот же, что и render_promo.py).

Запуск:
  /root/bot/venv/bin/python3 /root/bot/shot.py               # весь набор
  /root/bot/venv/bin/python3 /root/bot/shot.py URL [W H] OUT # одиночный кадр

Выход: /root/scratch_ux/shots/*.png  (потом открыть Read-ом / codex-ом)
"""
from __future__ import annotations
import sys
from pathlib import Path

OUT = Path("/root/scratch_ux/shots")
BASE = "http://127.0.0.1:5001"

# (url, viewport_w, viewport_h, full_page, имя файла)
SHOTS = [
    (f"{BASE}/",         1440, 900, True,  "site_home_desktop.png"),
    (f"{BASE}/",          390, 844, True,  "site_home_mobile.png"),
    (f"{BASE}/webapp",    390, 844, True,  "miniapp.png"),
    (f"{BASE}/faq",      1440, 900, False, "site_faq_desktop.png"),
    (f"{BASE}/register",  390, 844, False, "site_register_mobile.png"),
]


def _capture(browser, url, w, h, full, out):
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
    except Exception:
        page.goto(url, timeout=20000)
    page.wait_for_timeout(1200)  # анимации/шрифты/фон
    page.screenshot(path=str(out), full_page=full)
    page.close()
    return out.stat().st_size // 1024


def main(argv) -> int:
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    if len(argv) >= 2:  # одиночный режим: URL [W H] OUT
        url = argv[1]
        if len(argv) >= 5:
            w, h, out = int(argv[2]), int(argv[3]), OUT / argv[4]
        else:
            w, h, out = 1440, 900, OUT / (argv[2] if len(argv) >= 3 else "shot.png")
        shots = [(url, w, h, True, out.name)]
    else:
        shots = SHOTS
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        for url, w, h, full, name in shots:
            try:
                kb = _capture(browser, url, w, h, full, OUT / name)
                print(f"OK  {name:28s} {w}x{h}  {kb} KB  ← {url}")
            except Exception as exc:
                print(f"ERR {name:28s} {type(exc).__name__}: {exc}")
        browser.close()
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
