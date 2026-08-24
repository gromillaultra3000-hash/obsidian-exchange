#!/bin/bash
# Общий помощник для shell-сторожей: аккуратно достать ключи из bot/.env и
# отправить сообщение всем админам.
#
# ⚠️ Зачем отдельный файл. Скрипты доставали значения так:
#     ADMIN_ID=$(grep ADMIN_ID /root/bot/.env | cut -d= -f2)
# `grep ADMIN_ID` ловит и ADMIN_ID, и ADMIN_ID_2 → в переменной оказывались ДВЕ
# строки, а Telegram ждёт одно число. С 08.07.2026 (когда завели второго админа)
# ни одна тревога «бот упал» и ни один ночной отчёт НЕ доходили — молча, потому
# что вывод curl уходил в /dev/null. Сторож, который сам сломан и об этом не
# сообщает, хуже отсутствующего: он создаёт ложное чувство защиты.

ENV_FILE="${ENV_FILE:-/root/bot/.env}"

# Точное совпадение ключа: ^KEY= ... и только первое вхождение.
env_get() {
    sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | head -1 | tr -d '"'"'"'\r'
}

TG_TOKEN="$(env_get BOT_TOKEN)"

# Все админы: ADMIN_ID + ADMIN_ID_2 (если задан)
tg_admins() {
    local a b
    a="$(env_get ADMIN_ID)"; b="$(env_get ADMIN_ID_2)"
    [ -n "$a" ] && echo "$a"
    [ -n "$b" ] && [ "$b" != "$a" ] && echo "$b"
}

# tg_send "текст" — вернёт 0, только если Telegram принял хотя бы одну доставку.
tg_send() {
    local text="$1" ok=1 code
    [ -z "$TG_TOKEN" ] && { echo "tg_send: BOT_TOKEN не найден в $ENV_FILE" >&2; return 1; }
    while read -r chat; do
        [ -z "$chat" ] && continue
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
            -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
            --data-urlencode "chat_id=$chat" \
            --data-urlencode "text=$text")
        if [ "$code" = "200" ]; then
            ok=0
        else
            # Молчаливый сбой доставки — это и есть та самая беда. В лог.
            echo "$(date -Is) tg_send: chat=$chat HTTP $code" >> /root/watchdog.log
        fi
    done < <(tg_admins)
    return $ok
}
