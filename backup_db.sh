#!/bin/bash
BACKUP_DIR="/root/backups"
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M%S)
cp /root/exchange.db "$BACKUP_DIR/exchange_$DATE.db"
# Храним только последние 7 бэкапов
ls -t $BACKUP_DIR/exchange_*.db | tail -n +8 | xargs rm -f 2>/dev/null
echo "Бэкап создан: exchange_$DATE.db"
