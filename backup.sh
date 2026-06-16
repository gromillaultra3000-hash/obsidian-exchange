#!/bin/bash
# Ежечасный бэкап exchange.db с проверкой целостности и офлайн-копией

DB="/root/exchange.db"
BACKUP_DIR="/root/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/exchange_$TIMESTAMP.db"

mkdir -p "$BACKUP_DIR"

send_telegram() {
    BOT_TOKEN=$(grep '^BOT_TOKEN=' /root/bot/.env | cut -d= -f2)
    ADMIN_ID=$(grep '^ADMIN_ID=' /root/bot/.env | cut -d= -f2)
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${ADMIN_ID}" \
            -d "text=$1" > /dev/null 2>&1
    fi
}

# Создаём бэкап через SQLite online backup API (безопасно при WAL)
if ! sqlite3 "$DB" ".backup $BACKUP_FILE" 2>/dev/null; then
    send_telegram "❌ Ошибка создания бэкапа exchange.db!"
    exit 1
fi

# Проверяем целостность
if ! sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>/dev/null | grep -q "^ok$"; then
    send_telegram "❌ Бэкап не прошёл integrity_check — удалён!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

gzip -f "$BACKUP_FILE"
GZIP_FILE="${BACKUP_FILE}.gz"

# Копия на второй диск / удалённый сервер (если настроен)
# Вариант 1: rsync на другой сервер (настроить SSH-ключ и адрес)
# REMOTE_BACKUP_HOST="user@backup-server.example.com"
# REMOTE_BACKUP_DIR="/backups/obsidian/"
# if [ -n "$REMOTE_BACKUP_HOST" ]; then
#     rsync -az "$GZIP_FILE" "${REMOTE_BACKUP_HOST}:${REMOTE_BACKUP_DIR}" 2>/dev/null \
#         && send_telegram "☁️ Бэкап отправлен на удалённый сервер" \
#         || send_telegram "⚠️ Не удалось отправить бэкап на удалённый сервер"
# fi

# Вариант 2: копия в другую директорию (например, примонтированный NFS/S3FS)
OFFSITE_DIR="/mnt/backup"
if [ -d "$OFFSITE_DIR" ]; then
    cp "$GZIP_FILE" "$OFFSITE_DIR/" 2>/dev/null \
        && send_telegram "☁️ Офсайт-копия создана: ${OFFSITE_DIR}" \
        || send_telegram "⚠️ Не удалось скопировать бэкап в ${OFFSITE_DIR}"
fi

# Удаляем локальные архивы старше 7 дней (хватает 168 штук)
find "$BACKUP_DIR" -name "*.gz" -mtime +7 -delete

# Раз в сутки — краткий отчёт (только при запуске в 06:00)
HOUR=$(date +%H)
if [ "$HOUR" = "06" ]; then
    COUNT=$(ls "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)
    SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    DB_SIZE=$(du -sh "$DB" 2>/dev/null | cut -f1)
    send_telegram "📊 Ежедневный отчёт бэкапов:
• Архивов: ${COUNT}
• Размер папки: ${SIZE}
• Размер БД: ${DB_SIZE}"
fi
