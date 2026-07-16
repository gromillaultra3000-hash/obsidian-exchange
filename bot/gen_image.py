#!/usr/bin/env python3
"""Дизайн-генератор изображений для ИИ-агентов (Claude Code + Codex).

Midjourney НЕ имеет официального API (только Discord) → используем OpenAI Images
API (gpt-image-1), та же экосистема, что ChatGPT/Codex. Fail-closed: без ключа
ничего не делает, честно сообщает.

⚠️ ChatGPT-подписка ≠ API-ключ. Нужен ключ с platform.openai.com (отдельный
биллинг). Положить в bot/.env как OPENAI_API_KEY=sk-...  ЛИБО экспортом в окружении.

Запуск:
  OPENAI_API_KEY=sk-... /root/bot/venv/bin/python3 /root/bot/gen_image.py \
      "obsidian purple crystal, dark premium fintech hero background, 3d, glow" \
      hero_bg.png 1536x1024

Модель по умолчанию gpt-image-1. Выход: /root/scratch_ux/gen/<name>.
Для точных UI-карточек/баннеров используйте render_promo.py (HTML→PNG) — он
пиксель-в-пиксель и в бренде; ИИ-генерация — для иллюстраций/фонов/арта.
"""
from __future__ import annotations
import base64
import os
import sys
from pathlib import Path

OUT = Path("/root/scratch_ux/gen")


def _load_env_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    # мягко подхватить из bot/.env, не тащя зависимостей
    envp = Path("/root/bot/.env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: gen_image.py \"<prompt>\" [out.png] [WxH]")
        return 2
    prompt = argv[1]
    out_name = argv[2] if len(argv) > 2 else "gen.png"
    size = argv[3] if len(argv) > 3 else "1024x1024"

    key = _load_env_key()
    if not key:
        print("FAIL-CLOSED: нет OPENAI_API_KEY (ChatGPT-подписка не подходит — нужен "
              "API-ключ с platform.openai.com). Положите в bot/.env: OPENAI_API_KEY=sk-...")
        return 1

    try:
        from openai import OpenAI  # pip install openai (в bot/venv)
    except ImportError:
        print("Нет пакета openai. Установить: /root/bot/venv/bin/pip install openai")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=key)
    try:
        resp = client.images.generate(model="gpt-image-1", prompt=prompt, size=size, n=1)
    except Exception as exc:
        print(f"Ошибка генерации: {type(exc).__name__}: {exc}")
        return 1

    b64 = resp.data[0].b64_json
    dst = OUT / out_name
    dst.write_bytes(base64.b64decode(b64))
    print(f"OK  {dst}  ({dst.stat().st_size // 1024} KB, {size})")
    print("Открыть Read-ом / codex exec -i для просмотра.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
