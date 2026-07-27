#!/usr/bin/env python3
"""Проверка макетов пака на обрезку содержимого.

Зачем: у каждой карточки `.scene` имеет `overflow:hidden` и жёсткий размер.
Если содержимое не помещается, браузер молча срежет его — картинка
отрендерится без ошибок, и дефект видно только глазом. Так из баннера
пропали кнопка «Обменять» и целая карточка «Комиссия».

Проверяем две вещи:
  1. геометрия — блок вылезает за границы `.scene`;
  2. внутренняя обрезка — текст шире своего контейнера с overflow:hidden.

Запуск: /root/bot/venv/bin/python3 /root/scratch_ux/check_layout.py
Код возврата 1, если хоть что-то обрезано.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path("/root/scratch_ux")

# (html, ширина сцены, высота сцены) — как в bot/render_promo.py
CARDS = [
    ("obsidian_bot_promo_card.html", 1080, 1080),
    ("obsidian_forum_banner_main.html", 1200, 300),
    ("obsidian_referral_card.html", 1080, 1080),
    ("obsidian_voucher_card.html", 1080, 1080),
    ("obsidian_site_hero.html", 1536, 1024),
    ("obsidian_mini_app_concept.html", 430, 932),
]

# Фоновые слои занимают всю сцену намеренно и часто выходят за неё по замыслу
# (свечение, туман, скан-линия) — их обрезка дефектом не является.
IGNORE = {"noise", "mist", "grid", "hud", "frame", "scan", "content", "topbar",
          "scene", "crystal-aura"}

JS = r"""
(ignore) => {
  const scene = document.querySelector('.scene');
  const sr = scene.getBoundingClientRect();
  const res = {overflow: [], clipped: []};
  const skip = new Set(ignore);

  const named = el => (el.className && typeof el.className === 'string')
      ? el.className.split(/\s+/).filter(Boolean) : [];

  scene.querySelectorAll('*').forEach(el => {
    if (el.tagName === 'CANVAS' || el.tagName === 'SCRIPT') return;
    if (named(el).some(c => skip.has(c))) return;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    // элементы анимации в фазе «скрыт» лежат смещёнными — это не дефект
    if (parseFloat(st.opacity) < 0.02) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;

    const d = {b: +(r.bottom - sr.bottom).toFixed(1), t: +(sr.top - r.top).toFixed(1),
               l: +(sr.left - r.left).toFixed(1), rt: +(r.right - sr.right).toFixed(1)};
    const bad = [];
    if (d.b > 1) bad.push(`снизу на ${d.b}px`);
    if (d.t > 1) bad.push(`сверху на ${d.t}px`);
    if (d.l > 1) bad.push(`слева на ${d.l}px`);
    if (d.rt > 1) bad.push(`справа на ${d.rt}px`);
    if (bad.length) {
      res.overflow.push({sel: el.tagName.toLowerCase() + (named(el).length ? '.' + named(el).join('.') : ''),
                         text: (el.textContent || '').trim().slice(0, 46), why: bad.join(', ')});
    }

    // Внутреннюю обрезку меряем по ШИРИНЕ ТЕКСТА, а не по scrollWidth:
    // у чипов и кнопок есть декоративный блик (::after) со сдвигом transform,
    // и он раздувает scrollWidth, хотя ничего не режет.
    if (st.overflow !== 'visible' && st.overflowX !== 'visible') {
      // Сравниваем в абсолютных координатах: левая/правая граница текста против
      // внутренних границ элемента. clientWidth округляется до целых, из-за
      // чего у длинных строк набегала ложная «обрезка» в несколько пикселей.
      const er = el.getBoundingClientRect();
      const inL = er.left + parseFloat(st.borderLeftWidth) + parseFloat(st.paddingLeft);
      const inR = er.right - parseFloat(st.borderRightWidth) - parseFloat(st.paddingRight);
      // letter-spacing добавляет зазор ПОСЛЕ последней буквы: он входит в
      // измеренную ширину, но ничего не режет. Это допуск, а не дефект.
      const ls = parseFloat(st.letterSpacing) || 0;
      let ov = 0;
      for (const n of el.childNodes) {
        if (n.nodeType !== 3 || !n.nodeValue.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        const tr = rg.getBoundingClientRect();
        ov = Math.max(ov, (inL - tr.left), (tr.right - ls - inR));
      }
      ov = +ov.toFixed(1);
      if (ov > 1) {
        res.clipped.push({sel: el.tagName.toLowerCase() + (named(el).length ? '.' + named(el).join('.') : ''),
                          text: (el.textContent || '').trim().slice(0, 46), why: `текст шире контейнера на ${ov}px`});
      }
    }
  });
  return res;
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    problems = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        for html, w, h in CARDS:
            src = SRC / html
            if not src.exists():
                print(f"SKIP {html} — нет файла")
                continue
            page = browser.new_page(viewport={"width": w + 48, "height": h + 48},
                                    device_scale_factor=1)
            page.goto(src.as_uri())
            page.wait_for_timeout(1200)
            # анимации замораживаем в той же фазе, что и рендер картинок,
            # иначе замер поймает случайный кадр
            page.evaluate("()=>document.getAnimations().forEach(a=>a.pause())")
            page.evaluate("(t)=>document.getAnimations().forEach(a=>{try{a.currentTime=t}catch(e){}})", 2000)
            res = page.evaluate(JS, sorted(IGNORE))
            page.close()

            items = res["overflow"] + res["clipped"]
            if not items:
                print(f"OK   {html}")
                continue
            problems += len(items)
            print(f"БИТО {html} — {len(items)}:")
            for it in items:
                txt = f' «{it["text"]}»' if it["text"] else ""
                print(f'       {it["sel"]}{txt} — обрезан {it["why"]}')
        browser.close()

    print(f"\nИтого проблем: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
