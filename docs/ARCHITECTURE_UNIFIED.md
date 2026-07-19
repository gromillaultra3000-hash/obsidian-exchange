# ObsidianExchange — единая платформа (план объединения)

Черновик архитектуры: обменник + горячий кошелёк + общее ядро + сайт + Mini App
в одну структуру. Составлен Codex (read-only анализ репозитория), проверен по коду.
Статус: план, не реализация. Миграция — поэтапная, без простоя прода.

## Целевая структура (монорепо)

```
apps/            api (FastAPI), bot (aiogram), site, miniapp   — только поверхности
packages/
  core/          outcomes · evidence · safety · secrets        — общее ядро
  exchange/      orders · payments · routing · rates · risk
  wallet/        domain(Balance,TransferIntent,TxStatus) · tron · evm · xrp · signer
migrations/  tests/{unit,integration,e2e,reconciliation}/  deploy/{systemd,nginx,docker}/
data/            # ВНЕ git: БД, vault, журналы
```

Перенос текущего кода:
- relay-fastapi/main.py, auth.py, templates → apps/api + apps/site
- bot/main_bot.py → apps/bot (убрать из бота расчёты и отправку денег → через API)
- relay/miniapp.html, webapp.html → apps/miniapp
- relay/services/{payment_service,smart_router,conversion_intel,evidence} → packages/exchange + core
- relay/wallet/tron_wallet.py → packages/wallet/tron (подпись/broadcast — только payout-worker)
- exchange.db остаётся единственной prod-БД; дубликаты (bot/exchange.db) не использовать

## Общее ядро (core) — что выделяем из Lumi/Kairos + текущего
- **core/outcomes** — модели outcome/score (LUMI outcome_learning/core.py) → к record_outcome() smart_router + conversion_intel
- **core/evidence** — единый EvidenceRecord (webhook / live-status провайдера / blockchain receipt / reconciliation). Уже начато: relay/services/evidence.py
- **core/safety** — policy ALLOW|HOLD|MANUAL|FREEZE + лимиты (LUMI policy_engine) ∪ реальные payout_guard/payout_circuit
- **core/secrets** — vault + redaction + audit (Kairos secret_vault + LUMI redaction) ∪ наш support_bot/secret_guard. Приватный ключ НИКОГДА не выдаётся API/боту

## Кошелёк как источник резервов и выплат
Доступный резерв ≠ сырой баланс:
`available = confirmed_onchain − reserved_for_orders − pending_broadcasts − fee_buffer − safety_buffer`
Таблицу `reserves` (ручная витрина) заменить проекцией `reserve_snapshots`; ручное — только доп. cap.

Контур выплаты (fail-closed):
1. В одной транзакции: `payout_intent` с уникальным order_id + резерв средств
2. Worker: live-settlement (payout_guard) + policy + адрес/сеть/лимиты + свежесть RPC + fee buffer
3. Одноразовый **persisted** preview с хэшем параметров (сейчас previews в памяти — теряются при рестарте)
4. Атомарный флаг `broadcasting` ДО отправки; после — сохранить txid. Повтор задания сверяет hash/nonce, не подписывает второй перевод
5. `submitted` ≠ выплата; только reconciliation после подтверждений → `confirmed/sent`
6. Любая ошибка RPC/vault/evidence/reconciliation → HOLD/FREEZE, НИКОГДА ALLOW

## Найденные дефекты (проверены по коду)
- 🔴 **fail-open**: bot/main_bot.py:6235 при исключении circuit-breaker → `{"action":"ok"}` (сломанный страж разрешает выплату); payout_circuit=None (6163) пропускает проверку. → task #12
- **деньги во float**: orders/payout_queue/reserves REAL → minor units/Decimal. → task #13
- **previews в памяти** + нет идемпотентности sign/broadcast/txid. → task #14
- несколько физических exchange.db; SQLite lock/concurrency (долгосрочно → PostgreSQL)
- один hot key в процессе: компрометация bot/API не должна давать signer (отдельный unix-user/сервис, лимиты)
- TRC-20: наличие USDT ≠ возможность выплаты (нужен буфер TRX/energy)

## Миграция без простоя
1. Backup exchange.db+WAL, characterization-тесты (webhook/state machine/router/guard)
2. Монорепо копированием кода; systemd/nginx entrypoints не менять
3. Core в **shadow-режиме**: пишем evidence/outcomes, сравниваем новые safety-решения со старыми, на выплаты не влияем
4. Миграции: payout_intents, fund_reservations, wallet_transactions, evidence, reserve_snapshots + idempotency-ограничения; старое читаем
5. Wallet/reconciliation **read-only**: сверка on-chain USDT/TRX с ledger; API резервов на новую проекцию — после серии совпавших сверок
6. payout-worker: dry-run → canary (малые USDT-TRC20); старый payout — fallback, но 1 активный исполнитель на order
7. Бот → API-команды, убрать прямую запись в БД и прямой payout; затем site/Mini App за тот же API
8. Стабилизация → отключить старый контур, архивировать дубликаты, позже SQLite → PostgreSQL

## Правило
Outcome-learning НЕ трогает policy/лимиты напрямую — только рекомендует; применение versioned/audited/с одобрением владельца. (Совпадает с текущим advisory-подходом conversion_intel.)
