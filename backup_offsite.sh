#!/bin/bash
# Off-site шифрованный бэкап exchange.db (раз в день).
# Берёт свежий локальный бэкап, шифрует AES-256 и отправляет ВНЕ сервера:
#   1) Telegram-документом всем админам (облако Telegram = off-site, без доп. инфры);
#   2) опционально rsync на удалённый хост, если задан BACKUP_OFFSITE_RSYNC.
# Ключ шифрования: /root/.backup_key (root-only, НЕ в git). Восстановление:
#   openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/root/.backup_key \
#     -in exchange_YYYYMMDD.db.gz.enc | gunzip > restored.db
set -o pipefail

DB="/root/exchange.db"
BACKUP_DIR="/root/backups"
KEY="/root/.backup_key"
ENV="/root/bot/.env"
TS=$(date +%Y%m%d_%H%M%S)
TMP="$BACKUP_DIR/offsite_${TS}.db"
ENC="$BACKUP_DIR/exchange_${TS}.db.gz.enc"

mkdir -p "$BACKUP_DIR"

send_msg() {
    local BOT_TOKEN ADMIN
    BOT_TOKEN=$(grep '^BOT_TOKEN=' "$ENV" | cut -d= -f2)
    for ADMIN in $(grep -E '^ADMIN_ID(_2)?=' "$ENV" | cut -d= -f2); do
        [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN" ] && \
          curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
               -d "chat_id=${ADMIN}" -d "text=$1" >/dev/null 2>&1
    done
}

send_doc() {
    local BOT_TOKEN ADMIN
    BOT_TOKEN=$(grep '^BOT_TOKEN=' "$ENV" | cut -d= -f2)
    for ADMIN in $(grep -E '^ADMIN_ID(_2)?=' "$ENV" | cut -d= -f2); do
        [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN" ] && \
          curl -s -F "chat_id=${ADMIN}" \
               -F "document=@${1}" \
               -F "caption=🔐 Off-site бэкап БД $(date '+%Y-%m-%d %H:%M') (AES-256, ключ /root/.backup_key)" \
               "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" >/dev/null 2>&1
    done
}

if [ ! -f "$KEY" ]; then
    send_msg "❌ Off-site бэкап: нет ключа /root/.backup_key"; exit 1
fi

# консистентный снимок + проверка целостности
if ! sqlite3 "$DB" ".backup '$TMP'" 2>/dev/null; then
    send_msg "❌ Off-site бэкап: не удалось сделать снимок БД"; exit 1
fi
if ! sqlite3 "$TMP" "PRAGMA integrity_check;" 2>/dev/null | grep -q "^ok$"; then
    send_msg "❌ Off-site бэкап: integrity_check не пройден"; rm -f "$TMP"; exit 1
fi

# gzip + AES-256 (pbkdf2)
gzip -c "$TMP" | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$KEY" -out "$ENC"
RC=$?
rm -f "$TMP"
if [ $RC -ne 0 ] || [ ! -s "$ENC" ]; then
    send_msg "❌ Off-site бэкап: ошибка шифрования"; exit 1
fi

SIZE=$(du -sh "$ENC" | cut -f1)

# 1) Telegram off-site
send_doc "$ENC"

# 2) опциональный rsync (если задан BACKUP_OFFSITE_RSYNC=user@host:/path в bot/.env)
RSYNC_TARGET=$(grep '^BACKUP_OFFSITE_RSYNC=' "$ENV" 2>/dev/null | cut -d= -f2-)
if [ -n "$RSYNC_TARGET" ]; then
    rsync -az "$ENC" "$RSYNC_TARGET" 2>/dev/null && echo "[$(date)] rsync → $RSYNC_TARGET ok" \
        || send_msg "⚠️ Off-site бэкап: rsync на $RSYNC_TARGET не удался"
fi

# ротация зашифрованных копий (14 дней)
ls -t "$BACKUP_DIR"/exchange_*.db.gz.enc 2>/dev/null | tail -n +15 | xargs -r rm --

echo "[$(date)] Off-site backup OK: $ENC ($SIZE)"
