#!/usr/bin/env python3
"""HTML-анимация → бесшовный анимированный GIF.

Наивный способ (скриншоты «на бегу» с паузами) даёт неровные интервалы: браузер
не гарантирует, что между кадрами прошло ровно dt, и GIF дёргается. Здесь кадры
детерминированные: все CSS-анимации ставятся на паузу и перематываются через
Web Animations API (document.getAnimations() → currentTime), то есть кадр t —
это точный слепок сцены в момент t, независимо от скорости рендера.

Бесшовность петли обеспечивает НЕ этот скрипт, а исходник: все периоды анимаций
должны быть делителями длительности петли (см. banner_gif_src.html), иначе кадр
t=T не совпадёт с t=0 и на стыке будет рывок.

Запуск:
  render_gif.py <src.html> <out.gif> [--dur 16] [--fps 12] [--w 1200] [--h 300]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def capture_frames(src: Path, out_dir: Path, dur: float, fps: int, w: int, h: int) -> int:
    from playwright.sync_api import sync_playwright

    n = int(round(dur * fps))
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu",
                                          "--force-color-profile=srgb",
                                          "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": w + 40, "height": h + 40},
                                device_scale_factor=1)
        page.goto(src.resolve().as_uri())
        page.wait_for_timeout(1200)  # шрифты + первый layout

        # Всё на паузу: дальше время двигаем только мы.
        page.evaluate("document.getAnimations().forEach(a => a.pause())")

        el = page.locator(".scene").first
        for i in range(n):
            t = (i / fps) * 1000.0
            # Перемотать время И ДОЖДАТЬСЯ, пока композитор перерисует слои.
            # Без ожидания снимок ловит момент до перерастеризации слоёв с 3D-
            # трансформами / mix-blend-mode / blur: два снимка ОДНОГО t давали
            # расхождение до 132/255, кадры шумели случайным образом, а GIF из-за
            # этого не жался (8 МБ). Анимации на паузе — ожидание время не двигает.
            page.evaluate("""(t) => {
                document.getAnimations().forEach(a => { a.currentTime = t; });
                return new Promise(r => requestAnimationFrame(
                    () => requestAnimationFrame(r)));
            }""", t)
            el.screenshot(path=str(out_dir / f"f{i:04d}.png"))
        browser.close()
    return n


def build_gif(frames: Path, out: Path, fps: int, colors: int, dither: str) -> None:
    """Двухпроходный ffmpeg: своя палитра на ролик даёт заметно лучший результат
    на тёмных градиентах, чем дефолтная 256-цветная кубическая."""
    palette = frames / "palette.png"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps), "-i", str(frames / "f%04d.png"),
        "-vf", f"palettegen=max_colors={colors}:stats_mode=diff",
        str(palette),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps), "-i", str(frames / "f%04d.png"), "-i", str(palette),
        "-lavfi", f"paletteuse=dither={dither}:diff_mode=rectangle",
        "-loop", "0", str(out),
    ], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--dur", type=float, default=16.0)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--w", type=int, default=1200)
    ap.add_argument("--h", type=int, default=300)
    ap.add_argument("--colors", type=int, default=128)
    ap.add_argument("--dither", default="bayer:bayer_scale=3")
    ap.add_argument("--keep", action="store_true", help="не удалять кадры")
    a = ap.parse_args()

    src, out = Path(a.src), Path(a.out)
    if not src.exists():
        print(f"нет файла: {src}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="gifframes_"))
    try:
        n = capture_frames(src, tmp, a.dur, a.fps, a.w, a.h)
        print(f"кадров снято: {n}  ({a.dur}s @ {a.fps}fps, {a.w}x{a.h})")
        build_gif(tmp, out, a.fps, a.colors, a.dither)
        kb = out.stat().st_size // 1024
        print(f"GIF: {out}  {kb} KB  ({kb/1024:.2f} МБ)")
        if a.keep:
            keep = out.parent / (out.stem + "_frames")
            shutil.rmtree(keep, ignore_errors=True)
            shutil.copytree(tmp, keep)
            print(f"кадры: {keep}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
