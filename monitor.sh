#!/bin/bash
source /root/bot/.env
BOT_TOKEN=$(grep BOT_TOKEN /root/bot/.env | cut -d= -f2)
ADMIN_ID=$(grep ADMIN_ID /root/bot/.env | cut -d= -f2)
DB_PATH=$(grep DB_PATH /root/bot/.env | cut -d= -f2 | head -1)
TODAY=$(date +%Y-%m-%d)

# Объём за сегодня
VOL=$(sqlite3 $DB_PATH "SELECT COALESCE(SUM(rub_amount),0) FROM orders WHERE date(created_at)='$TODAY'")
# Успешных за сегодня
SENT=$(sqlite3 $DB_PATH "SELECT COUNT(*) FROM orders WHERE date(created_at)='$TODAY' AND status='sent'")
# Ошибок в логах за последний час
ERRS=$(journalctl -u exchange-bot --since "1 hour ago" | grep -ci "error\|exception\|traceback")

# Баланс кошелька через python (nowpay)
BALANCE=$(python3 -c "
import sys, os
sys.path.insert(0, '/root/payout')
from nowpay import get_balance
btc = get_balance('BTC')
ltc = get_balance('LTC')
print(f'BTC: {btc} | LTC: {ltc}')
" 2>/dev/null)

# Извлекаем числовые значения для проверки
BTC_BAL=$(echo $BALANCE | grep -oP 'BTC: \K[0-9.]+')
LTC_BAL=$(echo $BALANCE | grep -oP 'LTC: \K[0-9.]+')

# Алерт, если баланс BTC меньше 0.001 или LTC меньше 0.1
if [ -n "$BTC_BAL" ] && (( $(echo "$BTC_BAL < 0.001" | bc -l) )); then
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d chat_id="$ADMIN_ID" \
        -d text="🚨 Низкий баланс BTC: $BTC_BAL. Пополните кошелёк!" >/dev/null
fi
if [ -n "$LTC_BAL" ] && (( $(echo "$LTC_BAL < 0.1" | bc -l) )); then
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d chat_id="$ADMIN_ID" \
        -d text="🚨 Низкий баланс LTC: $LTC_BAL. Пополните кошелёк!" >/dev/null
fi

MSG="📊 Мониторинг ObsidianExchange за $TODAY
Объём: $VOL RUB
Успешных выплат: $SENT
Ошибок в логах (1ч): $ERRS
Баланс кошелька: $BALANCE"

curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d chat_id="$ADMIN_ID" \
    -d text="$MSG" >/dev/null
