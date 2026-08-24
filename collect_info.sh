#!/bin/bash
OUTPUT="/tmp/bot_info_$(date +%Y%m%d_%H%M).txt"

{
    echo "========================================="
    echo "СИСТЕМНАЯ ИНФОРМАЦИЯ"
    echo "========================================="
    echo "Дата: $(date)"
    echo "ОС: $(uname -a)"
    echo "Python: $(python3 --version 2>&1)"
    echo "Свободно RAM: $(free -h | grep Mem | awk '{print $4}')"
    echo "Свободно места: $(df -h / | tail -1 | awk '{print $4}')"

    echo -e "\n========================================="
    echo "ФАЙЛЫ ПРОЕКТА"
    echo "========================================="
    ls -la /root/bot/

    echo -e "\n========================================="
    echo "СОДЕРЖИМОЕ main_bot.py"
    echo "========================================="
    cat /root/bot/main_bot.py 2>/dev/null

    echo -e "\n\n========================================="
    echo "СОДЕРЖИМОЕ .env (ТОКЕН СКРЫТ)"
    echo "========================================="
    cat /root/bot/.env 2>/dev/null | sed 's/BOT_TOKEN=.*/BOT_TOKEN=HIDDEN/'

    echo -e "\n\n========================================="
    echo "ЛОГИ (последние 100 строк)"
    echo "========================================="
    tail -n 100 /root/bot/bot.log 2>/dev/null

    echo -e "\n\n========================================="
    echo "ОШИБКИ (последние 50 строк)"
    echo "========================================="
    tail -n 50 /root/bot/errors.log 2>/dev/null

    echo -e "\n\n========================================="
    echo "ЗАПУЩЕННЫЕ ПРОЦЕССЫ"
    echo "========================================="
    ps aux | grep -E "python|bot" | grep -v grep

    echo -e "\n\n========================================="
    echo "СТРУКТУРА БАЗЫ ДАННЫХ"
    echo "========================================="
    if [ -f /root/exchange.db ]; then
        sqlite3 /root/exchange.db ".schema" 2>/dev/null
        echo -e "\nКоличество заказов:"
        sqlite3 /root/exchange.db "SELECT COUNT(*) FROM orders;" 2>/dev/null
        echo -e "\nПоследние 5 заказов:"
        sqlite3 /root/exchange.db "SELECT * FROM orders ORDER BY order_id DESC LIMIT 5;" 2>/dev/null
    fi

    echo -e "\n\n========================================="
    echo "CROUTAB"
    echo "========================================="
    crontab -l 2>/dev/null

    echo -e "\n\n========================================="
    echo "СЕТЕВЫЕ ПОРТЫ"
    echo "========================================="
    netstat -tlnp 2>/dev/null | grep -E "5000|9898"

} > "$OUTPUT"

# Маскируем чувствительные данные
sed -i 's/[0-9]*:A[A-Za-z0-9_-]*/BOT_TOKEN_HIDDEN/g' "$OUTPUT"
sed -i 's/7154652873/ADMIN_ID_HIDDEN/g' "$OUTPUT"
sed -i 's/185\.236\.228\.19/IP_HIDDEN/g' "$OUTPUT"

echo "Информация собрана в $OUTPUT"
echo "Размер файла: $(wc -c < $OUTPUT) байт"
echo ""
echo "Для просмотра: cat $OUTPUT"
