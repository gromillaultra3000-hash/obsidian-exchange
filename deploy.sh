#!/bin/bash
# Auto-deploy from GitHub — вызывается таймером obsidian-autodeploy (каждые 15 мин)
#
# ⚠️ Сервисы перезапускаются ТОЛЬКО когда код действительно изменился.
# До 27.07.2026 скрипт дёргал `systemctl restart relay-fastapi` безусловно —
# 96 рестартов в сутки на пустом месте. Последствия не косметические: рвались
# запросы клиентов в полёте (страница оплаты, Mini App), обнулялись кеши курсов
# и — главное — троттлинг алертов жил в памяти процесса, поэтому сигнал «деньги
# клиента не выданы» приходил админу каждые 15 минут и перестал читаться.
set -e
LOG="/var/log/obsidian-deploy.log"
STATE="/root/.deploy_state"   # рев, который РЕАЛЬНО раскатан на сервисы

cd /root

DEPLOYED="$(cat "$STATE" 2>/dev/null || true)"

# Токен НЕ хранится здесь: git берёт его из /root/.git-credentials (chmod 600)
# через credential.helper=store. Ротация — заменить одну строку в том файле.
git pull origin master >/dev/null 2>&1 || {
    echo "[$(date)] git pull FAILED" | tee -a "$LOG"; exit 1;
}
NEW_REV="$(git rev-parse HEAD)"

# Сверяем с РАСКАТАННЫМ, а не с «до pull»: если прошлый прогон подтянул код, но
# упал на проверках, следующий обязан попробовать снова, а не решить, что всё уже
# на сервисах.
if [ "$DEPLOYED" = "$NEW_REV" ] && [ "$1" != "--force" ]; then
    exit 0   # тихо: раскатывать нечего
fi

echo "[$(date)] Deploy ${DEPLOYED:-<неизвестно>} → $NEW_REV" | tee -a "$LOG"

# Что изменилось. Пустой/неизвестный STATE (первый прогон после обновления
# скрипта) → считаем изменившимся всё и перезапускаем оба сервиса.
if [ -n "$DEPLOYED" ] && git cat-file -e "${DEPLOYED}^{commit}" 2>/dev/null; then
    CHANGED="$(git diff --name-only "$DEPLOYED" "$NEW_REV")"
else
    CHANGED="ВСЁ"
fi

# Syntax check before restart
python3 -m py_compile relay-fastapi/main.py && echo "Syntax OK" || { echo "SYNTAX ERROR - aborting" | tee -a "$LOG"; exit 1; }

# Мины: дефекты, которые выглядят как рабочий код (дубли-тени, мёртвый конфиг,
# fail-open в стражах денег, экспирация мимо expires_at). Гейтим ПРОД, а не push:
# сюда код приезжает фактически, и здесь его ещё можно не запускать.
python3 /root/tests/test_landmines.py 2>&1 | tee -a "$LOG"
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "LANDMINE CHECK FAILED - деплой остановлен, сервисы не перезапущены" | tee -a "$LOG"
    exit 1
fi

# relay-fastapi: свой код + всё, что он импортирует из /root/relay
if echo "$CHANGED" | grep -qE '^(ВСЁ|relay-fastapi/|relay/)'; then
    systemctl restart relay-fastapi
    sleep 2
    systemctl is-active relay-fastapi && echo "relay-fastapi: OK" | tee -a "$LOG" \
        || echo "relay-fastapi: FAILED" | tee -a "$LOG"
fi

# Бот тянет из /root/relay пакеты core/wallet/services/providers — их правки для
# него такие же «свои». Диапазон берём раскатанный→новый, а не HEAD~1: одним pull
# приезжает несколько коммитов, и сравнение с одним предыдущим их пропускало
# (так уже терялись фиксы, которые «задеплоились, но не заработали»).
if echo "$CHANGED" | grep -qE '^(ВСЁ|bot/|relay/(core|wallet|services|providers)/)'; then
    systemctl restart exchange-bot
    sleep 2
    systemctl is-active exchange-bot && echo "exchange-bot: OK" | tee -a "$LOG" \
        || echo "exchange-bot: FAILED" | tee -a "$LOG"
fi

# Монитор — такой же долгоживущий процесс, импортирующий /root/relay, но до
# 05.08.2026 его здесь не было. Он проработал с 31.07 на коде, снятом с
# эксплуатации 03.08, и месяцами слал бы тревогу про Platega и GreenPay,
# которых в коде уже нет. Правило простое: кто держит наш код в памяти — тот
# в списке перезапуска, иначе он живёт в прошлом и спорит с остальными.
if echo "$CHANGED" | grep -qE '^(ВСЁ|monitoring/|relay/(core|wallet|services|providers)/)'; then
    systemctl restart obsidian-monitor
    sleep 2
    systemctl is-active obsidian-monitor && echo "obsidian-monitor: OK" | tee -a "$LOG" \
        || echo "obsidian-monitor: FAILED" | tee -a "$LOG"
fi

echo "$NEW_REV" > "$STATE"
echo "[$(date)] Deploy complete" | tee -a "$LOG"
