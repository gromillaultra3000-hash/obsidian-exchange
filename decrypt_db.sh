#!/bin/bash
ENCRYPTION_KEY=$(grep DB_ENCRYPTION_KEY /root/bot/.env | cut -d= -f2)
# Создаём временную расшифрованную копию
sqlcipher /root/exchange.db << SQL
PRAGMA key = '$ENCRYPTION_KEY';
ATTACH DATABASE '/tmp/exchange_plain.db' AS plain KEY '';
SELECT sqlcipher_export('plain');
DETACH DATABASE plain;
SQL
mv /tmp/exchange_plain.db /root/exchange_plain.db
chmod 600 /root/exchange_plain.db
echo "База расшифрована в /root/exchange_plain.db"
