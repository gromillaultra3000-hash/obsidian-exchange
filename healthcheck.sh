#!/bin/bash
# Внешний сторож: жив ли процесс. Это единственная проверка, которую нельзя
# сделать изнутри самого сервиса — упавший процесс о себе не сообщит.
#
# ⚠️ Раньше здесь проверялся `pgrep -f app.py` — легаси-ретранслятор на порту
# 5000, который выключен с 19.07.2026 как источник потери сессий. Боевой
# сервис — relay-fastapi (:5001), и его сторож не смотрел вовсе. Плюс алерты
# всё равно не доходили из-за многострочного chat_id (см. lib_tg.sh).
#
# Троттлинг: одна и та же тревога не чаще раза в час — иначе крон (каждые 5
# минут) превратит её в 12 сообщений, и её перестанут читать.

source /root/lib_tg.sh

STATE_DIR=/run/obsidian-healthcheck
mkdir -p "$STATE_DIR"
THROTTLE_SEC=3600

alert_once() {           # alert_once <ключ> <текст>
    local key="$1" text="$2" f="$STATE_DIR/$1" now last
    now=$(date +%s)
    last=$(cat "$f" 2>/dev/null || echo 0)
    if [ $((now - last)) -ge "$THROTTLE_SEC" ]; then
        echo "$now" > "$f"
        tg_send "$text"
    fi
}

clear_alert() { rm -f "$STATE_DIR/$1"; }

# --- Бот ------------------------------------------------------------------
if pgrep -f "main_bot.py" > /dev/null; then
    clear_alert bot
else
    alert_once bot "🚨 ObsidianExchange: бот (exchange-bot) не запущен!"
fi

# --- Боевой сайт/API ------------------------------------------------------
if systemctl is-active --quiet relay-fastapi \
   && curl -s --max-time 8 -o /dev/null http://127.0.0.1:5001/api/system-status; then
    clear_alert relay
else
    alert_once relay "🚨 ObsidianExchange: relay-fastapi (:5001) не отвечает!"
fi

# --- Support-бот ----------------------------------------------------------
if systemctl is-active --quiet support-bot; then
    clear_alert support
else
    alert_once support "⚠️ ObsidianExchange: support-bot не запущен."
fi
