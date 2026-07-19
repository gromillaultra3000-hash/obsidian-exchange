# core — общее ядро платформы

Единый дом для safety / intelligence / secrets, переиспользуемый обменником, ботом,
кошельком и (позже) сайтом/Mini App. Шаг 1 плана единой платформы
(см. `docs/ARCHITECTURE_UNIFIED.md`).

## Что здесь сейчас
- `secrets.py` — **канонический** детектор/редактор секретов (secret-guard). Новый код
  использует `from core import contains_secret, redact`.
- `__init__.py` — единый импорт intelligence: `provider_conversion`, `evidence_summary`,
  `provider_failure_patterns` (реэкспорт из `services/*`).
- `safety.py` — единый доступ к стражам выплат (`verify_payment_settled`,
  `check_payout_allowed` с fail-closed, `payout_circuit_status`).

## Статус миграции
Аддитивный фасад: реализации intelligence/safety пока в `relay/services/*`, старые
импорты не тронуты. По мере консолидации реализации переезжают в `core/`, а `services/*`
становятся тонкими шимами.

⚠️ Дубликат: `/root/support_bot/secret_guard.py` — копия для отдельного процесса
support-бота (нет /root/relay в path). Свести к `core.secrets` при миграции support-бота.
