#!/bin/bash
# Watchdog VPN (Xray Reality, порт 8443). Запуск из cron каждые 2 мин.
# Проверяет НАСТОЯЩЕЕ здоровье: Reality-инбаунд обязан отвечать валидным TLS-
# хендшейком, маскируясь под www.nvidia.com. «Процесс жив» недостаточно — xray
# может висеть с открытым портом, но не проксировать. Две неудачи подряд → рестарт
# + алерт в Telegram (с троттлингом, чтобы не спамить).

PORT=8443
SNI=www.nvidia.com
CERT_MATCH=nvidia
LOG=/root/watchdog.log
STATE=/run/vpn_watchdog.fail        # счётчик неудач подряд
ALERT_STAMP=/run/vpn_watchdog.alert  # троттлинг алертов (1/час)
FAIL_THRESHOLD=2

log(){ echo "$(date '+%F %T'): $*" >> "$LOG"; }

tg_alert(){
  # не чаще раза в час
  if [ -f "$ALERT_STAMP" ] && [ $(( $(date +%s) - $(stat -c %Y "$ALERT_STAMP") )) -lt 3600 ]; then
    return
  fi
  local token id
  token=$(grep -E '^BOT_TOKEN=' /root/bot/.env | cut -d= -f2- | tr -d '"'"'"' \r')
  [ -z "$token" ] && return
  for id in $(grep -E '^ADMIN_ID(_2)?=' /root/bot/.env | cut -d= -f2- | tr -d '"'"'"' \r'); do
    curl -s --max-time 10 "https://api.telegram.org/bot${token}/sendMessage" \
      -d chat_id="$id" -d text="$1" >/dev/null 2>&1
  done
  touch "$ALERT_STAMP"
}

# --- проверка здоровья: валидный TLS-хендшейк с сертификатом ---
healthy=0
if timeout 8 openssl s_client -connect 127.0.0.1:${PORT} -servername ${SNI} </dev/null 2>/dev/null \
     | openssl x509 -noout -subject 2>/dev/null | grep -qi "$CERT_MATCH"; then
  healthy=1
fi

if [ "$healthy" = 1 ]; then
  rm -f "$STATE"
  exit 0
fi

# --- неудача: копим счётчик ---
fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
log "health FAIL (${fails}/${FAIL_THRESHOLD}): порт ${PORT} не отдал валидный TLS"

if [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
  log "перезапуск xray"
  systemctl restart xray
  sleep 4
  if timeout 8 openssl s_client -connect 127.0.0.1:${PORT} -servername ${SNI} </dev/null 2>/dev/null \
       | openssl x509 -noout -subject 2>/dev/null | grep -qi "$CERT_MATCH"; then
    log "xray восстановлен после рестарта"
    tg_alert "🟢 VPN: Xray завис/упал и был автоматически перезапущен — сейчас работает."
  else
    log "xray НЕ восстановился после рестарта!"
    tg_alert "🔴 VPN: Xray упал и НЕ поднялся после автоперезапуска. Нужна ручная проверка: systemctl status xray; journalctl -u xray -n50"
  fi
  rm -f "$STATE"
fi
