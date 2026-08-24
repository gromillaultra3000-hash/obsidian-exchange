#!/bin/bash
BOT_TOKEN=$(grep BOT_TOKEN /root/bot/.env | cut -d= -f2)
ADMIN_ID=$(grep ADMIN_ID /root/bot/.env | cut -d= -f2)
DB_PATH=$(grep DB_PATH /root/bot/.env | cut -d= -f2)

TODAY=$(date +%Y-%m-%d)
TOTAL=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM orders WHERE date(created_at)='$TODAY';")
VOLUME=$(sqlite3 $DB_PATH "SELECT COALESCE(SUM(rub_amount),0) FROM orders WHERE date(created_at)='$TODAY';")
SENT=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM orders WHERE date(created_at)='$TODAY' AND status='sent';")
PENDING=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM orders WHERE status='pending';")

MSG="📊 ObsidianExchange — статистика за $TODAY
🔹 Заявок сегодня: $TOTAL
🔹 Оборот: $VOLUME RUB
🔹 Успешных выплат: $SENT
🔹 Ожидают оплаты: $PENDING"

curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d chat_id="$ADMIN_ID" \
    -d text="$MSG" >/dev/null
