# Выбор первого read-only CEX connector

Снимок решения: 2026-08-10. Рассматриваются только официальные API-контракты;
реальные ключи и private API calls в этом этапе не используются.

## Обязательный gate KAIROS

Подключение допускается только при свежем authenticated evidence, связанном с
точным аккаунтом и credential reference:

- `read=true`;
- `trade=false`;
- `withdraw=false`;
- `internal_transfer=false`;
- неизвестное, устаревшее или противоречивое значение означает `BLOCKED`;
- успешный `fetch_balance` сам по себе не является permission proof;
- проверка не создаёт пробный order/transfer/withdraw;
- drift немедленно останавливает синхронизацию, а последний balance snapshot
  остаётся явно `STALE`, не превращаясь в ноль.

## Сравнительная матрица

| CEX | Authenticated self-inspection | Read-only доказуем | Transfer/withdraw видимы | Решение |
|---|---|---|---|---|
| Bybit | `GET /v5/user/query-api` | Явный `readOnly=1` | Детальные `Wallet`, `Spot`, derivatives permissions и IP binding | Первый adapter |
| OKX | Account configuration возвращает `perm` | Требуем точное `read_only` | `trade` включает funding transfer; `withdraw` отдельный | Второй кандидат |
| KuCoin | `GET /api/ua/v1/user/api-key` | `General` документирован как read-only | Ответ перечисляет `Spot`, `Withdrawal`, `InnerTransfer` и другие permissions | Второй кандидат после Bybit |

Официальные источники:

- [Bybit: Get API Key Information](https://bybit-exchange.github.io/docs/v5/user/apikey-info)
- [OKX: API permissions and account configuration](https://www.okx.com/docs-v5/)
- [KuCoin: Get Apikey Info](https://www.kucoin.com/docs-new/rest/ua/get-apikey-info)
- [KuCoin: permission definitions](https://www.kucoin.com/docs-new?lang=en_US)

## Решение

Первым реализуется Bybit, потому что один authenticated endpoint возвращает
глобальный read-only bit, детальные классы permissions, account identity и IP
binding. Это позволяет доказать запреты без попытки выполнить опасную операцию.

Выбор не разрешает подключение production credentials. Перед этим необходимы:

1. перевести Relay с root на отдельного service user и ограничить write paths;
2. внутренний credential-ingress, который сам строит source-scoped refs;
3. периодический Bybit drift transport и bounded balance snapshot — реализованы
   и развёрнуты keyless; production credential по-прежнему отсутствует;
4. synthetic/testnet acceptance, затем отдельное одобрение production key.

Owner-isolated store, targeted vault deletion, crash-safe `REVOKING→REVOKED`,
revision CAS и 15-minute freshness gate уже реализованы внутренне. Они не
экспонируются HTTP до появления server-derived principal. Provider-specific
Bybit parser и его malformed/unknown permission tests также готовы.
Ed25519 Relay→KAIROS identity, server-derived principal, exact read scope и
persistent replay protection также развёрнуты.

Legacy `/api/exchanges/save` и `/api/exchanges/test` остаются закрыты: они были
глобальными, передавали credentials в process environment/engine и принимали
balance read за достаточное доказательство permissions.
