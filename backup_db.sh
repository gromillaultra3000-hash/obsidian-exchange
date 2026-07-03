#!/bin/bash
# Авто-бэкап exchange.db каждые 5 дней — ротация 6 копий (30 дней покрытия)

DB_SRC="/root/exchange.db"
BACKUP_DIR="/root/backups"
MAX_BACKUPS=6

mkdir -p "$BACKUP_DIR"

FILENAME="exchange_$(date +%Y%m%d_%H%M%S).db"
DEST="$BACKUP_DIR/$FILENAME"

# sqlite3 .backup гарантирует консистентный снимок даже при активных записях
sqlite3 "$DB_SRC" ".backup '$DEST'"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$DEST" | cut -f1)
    echo "[$(date)] Backup OK: $DEST ($SIZE)"
    ls -t "$BACKUP_DIR"/exchange_*.db 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm --
else
    echo "[$(date)] ERROR: backup failed!" >&2
    exit 1
fi
