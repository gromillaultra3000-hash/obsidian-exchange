# Единая экосистема — канонический маршрут

Статус: утверждён владельцем 2026-08-10. Этот документ задаёт продуктовый
маршрут. `roadmap_ecosystem.md` остаётся подробным журналом выполненных
итераций, а `ARCHITECTURE_UNIFIED.md` — ранним архитектурным черновиком.

## Цель

Один понятный интерфейс управления криптоактивами, который объединяет:

- некастодиальный кошелёк и внешний портфель пользователя;
- приватный non-KYC обмен через ObsidianExchange;
- верифицированные/KYC-биржи пользователя через KAIROS;
- LUMI как общий advisory/risk/policy слой;
- будущее нативное приложение для локального хранения и использования ключей.

Единый продукт не означает один процесс или один уровень доверия. Денежные,
торговые, аналитические и пользовательские компоненты изолируются и общаются
через узкие версионированные контракты.

## Роли компонентов

### ObsidianExchange

Рабочая приватная полоса RUB↔crypto без KYC. Владеет заявками, оплатами,
маршрутизацией провайдеров, payout intents, reconciliation и доказательствами
исполнения. Не получает ключи пользовательских кошельков или CEX-аккаунтов.

### Wallet

Главная пользовательская оболочка: портфель, подтверждённые адреса, история,
получение, обмен и запросы на подпись. Серверный Wallet хранит только публичные
адреса, доказательства владения, метаданные и намерения. Seed/private key не
попадает в HTML/JS Mini App, backend, Telegram bot, LUMI или KAIROS.

### KAIROS

Шлюз к внешним CEX и исполнитель разрешённых торговых намерений. KYC и custody
остаются у выбранной биржи. Первый production-контракт — read-only. Будущие
торговые ключи обязаны иметь trade/read permissions без withdrawal/transfer.
KAIROS не подписывает on-chain выплаты ObsidianExchange.

### LUMI

Advisory/risk слой: нормализует evidence, выявляет конфликтующие сигналы,
оценивает риск и возвращает ALLOW/HOLD/MANUAL/FREEZE или более строгий вердикт.
LUMI не хранит деньги, не подписывает операции, не повышает разрешения и не
может ослабить hard gate. Недоступность LUMI не создаёт разрешение.

### Native Wallet App

Будущий единственный наш клиент, которому разрешено локально создавать и
хранить пользовательские ключи: Secure Enclave/Android Keystore, биометрическое
подтверждение, резервное восстановление и подписанные store-релизы. Web/Mini App
может только запросить подпись через ограниченный native bridge.

## Две рыночные полосы

| Полоса | Исполнитель | Identity/KYC | Custody | Текущий статус |
|---|---|---|---|---|
| Приватный обмен | ObsidianExchange | Без KYC | Только операционный payout-контур | Работает |
| Проверенные биржи | Внешняя CEX через KAIROS | Выполняет CEX | Остаётся у CEX | Public quotes; аккаунты planned |

Интерфейс всегда показывает, где находятся средства, кто проверяет личность и
кто исполняет действие. Балансы разных custody-доменов можно суммировать в
портфель, но нельзя представлять единым серверным балансом.

## Непересекаемые границы безопасности

1. Клиентские seed/private keys никогда не поступают на сервер.
2. On-chain signer ObsidianExchange остаётся отдельным least-privilege worker.
3. CEX withdrawal и internal transfer запрещены техническими permissions и
   проверяются при подключении и периодически после него.
4. Любое денежное или торговое действие начинается с persisted intent,
   idempotency key, immutable parameters и audit correlation id.
5. Preview/quote не является исполнением; submitted не является confirmed.
6. Неизвестное состояние, конфликт evidence или потеря связи дают HOLD/MANUAL,
   а не автоматический retry.
7. AI/advisory не меняет hard limits, ACL или policy без версионированного и
   аудируемого одобрения владельца.
8. Read-only интеграция предшествует shadow/dry-run, затем canary и только после
   измеримой приёмки — ограниченному live.
9. Каждый внешний компонент получает отдельные credentials, network policy,
   timeout/circuit breaker, bounded payload и журнал без секретов.
10. Production не загружает исполняемый код с CDN и не исполняет непроверенные
    скрипты из форумов, Tor или случайных репозиториев.

## Этапы

### E0 — фундамент и инвентаризация (текущий)

Уже выполнено: PostgreSQL cutover, repository boundaries, payout intents,
изолированный signer, outbox/reconciliation, многоуровневая авторизация,
кошелёк/портфель и публичный market gateway KAIROS.

Осталось:

- описать текущие API/data contracts Wallet↔Exchange↔KAIROS↔LUMI;
- составить реестр данных, секретов, владельцев и trust boundaries;
- снять честный feature/status inventory на всех шести поверхностях
  (Telegram bot, site, Mini App, admin, API, native);
- определить SLO, метрики и аварийные runbooks для будущих CEX-коннекторов.

SLO, allowlisted privacy-safe metrics, alert thresholds and fail-closed
incident procedures are frozen in `docs/cex-readonly-operations.md`. They are
design/readiness requirements only; no connector credential or runtime metric
pipeline is enabled by this document.

E0.3/064A refreshed evidence (2026-08-18): an exact secret-free production
observation found 94 jobs (81 SENT, 13 SENDING, 11 stale) with no invalid
state/kind/lifecycle/active-recipient shape. The same exported read-only MVCC
snapshot restored into a distinct network-none/read-only-root/tmpfs PG17
container; all 54 table fingerprints and all 13 bounded catalog-v2 sections
matched, then the archive/manifests/container/tmpfs were removed. A new
unambiguous `ACCEPT_BOUNDED_EVIDENCE_ONLY` candidate binds those hashes while
preserving the v1 input and restrictive owner deferral immutably. Evidence:
`docs/e0-3-bot-b5-3-064a-production-source-refresh.v2.json`; candidate:
`docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json`. Result remains
`BLOCKED_OWNER`: freshness only invalidates, 064B and every production effect
remain prohibited, and this exact new candidate needs a new authenticated
accountable-owner accept-or-re-defer decision plus applicable independent
reviewer acceptance. Next: obtain those decisions inside the 24-hour source
window or refresh again; the 13 SENDING rows require separate 064D disposition.

The v2 offline handoff now fail-closed validates that exact candidate schema,
evidence-only label, restrictive authority and source-window issuance before it
can build a statement. Candidate keys and a synthetic signature flow still have
no production trust. Evidence:
`docs/e0-3-bot-b5-3-064a-v2-offline-handoff.v1.json`. The next canonical item
does not change: obtain the real authenticated owner/reviewer decision over the
exact candidate digest before expiry, or refresh and issue a new candidate.

Owner re-deferral (2026-08-18): the exact v2 candidate digest is now preserved
under a new restrictive deferral. Evidence:
`docs/e0-3-bot-b5-3-064a-owner-deferral.v2.json`. This is not evidence
acceptance and grants no 064B/064D, production, deploy, restart, cutover,
delivery or retry authority. E0.3 remains the first unmet `BLOCKED_OWNER` gate;
13 SENDING rows (11 stale) remain unchanged. The allowed safe route is
`E0/E0.4/POST_25_CLOSURE_RECONCILIATION`: rescan the complete deployed/generated
route, startup/import-writer, worker/service and UI/bot-consumer universe
read-only. The earlier 25-family classification does not prove completeness.

Post-25 closure reconciliation (2026-08-18): read-only enumeration observed
346 inferred FastAPI route objects, 29 generated Laravel routes, 13 enabled
Nginx locations, active and dormant service/timer entrypoints, startup/import
writers and UI/bot consumers. The 25-family matrix is not complete. Material
omissions are `RATE_LOCKS`, `DEPLOYMENT_RELEASE_AUTOMATION`,
`EDITORIAL_NEWS_DELIVERY`, `TELEGRAM_CHANNEL_POST_PROCESSING` and
`LEGACY_PAYMENT_EDGE_UPSTREAM`; public trust/legal content and generated
framework routes also need explicit mapping decisions. Evidence:
`docs/e0-4-post-25-closure-reconciliation.v1.json`. E0.4 remains
`IN_PROGRESS`. Next: classify `RATE_LOCKS` across all six surfaces and verify
quote, fee, expiry, persistence and money authority without invoking writers.

RATE_LOCKS evidence (2026-08-18): Telegram alone implements a durable paid
15-minute rate promise; all six surfaces are classified. Acceptance is
`PARTIAL_NOT_ACCEPTED`. The advertised 100 RUB fee is never deducted or
accounted, stale/static fallback may become a guarantee without provenance,
callbacks freely renew it, DB consumption trusts caller-computed quote vectors,
and concurrent first insert can leave multiple active locks. Owner/currency/
expiry filtering and atomic single-use order consumption are positive controls.
Evidence: `docs/e0-4-rate-locks-runtime-observation.v1.json`. Next: classify
`DEPLOYMENT_RELEASE_AUTOMATION` read-only, including source trust, credentials,
checks, restart authority, audit, rollback and recovery.

DEPLOYMENT_RELEASE_AUTOMATION evidence (2026-08-18): the enabled 15-minute
timer runs an untracked root script against mutable unsigned `master` and a
heavily dirty `/root` checkout. Acceptance is `PARTIAL_NOT_ACCEPTED`. Effective
Relay/bot/monitor units execute `/opt/obsidian-exchange`, but the controller
only pulls/tests `/root` and performs no artifact promotion, so it can restart
unchanged binaries and record a false deployed revision. Health failure is also
swallowed before state is written successful. Provenance, approvals, complete
preflight, runtime-byte binding, readiness, rollback/recovery, hardening and
operator UX are absent. Evidence:
`docs/e0-4-deployment-release-automation-runtime-observation.v1.json`. Next:
classify `EDITORIAL_NEWS_DELIVERY` read-only across identity, provenance,
delivery idempotency, credentials, consent, retention and operator authority.

E0.4 reconciliation evidence (2026-08-18): the prior thirteen-family
six-surface matrix is explicitly bounded, not comprehensive. A read-only scan
of five hash-bound deployed application entrypoints found twelve material
unclassified families, led by the broad LUMI control plane and KAIROS trading
controls, then swaps, account/auth/profile, provider payments, payout/
reconciliation, wallet actions, public market information, engagement,
operations, Relay AI and KAIROS exchange discovery. The exact generated
route/handler/worker universe is not yet available, so completeness and
acceptance remain false and E0.4 stays `IN_PROGRESS`. Evidence:
`docs/e0-4-deployed-route-feature-reconciliation.v1.json`. Next: classify the
security-critical `LUMI_CONTROL_PLANE` across all six surfaces and verify its
authority boundary without invoking mutations.

LUMI control-plane evidence (2026-08-18): a no-import AST inventory of the
hash-bound deployed application records 203 mounted routes from 28 routers.
The loopback process contains genuine host-file apply/rollback, vault lifecycle
and mutable policy/action/project state. Its public security status was
`protected` but `configured:false`: restart loses the in-memory administrator
password and the first loopback caller can claim public setup. One bearer has
the complete control plane, while apply/test/approval identifiers are checked
only for presence. This exceeds LUMI's advisory-only trust role despite no
observed money/ACL writer. All six surfaces are classified; acceptance remains
`PARTIAL_NOT_ACCEPTED`. Evidence:
`docs/e0-4-lumi-control-plane-runtime-observation.v1.json`. Next: classify
`KAIROS_AUTONOMOUS_TRADE_CONTROL` and verify its execution authority read-only.

KAIROS autonomous trade-control evidence (2026-08-18): the active non-root
loopback service exposes start/stop/status/chat/committee/limit controls behind
one operator bearer. Its mounted trade route always returns 409, and every
worker/chat execution path reaches an unconditional `HOLD` before the retained
legacy CCXT `create_order` implementation; the older direct-execution router is
not mounted. No active money writer is therefore reachable from the observed
entrypoint. Acceptance remains `PARTIAL_NOT_ACCEPTED`: the same bearer can
change live flags and start the worker, LUMI is advisory rather than a veto,
and no persisted immutable intent, idempotent claim, durable pre-submit attempt
or ambiguous-submit recovery exists. Evidence:
`docs/e0-4-kairos-autonomous-trade-control-runtime-observation.v1.json`. Next:
classify `SWAPS` across all six surfaces and verify its customer and money
authority read-only.

SWAPS evidence (2026-08-18): deployed Telegram and authenticated-site flows
create real SwapUZ orders, while Mini App only advertises the feature and the
operator resource is read-only. Acceptance is `PARTIAL_NOT_ACCEPTED`. Both
customer flows submit to the provider before a durable local intent/attempt;
ambiguous submit has no reconciliation-before-retry. The public bearer status
GET exposes addresses and mutates local state. SwapUZ errors/unknown states can
regress `finished`, after which the bot can re-enter `finished` and repeat the
non-idempotent referral credit. A checkout-only fail-closed transition guard
and regression candidate exists, but production remains vulnerable until a
separately controlled rollout and verification. Evidence:
`docs/e0-4-swaps-runtime-observation.v1.json`. Next: classify
`ACCOUNT_AUTH_PROFILE` across all six surfaces and verify authentication,
recovery and authorization authority read-only.

ACCOUNT_AUTH_PROFILE evidence (2026-08-18): deployed site registration/login,
30-day cookie sessions, optional TOTP, password/profile mutation, Telegram
binding, Mini App initData and separate Laravel admin auth are classified on
all six surfaces. Bcrypt, secure cookie flags, CSRF on profile mutations,
Telegram HMAC/freshness and Nginx login/register throttles are present.
Acceptance remains `PARTIAL_NOT_ACCEPTED`: Telegram binding is a state-changing
GET without CSRF/state/fresh step-up; password/TOTP changes do not revoke old
sessions; raw session/CSRF tokens and customer TOTP secrets are database
material; second-step TOTP is replayable; verified email, reset/recovery,
unlink, revoke-all and a canonical merge/unmerge state machine are absent.
Evidence: `docs/e0-4-account-auth-profile-runtime-observation.v1.json`. Next:
classify `PAYMENT_PROVIDER_LIFECYCLE` and verify callback, payment-truth and
money authority read-only.

PAYMENT_PROVIDER_LIFECYCLE evidence (2026-08-18): Telegram, site and Mini App
create live external-provider invoices, while Relay owns the local
`pending -> paid` truth used by payout. Callback secrets and transactional CAS
are positive controls, but acceptance is `PARTIAL_NOT_ACCEPTED`: live submit
precedes any durable provider attempt and ambiguous failures are retried;
callbacks are not bound to an exact persisted invoice, amount and currency;
the unauthenticated legacy numeric `/pay/{order_id}` route can redirect to the
high-entropy payment-session bearer and disclose requisites/order facts; raw
callback payload logging and fragmented polling/manual recovery remain.
Evidence: `docs/e0-4-payment-provider-lifecycle-runtime-observation.v1.json`.
Next: classify `PAYOUT_SETTLEMENT_RECONCILIATION` and verify payout truth,
custody and reconciliation authority read-only.

PAYOUT_SETTLEMENT_RECONCILIATION evidence (2026-08-18): a canonical branch
persists immutable payout intents before a separate server hot-wallet signer,
holds ambiguous signer failures in review and transactionally reconciles a
succeeded intent with order status, accounting and an outbox. Acceptance is
still `PARTIAL_NOT_ACCEPTED`: Telegram, Relay web-admin API and Laravel retain
format-only TXID completion bypasses; signer-ledger absence/path durability is
not proven; submitted transactions become `sent` without finality; reserve
accounting excludes in-flight obligations and can fail open; stale processing,
ambiguous notification delivery and the overlapping legacy notifier lack one
safe recovery state machine. Evidence:
`docs/e0-4-payout-settlement-reconciliation-runtime-observation.v1.json`.
Next: classify `WALLET_RECEIVE_TRANSFER` and verify receive, transfer-request,
external signing and broadcast authority read-only.

WALLET_RECEIVE_TRANSFER evidence (2026-08-18): Mini App and Relay expose TON
receive, free-transfer and sell-payment request flows while the customer's
external TON Connect wallet retains the key, confirmation, signature and
broadcast authority. Receive uses a stored verified public address and sell
drafts bind owner/order/address/amount server-side. Acceptance remains
`PARTIAL_NOT_ACCEPTED`: failed intent persistence still returns a signable
draft; requests lack immutable identity/idempotency/single-use state; free
transfers have no durable lifecycle; `send-signed` is unbound and can report
false success; current wallet account/content approval receipts, expiry,
recovery and non-TON parity are absent. Evidence:
`docs/e0-4-wallet-receive-transfer-runtime-observation.v1.json`. Next:
classify `PUBLIC_MARKET_INFORMATION` and verify pricing, provenance, freshness
and read-only authority.

PUBLIC_MARKET_INFORMATION evidence (2026-08-18): public site/API, Telegram and
Mini App expose indicative RUB market data, but the same fallback-capable,
unversioned price helpers also feed order calculations and automated limit
triggers. Acceptance remains `PARTIAL_NOT_ACCEPTED`: static fallback prices can
reach money decisions; source age/fallback/confidence are erased and current
response time masquerades as observation time; sources are sequential rather
than quorum-checked; Mini App direct CoinGecko display diverges from backend
calculator semantics; no operator price-health surface exists. Evidence:
`docs/e0-4-public-market-information-runtime-observation.v1.json`. Next:
classify `CUSTOMER_ENGAGEMENT` and verify consent, delivery, retention and
non-custodial authority.

CUSTOMER_ENGAGEMENT evidence (2026-08-18): Telegram implements rate alerts,
reviews, promos, VIP/referral presentation, direct campaigns and durable
one-shot notification jobs; site/Mini App expose partial projections. Acceptance
remains `PARTIAL_NOT_ACCEPTED`: marketing defaults on without a consent ledger
or usable global opt-out; several broadcast/recall/win-back audiences bypass
the stored preference; direct campaigns have no durable recipient lifecycle;
ambiguous jobs lack recovery; win-back bearers are not recipient-bound; review
publication consent, promo bounds, loyalty idempotency and retention/erasure are
unaccepted. Evidence:
`docs/e0-4-customer-engagement-runtime-observation.v1.json`. That slice has
since completed; the current route is `AI_ASSISTANT`.

OPERATIONS_MONITORING evidence (2026-08-18): active standalone and embedded
checks, public status and operator risk views exist, but observer errors can
produce false green; alert delivery has no durable incident/ack/escalation
lifecycle; public readiness overstates one-provider health; dead-man, general
SLO/error budgets, telemetry retention and recurring restore proof are absent;
the standalone monitor runs as root with an overbroad environment. Acceptance
is `PARTIAL_NOT_ACCEPTED`. Effectful dispute, payout, routing and deployment
watchers remain owned by their existing control families. Evidence:
`docs/e0-4-operations-monitoring-runtime-observation.v1.json`. That slice has
since completed; current route is `KAIROS_EXCHANGE_DISCOVERY`.

AI_ASSISTANT evidence (2026-08-18): Mini App exposes a single-turn FAQ assistant
through public Relay `/api/ai-ask` and loopback Ollama. The inspected path has
no tools, customer/order retrieval, persistence, signing or money action, and
renders output as text. Acceptance remains `PARTIAL_NOT_ACCEPTED`: public
inference lacks bounded admission/concurrency, hard-coded financial facts
contradict deployed policy, advisory and sensitive-data boundaries are only
prompt instructions, privacy copy overclaims, raw errors and brittle streaming
remain, and model provenance/readiness/evals are unproved. KAIROS/LUMI control
and advisory paths are explicitly not accepted by this family. Evidence:
`docs/e0-4-ai-assistant-runtime-observation.v1.json`. That slice has since
completed; current route returns to the first unmet criterion, `E0.3`.

KAIROS_EXCHANGE_DISCOVERY evidence (2026-08-18): bearer-protected operator
routes and SPA locally register exchange names and persist review drafts. This
is an effectful catalog writer, not external discovery; it accepts no keys and
does not activate connectors or trades. Acceptance is `PARTIAL_NOT_ACCEPTED`:
hard-coded URLs and CCXT labels have no versioned provenance, READ_ONLY currently
overstates proof and dormant READY logic would overstate it if re-enabled; JSON persistence lacks locking/CAS/corruption
quarantine, names can collide after lossy slugging, and no immutable approval,
revision, retention or recovery lifecycle exists. All 25 currently enumerated
families are classified, but empty bounded omissions do not accept E0.4 or E0.
No post-expansion closure rescan of the full deployed/generated route,
startup/import-writer, worker/service and UI/bot-consumer universe has been
performed, so material omission absence is not proved. Evidence:
`docs/e0-4-kairos-exchange-discovery-runtime-observation.v1.json`. Canonical
route returns to `E0.3`, the first unmet E0 criterion; a future safe keyless
E0.4 resumption starts with post-25 closure reconciliation.

Gate E0: нет неразмеченного компонента в критическом пути; документация и
production сходятся; каждый секрет и денежный writer имеет одного владельца.

### E1 — единый read-only портфель

Статус 2026-08-11: keyless поверхность завершена и production readiness gate
даёт `GO` для frozen `connector-list.v1`, `connector-events.v1` и
`unified-portfolio.v1`. Connect остаётся отключён, production connector store
отсутствует. Полный Gate E1 не закрыт до отдельного явного решения владельца о
вводе одного ограниченного testnet read-only credential и проверки реального
permission/balance/drift цикла; это не блокирует keyless проектирование E2.

- единая модель account/source/asset/network/custody;
- внешние подтверждённые кошельки и история ObsidianExchange;
- CEX connector contract: capabilities, permissions, balances, positions,
  freshness, rate-limit and degraded state;
- KAIROS подключает один CEX в read-only режиме без передачи данных в LUMI;
- UI явно разделяет Wallet, ObsidianExchange и CEX custody;
- revoke/disconnect удаляет доступ, но сохраняет минимальный audit trail.

Gate E1: withdrawal невозможен; чужой аккаунт/адрес недоступен; stale/error не
становится нулём; три поверхности показывают одинаковые нормализованные данные;
полный disconnect проверен E2E.

### E2 — наблюдение и risk intelligence

E0.4 inventory evidence (2026-08-18): production has a loopback
KAIROS→LUMI generic `/conflict/resolve` bridge, separate from the frozen shadow
wire below. It records but does not gate KAIROS execution, so LUMI currently has
no money/ACL authority and also supplies no accepted veto. The live bridge lacks
the frozen request bounds, replay/freshness, signed response receipt and strict
failure-to-`HOLD`; generic LUMI may emit misleading `actionAllowed:true`.
Classification remains `PARTIAL_NOT_ACCEPTED`; see
`docs/e0-4-lumi-advisory-runtime-observation.v1.json`.

Статус 2026-08-11: keyless foundation продолжен. Чистые frozen
`evidence-record.v1` и `decision-envelope.v1` уже задают минимизированные
scalar facts и монотонный порядок `ALLOW < HOLD < MANUAL < FREEZE`; LUMI
timeout/error/malformed нормализуются минимум в `HOLD`. Append-only
`shadow-decision-record.v1` связывает записи SHA-256 цепочкой, а
`shadow-replay.v1` детерминированно проверяет всю историю до append/replay.
Для журнала выделен service-owned `0700` путь, зафиксирована консервативная
400-дневная retention/двухкопийная backup/restore policy и установлен ежедневный
read-only `shadow-operator-signal.v1`. Отсутствующий до producer журнал честно
показывается как пустой genesis и не создаётся probe. Контракты и журнал пока не
подключены к runtime bridge или исполнению. Rotation сохраняет глобальные
sequence/hash через hash-chained generation checkpoints; два backup bundle
проверяются по digest и replay, а restore rehearsal ограничен guarded temporary
target. Hermetic continuity/backup/restore/tamper tests пройдены. Две локальные
`0700` backup-зоны, first-record path trigger и daily timer развёрнуты. Readiness
честно остаётся `producerReady:false`: обе зоны находятся
на одном `/dev/sda1`, поэтому это operational redundancy, не независимые copies.
Синтетический service-UID drill доказал rotation → two bundles → restore replay;
production journal и backup-зоны остались пустыми.
Узкий Relay→KAIROS `shadow-submission.v1` boundary также развёрнут, но с обоих
концов явно выключен. KAIROS требует Ed25519 scope `shadow:write`, replay guard,
feature flag и разные filesystem device IDs backup-зон; Relay при flag=0 не
читает signing key и не делает network call. Даже synthetic ALLOW возвращает
только `actionAllowed:false`. Runtime producer/task и LUMI endpoint отсутствуют.
Frozen `shadow-trigger-catalog.v1` ограничивает будущий producer пятью типами
наблюдений, точными fact keys и UTC sampling buckets; observation ID детерминирован
для retry/idempotency. Daily read-only verifier теперь выдаёт zero-filled
`shadow-metrics.v1` только со счётчиками signal/freshness/verdict/divergence;
неизвестный signal fail-closed, facts/IDs не публикуются.
Frozen `shadow-alert-policy.v1` задаёт 5-минутные окна и точные пороги для
divergence/latency/stale/permission/rate-limit. Escalation немедленная, clear
требует два строго смежных healthy windows; gap/replay запрещены. Даже CRITICAL
projection остаётся `actionAllowed:false`; evaluator не подключён к runtime.
`shadow-alarm-replay.v1` детерминированно раскладывает verified `recordedAt` по
5-минутным окнам, явно заполняет gaps нулями и одинаково воспроизводится целиком
или последовательными ≤7-дневными chunks. Latency/age/retry — только frozen
buckets, не raw values. Replay hermetic, non-persistent и non-executing.
Read-only operator CLI теперь выполняет full-chain verification до range filter,
поэтому tamper за пределами выбранного окна тоже даёт `NO_GO`. Результат и все
ошибки — только JSON stdout с exit 0/1/2; output file/network/state отсутствуют.
Frozen `shadow-advisory-request/response.v1` связывает privacy-minimized request
и LUMI advisory opaque hash ID. Pure dispatcher имеет injected transport и
deadline 750 ms; timeout/error/malformed → HOLD, а hard MANUAL/FREEZE никогда не
смягчаются. Даже ALLOW/ALLOW имеет `executionEffect:NONE/actionAllowed:false`.
Pure LUMI adapter независимо перепроверяет hashes и точный пятисигнальный
каталог с bounded integer/boolean/enum facts, затем применяет только
детерминированные tightening rules. Неизвестные сигналы, type coercion и raw
latency fail-closed. Endpoint/token/network/model/state/runtime wiring
отсутствуют.
Dormant `AtomicReplayStore` оборачивает тот же ledger в exclusive `flock` и
`0600` temp → fsync → atomic replace → directory fsync. Symlink/permissive/
corrupt/partial/oversized state fail-closed. Fault before replace сохраняет
старый snapshot, uncertain fault после replace оставляет валидный commit;
межпроцессные гонки не теряют updates и принимают один nonce ровно один раз.
Production path/state/unit/caller не созданы.
Frozen `shadow-public-keyring.v1` ограничен восемью content-hashed Ed25519
public keys и статусами ACTIVE/RETIRING/REVOKED. Rotation даёт старому ключу
только явный inclusive overlap 0..300 секунд, новый становится единственным
ACTIVE; revocation немедленный и может оставить zero-active fail-closed stop.
Read-only loader отвергает symlink, writable, corrupt и oversized файлы.
Использованы только synthetic keys; `/etc/lumi`/`/var/lib/lumi` provisioning
отсутствует.
Read-only `shadow-transport-readiness.v1` сводит 12 prerequisites: Ed25519,
keyring/ACTIVE key, replay path/parent/state, четыре feature flags и independent
backup devices. Любой missing/inconsistent probe даёт ordered `NO_GO`; даже
синтетический GO остаётся `executionEffect:NONE/actionAllowed:false`. CLI пишет
только один JSON в stdout и не создаёт state/lock. Production `lumi-svc` сейчас
честно возвращает frozen all-blockers NO_GO с exit 1.
Reverse `shadow-response-receipt.v1` подписывает LUMI→KAIROS response отдельной
Ed25519 identity и связывает request ID, exact request/response hashes,
content type, timestamp/nonce/key ID, issuer/scope/audience и literal
`executionEffect:NONE/actionAllowed:false`. KAIROS независимо валидирует оба
wire contracts до consume; replay/tamper fail-closed. Runtime keys/state/route
по-прежнему отсутствуют.
Hermetic `shadow-mutual-auth-transcript.v1` собирает обе identity legs в один
content-hashed `rt_…` proof: request verify → LUMI evaluate → response receipt
verify → KAIROS dispatch. Shared request ID, exact body hashes и receipt ID
проверяются сквозным binding; replay останавливает цепочку до следующего
effectful callback. Все уровни остаются `executionEffect:NONE` и
`actionAllowed:false`; это offline self-test, не runtime transport.
Read-only `shadow-preflight-proof.v1` content-hash связывает полный readiness
result и summary проверенного mutual-auth transcript. Только `GO + self-test`
может дать `ELIGIBLE`, но никогда не `actionAllowed:true`. Frozen production
proof сейчас честно `INELIGIBLE`: self-test успешен, Ed25519 dependency уже
готова, остальные 11 operational blockers сохранены в точном порядке.
Frozen `shadow-service-key-plan.v1` разделяет обе identities: request private
key остаётся у KAIROS, response private key — у LUMI, а противоположные стороны
получают только audience-bound public keyrings. Provisioner использует
exclusive/no-follow writes, `0640`/`0750`, fsync и полный rollback при fault;
существующие/partial/symlink targets не перезаписываются. Production keys ещё
не созданы: сначала отдельно готовятся и проверяются service-owned ancestors.
Frozen `shadow-offline-replay.v1` теперь полностью проводит синтетическое
наблюдение через Relay plan → LUMI rules → KAIROS dispatch → точную genesis
journal projection в памяти. Общий pure `project_record` используется и
реальным append, а тест доказывает byte-equivalent формат. Replay не создаёт
journal/lock и всегда остаётся `projectionOnly:true` и non-executing.
Head-aware `shadow-offline-batch.v1` строит bounded цепочку из 1..64 входов
поверх явного `baseSequence/baseHash`. Все пять frozen triggers проверены в
одной непрерывной цепи; exact retry не двигает head, а duplicate input drift
fail-closed. Проекция совпадает с настоящим journal append/replay на временном
файле, но сам batch не имеет I/O.
Pure `shadow-offline-batch-verification.v1` строго перепроверяет nested
request/response/dispatch/decision bindings, counts/flags/duplicates и всю
sequence/previousHash/recordHash/headHash цепь. Тампер-матрица fail-closed;
цельный пятисигнальный replay и resume chunks `2 + 3` дают одинаковые records
и конечный head.
Frozen `shadow-service-envelope.v1` задаёт отдельную Ed25519 identity будущего
KAIROS→LUMI shadow-вызова: exact POST/path/empty query/body hash/content type,
key ID/timestamp/nonce, issuer/scope/audience и окно ±30 секунд. Sign/verify и
nonce consume внедряются; модуль не читает env/keys/files, не хранит state и не
делает network call. Endpoint и production keys отсутствуют. LUMI venv пока не
содержит `cryptography`, поэтому runtime enablement честно заблокирован.
Pure `shadow-replay-ledger.v1` хранит только hash `(keyId, nonce)` и expiry в
immutable bounded snapshot. Transition валидирует весь snapshot, prune делает
только после inclusive expiry, replay/capacity fail-closed, а JSON restart
сохраняет защиту. Raw key ID/nonce, filesystem, lock и production state
отсутствуют.

- нормализованный EvidenceRecord и decision envelope;
- LUMI получает минимизированные обезличенные торговые признаки;
- shadow-вердикты сравниваются с детерминированными hard gates;
- метрики расхождений, задержек, stale data, API bans и permission drift;
- tamper-evident audit и operator review для конфликтов.

Gate E2: LUMI не может расширить права; timeout/failure проверены fault
injection; решения воспроизводятся по versioned inputs/policy.

### E3 — торговые инструменты KAIROS

Статус 2026-08-11: начат только keyless/offline foundation, независимо от
отложенного runtime-enable E2. Frozen `market-depth-snapshot.v1` строго
нормализует bounded стакан через Decimal, отвергает crossed/locked, несортированные,
дублированные и malformed уровни и content-hash связывает источник, рынок,
время и глубину. Pure `slippage-estimate.v1` детерминированно считает BUY/SELL
depth walk, fee, average price и midpoint slippage; недостаточная глубина
fail-closed, а результат всегда `projectionOnly:true`, `executionEffect:NONE`,
`actionAllowed:false`. Контракт не подключён к endpoint, сети, credentials,
state, feature flag или engine execution. Подробности —
`docs/e3-market-contracts.md`.
Frozen `market-source-comparison.v1` сравнивает 2–8 уникальных стаканов одного
рынка относительно явного времени оценки: данные старше 5 секунд помечаются
`STALE`, clock skew свыше 1 секунды — `FUTURE`, и ни то ни другое не становится
нулевой ценой. Только свежие midpoint участвуют в детерминированной медиане;
менее двух свежих источников даёт `INSUFFICIENT_FRESH_SOURCES`, а отклонение
свыше 100 bps — `DIVERGENT`. Проекция content-addressed, независима от порядка
источников и остаётся `executionEffect:NONE/actionAllowed:false`.
Frozen `paper-trade-ledger.v1` добавляет только immutable synthetic balances и
hash-chained `paper-trade-entry.v1`. Переход заново вычисляет depth estimate,
атомарно в возвращаемом значении списывает input и начисляет net output после
fee; недостаточный paper balance блокируется. Account-bound hash idempotency
возвращает прежний ledger при exact retry и отвергает drift. Строгий verifier
проигрывает balance/fee/request semantics от content-addressed genesis и ловит
даже согласованно перехэшированную подделку. Контракт не имеет I/O и всегда
`simulationOnly:true`, `executionEffect:NONE`, `actionAllowed:false`.
Frozen `paper-risk-policy.v1` задаёт account/symbol allowlist и inclusive hard
limits на order/day quote notional, UTC-day trade count и drawdown, а также
5-секундную freshness с 1-секундным future skew. Content-addressed
`paper-risk-decision.v1` связывает ledger/snapshot/policy/intent и выдаёт
`HOLD` при любом нарушении либо только `PAPER_ALLOW` при полном прохождении.
Даже этот положительный verdict остаётся `paperOnly:true`,
`executionEffect:NONE`, `actionAllowed:false` и не подключён к engine.
Frozen `paper-intent-state.v1` задаёт hash-chained lifecycle
`READY/HOLD → FILLED → RECONCILED|REVIEW`, связывая decision, ledger, snapshot,
policy, fee и idempotency. Fill создаёт только ожидаемый paper-ledger hash;
отдельная reconciliation сравнивает валидированный observed ledger. Совпадение
терминально `RECONCILED`, несовпадение терминально `REVIEW` без auto-retry;
повтор того же observation идемпотентен, drift запрещён. Все состояния остаются
offline/non-executing и не являются production persistence или CEX submit.
Frozen `paper-daily-usage.v1` ведёт content-addressed hash-chain на synthetic
account/UTC-day и принимает только полностью валидированный `RECONCILED`
intent с совпадающими decision/account/day bindings. `HOLD/FILLED/REVIEW`,
чужой день/аккаунт и tamper не увеличивают usage; exact retry идемпотентен.
Risk wrapper теперь получает daily count/notional только из перепроверенного
usage ledger, а не от caller. Drawdown остаётся отдельным явным входом до
появления valuation/equity contract.
Frozen `paper-admission-control.v1` добавляет account-bound `OPEN` и terminal
`STOPPED/TRIPPED`; exact повтор terminal evidence идемпотентен, drift и
автоматический reopen запрещены. `paper-admission-decision.v1` монотонно
объединяет risk и control: только `PAPER_ALLOW + OPEN` даёт `ADMIT_PAPER`, всё
остальное — `HOLD`. Admission теперь обязателен для создания `READY` intent,
но сам остаётся `actionAllowed:false` и не является engine authorization.
Frozen `paper-equity-valuation.v1` полностью оценивает validated paper ledger в
одном quote asset: cash=1, каждый иной актив требует ровно один свежий market
snapshot; missing/duplicate/stale/future price fail-closed. Immutable
`paper-equity-baseline.v1` и derived `paper-drawdown.v1` связывают initial/current
equity и воспроизводят quote/bps drawdown. Risk wrapper теперь получает из
проверенных контрактов daily count, notional и drawdown — caller не задаёт ни
одно из этих трёх значений.
Frozen `paper-pnl-reconciliation.v1` перепроигрывает каждый `RECONCILED` intent
из pre-ledger/original book/idempotency и требует ровно одну новую запись.
Pre/post equity строятся на одном price vector/time, поэтому market move не
маскируется под execution P&L; fee конвертируется из фактического output asset.
`paper-pnl-journal.v1` hash-chains только непрерывные ledger transitions,
идемпотентно отвергает duplicate drift и полностью воспроизводит fees/net/gross
execution P&L totals.
Frozen `paper-total-pnl-snapshot.v1` связывает baseline/current equity с полным
P&L journal и разлагает mark-to-market total на execution net и честно названный
`marketAndHolding` residual. Формулы, ledger boundaries, account и quote
перепроверяются. Контракт явно `taxLotAccounting:false` и не выдаёт residual за
realized/unrealized P&L.
Frozen `e3-readiness-proof.v2` сводит шесть завершённых offline contract checks
и девять operational prerequisites. Текущий результат честно
`OFFLINE_FOUNDATION_COMPLETE/NO_GO`: E2, persistence, engine adapter, accepted
independent-verifier/result binding, restricted testnet account,
withdrawal/transfer denial, runtime reconciliation, runtime stop proof и owner
approval отсутствуют. Даже synthetic all-true даёт лишь
eligibility for preparation, но никогда runtime/live authorization.
Dormant `024_e3_paper_evidence.sql` и KAIROS repository задают append-only
evidence persistence для intent/usage/admission/P&L snapshots. Atomic
compare-and-append блокирует head, требует sequence/previous hash, exact retry
делает no-op, drift/gap/mutation отклоняет. Disposable PostgreSQL rehearsal без
порта/volume прошла и контейнер удалён; production не мигрирован, поэтому
readiness `PRODUCTION_PERSISTENCE_READY` остаётся false.
Frozen `paper-engine-submission.v1` строится только из validated `READY`
intent и content-bind связывает state/account/ledger/snapshot/policy/side/
amount/fee/idempotency. `paper-engine-receipt.v1` принимает только точную
привязку к submission и явные `ACCEPTED/NONE` либо `REJECTED/<bounded reason>`.
Герметичный adapter использует лишь injected `PaperEngineTransport`, считает
его ответ недоверенным, не импортирует CEX SDK/network/runtime config и не
изменяет intent или ledger. Все артефакты остаются
`PAPER_SIMULATION`, `executionEffect:NONE`, `actionAllowed:false`; поэтому
operational check `ENGINE_ADAPTER_READY` по-прежнему false.
Frozen `paper-engine-fill-projection.v1` требует точный validated
`ACCEPTED/NONE` receipt для engine-пути `READY → FILLED`. Receipt обязан
соответствовать canonical submission именно этого ready-state; временная
цепочка фиксирована как `READY ≤ receipt ≤ FILLED`. Receipt ID входит в
hash-chain события, а projection связывает ready/filled state и expected ledger
hash. Rejected/cross-state/future/tampered evidence блокируется; существующая
reconciliation сохранена. Это pure projection без runtime submit/persistence,
поэтому readiness-флаг не меняется.
Frozen `paper-engine-attempt.v1` фиксирует один hermetic invocation как
terminal evidence. Valid response даёт `RECEIVED` с exact receipt; timeout,
transport error и malformed response дают `UNKNOWN/manualReviewRequired` без
receipt. Во всех случаях `retryAllowed:false` и
`automaticResubmitAllowed:false`. Exact replay перепроверяет прежний attempt и
receipt и возвращает их без повторного transport call; drift блокируется до
вызова. Модуль не использует clock/network/SDK/runtime config и не меняет
operational readiness.
Frozen `paper-engine-attempt-resolution.v1` разрешает только validated immutable
`UNKNOWN` attempt и ровно одну ветку: independently recovered exact receipt или
bounded manual disposition. Resolution связывает SHA-256 evidence, не может
предшествовать attempt и всегда сохраняет retry/resubmit запрещёнными. Только
recovered accepted receipt даёт `fillEligible:true`; recovered rejection и все
manual outcomes остаются false. UNKNOWN-specific fill повторно валидирует
resolution/receipt. Исходный attempt не переписывается, runtime query/storage
не добавлены, readiness не меняется.
Frozen `paper-engine-evidence-bundle.v1` совместно перепроверяет READY intent,
submission, attempt, optional receipt/resolution и optional fill projection;
partial/smuggled/ineligible evidence fail-closed. Dormant PostgreSQL store
принимает новый `ENGINE_EVIDENCE` только после полной валидации и совпадения
bundle/database continuity hash. Одноразовый PostgreSQL 17 без port/volume
подтвердил first append, exact retry, next append, gap/drift/mutation rejection
и head, после чего был удалён. Production не запрашивался и не мигрировался;
оба operational readiness checks остаются false.
Frozen `testnet-capability-observation.v1` хранит secret-free permission
inventory либо withdrawal/transfer denial observation только для
`TESTNET/SPOT_PAPER`, с 15-minute expiry и evidence SHA-256 без key identifiers.
`restricted-testnet-account-evidence.v1` требует один inventory и оба denial
для одного account, нужный spot scope, отсутствие всех forbidden grants и
явный denial forbidden permissions/actions. Даже идеальный набор даёт только
`OFFLINE_ELIGIBLE`, сохраняя `runtimeVerified:false` и
`readinessCheckSatisfied:false`; contract сам не делает probes и не меняет
readiness.
Frozen `testnet-capability-verifier-request.v1` разрешает только получение
существующего secret-free evidence, фиксирует `activeProbeAllowed:false` и не
может инициировать withdrawal/transfer. Hermetic injected-source adapter
возвращает validated offline assessment; permissive evidence, timeout, source
error, malformed или secret-bearing response дают NO_GO без exception text.
Exact replay не вызывает source повторно. Даже `VERIFIED_OFFLINE` сохраняет
`independentDeploymentVerified:false` и `readinessCheckSatisfied:false`.

- нормализованные quotes/order books/fees/slippage;
- paper trading и детерминированный ledger;
- persisted trade intent → risk check → bounded execution → reconciliation;
- лимиты на инструмент, аккаунт, день, просадку и число операций;
- запрет withdrawal/transfer и отдельный emergency stop;
- shadow, sandbox, затем малый canary на одном аккаунте и одной CEX.

Gate E3: повтор/рестарт/таймаут не создаёт вторую сделку; позиции и комиссии
сходятся с CEX; stop действительно останавливает новые действия; rollback — это
закрытие/ручное урегулирование, а не переписывание истории.

### E4 — единый UX действий

- обмен из портфеля через явный выбор private/KYC lane;
- предварительный экран identity/custody/fees/risk;
- адресная книга и receive/send без ложного ощущения серверного custody;
- единый центр уведомлений, evidence и поддержки;
- accessibility, localization, responsive UI и usability-тесты денежных путей.

Gate E4: пользователь до подтверждения понимает исполнителя, custody, KYC,
комиссии и необратимость; опасные действия нельзя выполнить случайным тапом.

### E5 — нативный некастодиальный кошелёк

E0.4 inventory evidence (2026-08-18): the checkout has a Rust/UniFFI Bitcoin
Signet preview and synthetic Python boundary/consent contracts, but no key
generation, device authenticator, signature, broadcast, mobile shell, deployed
artifact or signed release. All signing and production-action flags remain
false. Classification is `PARTIAL_NOT_ACCEPTED`; this evidence does not advance
the E5 gate. See `docs/e0-4-native-signing-runtime-observation.v1.json`.

Frozen design-only foundation: `native-wallet-key-boundary.v1` separates the
user-device native app, hardware-backed non-exportable key storage, bounded
native signing bridge and remote server. Server authorization is never enough
to sign and the server may never receive seed/private-key/keystore/biometric or
local-authenticator material. Network choice, recovery, build provenance,
signing and production release remain explicitly unimplemented/false; the
contract has no execution surface.
The next frozen layer uses `native-signing-display-request.v1` to bind one
synthetic unsigned-payload digest to the exact displayed network, destination,
amount and fee, and `native-signing-consent-receipt.v1` to require a distinct
deliberate second interaction. Both remain synthetic/offline: authenticator
verification, signature, production network and action permission are false.
`native-authenticator-evidence.v1` then binds the exact consent chain to hashed
device-key identity, challenge and synthetic assertion evidence with a fresh
window, monotonic counter and consumed-ID replay guard. Hardware/user-presence
claims are not platform attestation: authenticator verification, signing and
all production/action permissions remain false.
The recovery foundation uses two independent paths: user-controlled offline
seed restore and a delayed 2-of-3 guardian/device flow. The server may coordinate
opaque messages but may never receive the seed, hold a recovery share, act as a
guardian or override the threshold. Monotonic epochs, prior-device revocation,
single-use approvals, out-of-band notifications and active-device veto are
mandatory. The policy remains design-only with no chosen cryptography or SDK.
The hash-chained `native-wallet-recovery-attempt.v1` binds the target device and
attestation to exactly the next recovery epoch. Two distinct guardian approvals
plus the 24-hour delay produce only `ELIGIBLE_OFFLINE`; active-device veto and
expiry are terminal. It cannot install new authority, revoke an old device or
perform recovery.

- отдельная threat model и криптографическая спецификация;
- аппаратно защищённое хранилище, биометрия и recovery design;
- reproducible/signed builds, dependency pinning и mobile security review;
- ограниченный native signing bridge;
- по одной сети до полного backup/restore/send/reconcile E2E.

Gate E5: серверная компрометация не раскрывает ключ и не может подписать
перевод; потеря устройства и восстановление проверены до production-релиза.

## Инструментальная политика

Инструмент выбирается из требования, а не из списка брендов. Перед внедрением:

1. проверить официальный источник, владельца, release cadence и CVE;
2. зафиксировать версию и checksum/signature;
3. проверить лицензию и transitive dependencies;
4. испытать в изоляции на synthetic/non-secret data;
5. дать минимальные filesystem/network/credential permissions;
6. добавить обновление, rollback, мониторинг и удаление;
7. не включать в production, если существующий стек решает задачу проще.

Базовые классы средств: SAST, dependency/secret/container/IaC scanning,
property/fuzz/contract/fault/E2E tests, SBOM/provenance, metrics/logs/traces,
chain/CEX reconciliation и synthetic probes. Данные из security-форумов могут
служить сигналом для исследования; неподтверждённый код — не зависимость.

## Ближайший исполнимый пакет

1. Создать `docs/ecosystem-contracts.md` с текущими API и trust boundaries.
2. Провести read-only inventory Wallet, KAIROS и LUMI: runtime, endpoints,
   credentials classes, persistence, callers и feature flags.
3. Зафиксировать модель `PortfolioSource`/`CustodyDomain` без миграции данных.
4. Спроектировать read-only CEX connection flow и permission verifier.
5. Выбрать одну первую CEX только после сравнительной capability/risk-матрицы.

Ни один пункт этого пакета не включает live trading, пользовательские CEX
ключи в production или изменение payout-контура.

## 2026-08-18 — E0/E0.4: EDITORIAL_NEWS_DELIVERY

Read-only inventory completed at `docs/e0-4-editorial-news-delivery-runtime-observation.v1.json`.
Telegram subscription/delivery is implemented but not accepted: timestamp-only
watermarks lack idempotent outbox/leases, source provenance/freshness/licensing,
consent/audit/retention, and bounded retry/dead-letter controls. Separate legacy
`publish_news.py`, `news_bot.py`, and callback-handler Telegram processes create
unreconciled trust and delivery boundaries. API exposure is partial and
unaccepted; site, MiniApp, native, and admin moderation/health surfaces are
absent. No Telegram, customer, MongoDB, provider, deployment, or production
mutation was performed. E0.3 remains first unmet/BLOCKED_OWNER and E0.4 remains
IN_PROGRESS. Next safe route: `E0/E0.4/TELEGRAM_CHANNEL_POST_PROCESSING`.

## 2026-08-18 — E0/E0.4: TELEGRAM_CHANNEL_POST_PROCESSING

Read-only inventory completed at `docs/e0-4-telegram-channel-post-processing-runtime-observation.v1.json`.
The premium Telethon userbot is a high-authority channel-edit writer, but
acceptance is rejected: persistent user-session authority is not least
privilege-bound, channel/message scope is configuration-driven, watcher edits
have no durable receipts/idempotency/reconciliation, and the systemd unit is
unsandboxed/root-default. Duplicate source copies and legacy direct Telegram
writers add drift. No Telegram call, authentication, edit, deployment or
production mutation occurred. E0.3 remains first unmet/BLOCKED_OWNER and E0.4
remains IN_PROGRESS. Next safe route: `E0/E0.4/LEGACY_PAYMENT_EDGE_UPSTREAM`.

## 2026-08-18 — E0/E0.4: LEGACY_PAYMENT_EDGE_UPSTREAM

Read-only inventory completed at `docs/e0-4-legacy-payment-edge-upstream-runtime-observation.v1.json`.
Both enabled public payment aliases proxy wildcard `/` to `127.0.0.1:8080`,
but no mapped systemd/container owner or payment-truth authority was found.
No `:8080` listener was visible; Docker inspection was sandbox-inaccessible,
and `nginx -t` syntax was valid but runtime test was blocked by read-only
`/run/nginx.pid`. Acceptance is rejected pending owner, reachability, TLS,
route-scope, release identity, health and rollback evidence. No HTTP call,
payment/customer read, deployment, restart or mutation occurred. E0.3 remains
first unmet/BLOCKED_OWNER and E0.4 remains IN_PROGRESS. Next safe route:
`E0/E0.4/FRAMEWORK_GENERATED_ADMIN_HTTP_SURFACE`.

## 2026-08-18 — E0/E0.4: FRAMEWORK_GENERATED_ADMIN_HTTP_SURFACE

Read-only declaration inventory completed at `docs/e0-4-framework-generated-admin-http-surface-runtime-observation.v1.json`.
Filament statically declares 12 resources, 16 resource-page files and one web
route, while the complete runtime route universe is not provable without boot:
auth/dashboard/resource/Livewire/vendor routes are generated. Acceptance is
rejected pending a bound generated manifest, closed action/field/role inventory,
runtime artifact binding, and durable audit/reconciliation evidence. No Laravel
boot, authentication, customer/admin data access, deployment or mutation was
performed. E0.3 remains first unmet/BLOCKED_OWNER and E0.4 remains IN_PROGRESS.
Next safe route: `E0/E0.4/GENERATED_FASTAPI_DOCS`.

## 2026-08-18 — E0/E0.4: GENERATED_FASTAPI_DOCS

Read-only static inventory completed at `docs/e0-4-generated-fastapi-docs-runtime-observation.v1.json`.
Relay has 94 decorated routes plus default OpenAPI/docs/redoc and `/static`;
LUMI has 203 plus the same generated docs; KAIROS has 41 decorated routes,
`/assets`, and explicitly disables docs. Combined inferred route objects are
346, but runtime middleware/conditional/generated inclusion is not proven.
Acceptance is rejected pending public-doc exposure classification, static-mount
policy and immutable deployed route manifests. No app import, HTTP call,
authentication, customer/provider access, deployment or mutation occurred.
E0.3 remains first unmet/BLOCKED_OWNER and E0.4 remains IN_PROGRESS. Next safe
route: `E0/E0.4/DEPLOYED_GENERATED_UNIVERSE_RECONCILIATION`.

## 2026-08-18 — E0/E0.4: POST_CLOSURE_GAP_REGISTER

Aggregate register completed at `docs/e0-4-post-closure-gap-register.v1.json`.
Eight confirmed closure gaps remain across money authority, deployment trust,
editorial/channel delivery, public payment edge ownership, generated admin/API
surfaces and `/root` versus `/opt` runtime drift. This register is restrictive
and grants no acceptance or production authority. E0.3 remains first unmet and
BLOCKED_OWNER; E0.4 remains IN_PROGRESS. Next safe route is the owner-gated
remediation plan; no production action is authorized by this register.

## 2026-08-18 — E0/E0.4: DEPLOYED_GENERATED_UNIVERSE_RECONCILIATION

Read-only reconciliation completed at `docs/e0-4-deployed-generated-universe-reconciliation.v1.json`.
Effective systemd units execute `/root` paths while deployed route evidence is
under `/opt` for Relay, KAIROS and LUMI; no immutable manifest binds unit,
executable, dependencies, route inventory, Nginx and generated caches. Parallel
shadow/runtime universes make static route claims non-authoritative. Acceptance
is rejected. No service start/restart, import, HTTP/authentication, customer or
provider access, deployment or mutation occurred. E0.3 remains first unmet/
BLOCKED_OWNER and E0.4 remains IN_PROGRESS. Next safe route:
`E0/E0.4/POST_CLOSURE_GAP_REGISTER`.

## 2026-08-18 — E0/E0.4: OWNER_GATED_REMEDIATION_PLAN

Documentation-only plan completed at `docs/e0-4-owner-gated-remediation-plan.v1.json`.
It organizes four workstreams: runtime identity, money/payment edge, Telegram/
editorial delivery, and generated surfaces. Each has explicit exit evidence,
forbidden actions, owner decisions and independent-review requirements. The plan
grants no implementation, deployment, restart, authentication, send/edit,
charge or production authority. E0.3 remains first unmet/BLOCKED_OWNER and E0.4
remains IN_PROGRESS. Next safe route: `E0/E0.4/OWNER_DECISION_INTAKE`.

## 2026-08-18 — E0/E0.4: OWNER_DECISION_INTAKE

An empty restrictive intake template was created at
`docs/e0-4-owner-decision-intake.v1.json`. No authenticated owner decision,
candidate hash binding, allowed-action enum or independent review was supplied;
therefore no acceptance or authority is inferred. Missing authentication,
ambiguous language, hash/path drift, expiry-as-allowance and reviewer/owner
conflation are explicit rejection rules. E0.3 remains first unmet/BLOCKED_OWNER
and E0.4 remains IN_PROGRESS. Next safe route:
`E0/E0.4/READ_ONLY_REMEDIATION_REHEARSAL`.

## 2026-08-18 — E0/E0.4: READ_ONLY_REMEDIATION_REHEARSAL

Synthetic validation completed at `docs/e0-4-read-only-remediation-rehearsal.v1.json`.
Schema, restrictive authority flags, owner gates, hash/path rules, expiry
monotonicity and E0.3/064B/064D restrictions passed. No production files were
written, services started, network calls made, secrets or customer data read.
The rehearsal does not remediate or accept anything; owner decision and
independent review remain absent. Next safe route:
`E0/E0.4/OWNER_DECISION_INTAKE_REVIEW`.

## 2026-08-18 — E0/E0.4: OWNER_DECISION_INTAKE_REVIEW

Review completed at `docs/e0-4-owner-decision-intake-review.v1.json`.
The intake template is present, but no authenticated owner, candidate hashes,
bounded action enum, independent reviewer, runtime manifest or rollback/replay
evidence is present. Result is explicitly `BLOCKED_OWNER`; no decision or
authority is inferred. E0.3 remains first unmet/BLOCKED_OWNER and E0.4 remains
IN_PROGRESS. Next safe route: `E0/E0.4/RESTRICTIVE_STATUS_REPORT`.

## 2026-08-19 — E0/E0.4: RESTRICTIVE_STATUS_REPORT

The closed restrictive report at
`docs/e0-4-restrictive-status-report.v1.json` binds the five governing input
artifacts by raw-byte SHA-256 and records the eight confirmed gaps only as a
lower bound. It closes the report artifact, not remediation or a gate: no
authenticated owner decision, independent acceptance, current runtime manifest,
trusted-time freshness, rollback/revocation/replay evidence, waiver or production
authority exists. E0.3 remains the first unmet gate and `BLOCKED_OWNER`; E0.4 and
E0 remain `IN_PROGRESS`. The next canonical item is
`E0/E0.3/B5.3/064A_ACCOUNTABLE_OWNER_AND_INDEPENDENT_REVIEWER_DECISION`. The
prior source window is expired, so possible acceptance first requires a new
read-only source refresh and exact candidate; this statement grants no authority
to perform production action or to proceed with 064B/064D.

## 2026-08-19 — E0/E0.3 B5.3/064A: v3 fresh decision handoff

A single new read-only MVCC refresh produced 95 aggregate notification jobs:
81 SENT, one PENDING and 13 SENDING, including 11 stale. The exact snapshot
restored into a removed network-none/tmpfs PostgreSQL 17 container; all 54 table
row-multiset fingerprints and 13 bounded catalog sections matched. The archive,
manifests, container and tmpfs were deleted. Evidence is
`docs/e0-3-bot-b5-3-064a-production-source-refresh.v3.json` (SHA-256
`280e0b0de3c76992ef1674ef76495a0136138c9ee6ab114ff794f8377437d104`).

The exact evidence-only candidate is
`docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json` (SHA-256
`771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf`).
Its conservative 24-hour source window starts `2026-08-19T02:34:54Z`.
Independent reviews found and drove fixes for stale-v2 ceremony selection,
tampered evidence bindings, open nested semantics and verify-time bundle drift.
Both statement creation and verification now require and cross-check all four
exact evidence files. The only current ceremony is
`docs/b64-064a-offline-signing-v3.md`; the unversioned older runbook is
historical v2 evidence and must not be used for the v3 decision. Twelve direct
focused checks pass; pytest is unavailable in installed environments.

E0.3 remains `BLOCKED_OWNER`; 064B/064D and all production action remain
unauthorized. No further design/refresh loop is canonical while this candidate
is current. Next: an authenticated accountable owner and applicable independent
reviewer accept or re-defer this exact v3 digest.

## 2026-08-19 — E0/E0.3 B5.3/064A: v3 restrictive re-deferral

The owner selected restrictive re-deferral for the exact v3 candidate. Evidence
is `docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json`; it binds candidate SHA-256
`771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf` and source
refresh SHA-256 `280e0b0de3c76992ef1674ef76495a0136138c9ee6ab114ff794f8377437d104`.
The conversation is explicitly not an authenticated signature or evidence
acceptance. It permits only `KEYLESS`, `READ_ONLY`, `NON_PRODUCTION` and
`DOCUMENTATION_AND_TESTS`; 064B, 064D, deploy, restart, delivery, retry and row
disposition remain prohibited. E0.3 remains `BLOCKED_OWNER`; the next
canonical item is authenticated owner plus applicable independent-reviewer
decision over the exact candidate, not another refresh loop.

## 2026-08-22 — E0/E0.3 B5.3/064A: v4 read-only source refresh and candidate

The current explicit request authorized one bounded keyless/read-only refresh;
it did not authenticate an owner signature or grant production authority. A
single `REPEATABLE READ READ ONLY` PostgreSQL 17 transaction produced 145
notification jobs: 127 SENT, 4 PENDING and 14 SENDING, including 14 stale;
state, kind, lifecycle and active-recipient-shape invalid counts were zero.
No identifiers or payloads were emitted and no production row was mutated.

The exact exported snapshot was dumped to a 549963-byte custom archive, then
restored into a removed network-none, read-only-root/tmpfs PostgreSQL 17
container. Tracked `bootstrap_roles.sql`, `prepare_database.sql`,
`pg_restore --role=obsidian_migrator --no-owner --no-privileges` and
`runtime_privileges.sql` reproduced all 54 table digests and all 13 bounded
catalog sections: database-local and separately reconstructed cluster-global
comparisons both MATCH. Archive, manifests, containers and tmpfs were deleted.
Evidence: `docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json`, SHA-256
`99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80`.

The exact evidence-only candidate is
`docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json`, SHA-256
`32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316`.
All authority flags remain false. E0.3 remains `BLOCKED_OWNER`; 064B/064D,
deploy, restart, delivery, retry and row disposition remain prohibited. The
next canonical item is an authenticated accountable-owner plus applicable
independent-reviewer decision over this exact v4 candidate digest.

## 2026-08-22 — E0/E0.3 B5.3/064A: v4 one-device synthetic preflight

The existing offline signer rejected the current v4 candidate because its
active restrictive deferral is schema v3 while the signer only accepted v1/v2.
The signer was extended with a fail-closed v3 deferral branch that binds the
exact prior v3 candidate, requires `BLOCKED_OWNER`, conversation-context-only
authentication, restrictive effect and all authority flags false. A regression
test now runs the exact v4 statement, synthetic reviewer envelope, synthetic
owner countersignature and verifier flow.

The synthetic flow passed in an ephemeral temporary directory with no network:
`SYNTHETIC_VALID`, but replay protection, human independence, separate-device
proof, authenticated acceptance and production authority all remain false.
Private keys and envelopes were destroyed. Evidence:
`docs/e0-3-bot-b5-3-064a-v4-synthetic-one-device-preflight.v1.json`.
This is preparation/rehearsal only; E0.3 remains `BLOCKED_OWNER` and no 064B,
064D, deployment, restart, delivery, retry, cutover or row disposition is
authorized. The next canonical item remains the authenticated owner plus
applicable independent-reviewer decision over the exact v4 candidate digest.

## 2026-08-22 — E0/E0.3 B5.3/064B: disposable rehearsal scope check

The requested no-client test was bounded to a disposable clone, but a
read-only inventory found no single tracked 064B `EXPAND` bundle or ordered
runner. The plan requires nullable v2 columns, new versioned tables/functions,
conditional constraints, concurrent indexes and old-runtime compatibility;
the repository currently contains only dependent proposal components 048 and
058–063. Applying them as an invented sequence would not be a faithful
rehearsal: proposal 058 itself combines schema changes, recipient backfill and
strict lifecycle constraints, while 060–063 depend on its resulting objects
and later governance/reconciliation state. Static migration-plan/preflight
checks passed, but no clone was created and no SQL mutation was attempted.
Evidence:
`docs/e0-3-bot-b5-3-064b-disposable-rehearsal-scope.v1.json`.

Production authorization, 064B, 064D and all runtime effects remain false.
E0.3 remains `BLOCKED_OWNER`; the next canonical item is still the
authenticated owner plus applicable independent-reviewer decision over the
exact v4 candidate, followed by an exact reviewed 064B bundle.

## 2026-08-22 — E0/E0.3 B5.3/064B: disposable EXPAND/rollback bundle rehearsal

To keep the owner-blocked route moving without using a second device or
production authority, a separate rehearsal-only 064B bundle was added under
`deploy/postgres/rehearsal/`. It is bound to the real legacy
`023_bot_notification_jobs.sql` schema and deliberately excludes the mixed
058–063 proposal sequence, recipient backfill, legacy state-check replacement,
roles/grants, producer/dispatcher fences and cutover.

The disposable PostgreSQL 17 rehearsal used image
`postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`
with network none, read-only root, tmpfs data, no published ports and
synthetic rows only. Nullable v2 columns, `NOT VALID` checks, token/evidence
tables, ungranted versioned functions and three `CREATE INDEX CONCURRENTLY`
indexes applied successfully. Legacy insert and pending→sending→sent DML
continued to work. Pre-v2 rollback restored the legacy schema and index set;
after a synthetic v2 claim the rollback guard rejected downgrade with
`064b_rollback_forbidden_after_v2_submit`. The container was stopped and
removed. Static Python/JSON/diff checks passed. Two rehearsal landmines were
found and fixed: FK drop order and qualification of `j.id`/`j.attempts` in a
`RETURNS TABLE` function.

Evidence: `docs/e0-3-bot-b5-3-064b-expand-rehearsal.v1.json`. This is
`IN_PROGRESS` rehearsal evidence only, not production acceptance; E0.3 remains
`BLOCKED_OWNER`, 064B/064D and runtime effects remain unauthorized. The one
next canonical item remains the authenticated accountable-owner plus applicable
independent-reviewer decision over the exact v4 candidate, followed by review
of this exact 064B field/function contract.

## 2026-08-22 — E0/E0.3 B5.3/064A: v4 offline handoff preparation

The previous offline handoff document was v3-bound while the current exact
candidate is v4. A separate public, secret-free v4 handoff was added at
`docs/b64-064a-offline-signing-v4.md`. It binds the current candidate and
source hashes plus the immutable v3 prior candidate and restrictive v3
deferral, gives the correct signer input paths, and explicitly requires two
genuinely independent offline devices. Same-device accounts, profiles, VMs or
keys are not accepted as independence.

The handoff is documentation and static-test preparation only: no private key,
signature envelope, registry, trusted time, replay ledger or production
authority was created. `064A_V4_HANDOFF_STATIC_PASS`, JSON parsing and diff
checks passed. Evidence:
`docs/e0-3-bot-b5-3-064a-v4-handoff.v1.json`, SHA-256
`621a1c8ce2c932d2e5bc0d91edced5fa9542a144de9d552300e9d64c42169dfa`. E0.3 remains `BLOCKED_OWNER`;
the exact next canonical item is the real authenticated accountable-owner plus
independent-reviewer decision over candidate SHA-256
`32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316`.

## 2026-08-22 — owner reprioritization to keyless E4

The owner explicitly requested moving to the next roadmap point while the
E0.3/064A owner gate remains unresolved. This is a reprioritization, not an E0.3
waiver or production acceptance: 064B/064D, deployment, restart, retry and live
row disposition remain deferred. The active bounded slice is E4's dormant
test-only invocation adapter. It revalidates the complete
`preview → acknowledgement → draft → assessment → reservation → BUY/SELL`
chain, calls only an explicitly test-only handoff store, returns bounded result
metadata and hard-codes `routeConnected:false`, `productionInvocationAllowed:false`
and `actionAllowed:false`. Pure/SQLite E4 tests pass 69/69; optional PostgreSQL
tests remain skipped without `TEST_POSTGRES_DSN`. Follow-up capability-boundary
review completed as `REVIEW_PASS_TEST_ONLY_CAPABILITY_BOUNDARY` in
`docs/e4-private-action-invoker-security-review.v3.md`: production-capable
handoff stores no longer expose a mutable `test_only` switch; the invoker
requires an explicit test-only wrapper, while trusted principal/actor and
applicable BUY web-user bindings remain enforced before handoff. No production
route/provider/HTTP reference was found. The wrapper is isolation, not
production authorization. Next ordered E4 item is the owner-gated disposable
PostgreSQL rehearsal; no target/snapshot approval is present.

## 2026-08-22 — E4 disposable full-snapshot restore diagnostic

The owner explicitly authorized one read-only connection to the running
`obsidian-postgres` service for snapshot acquisition. A 578528-byte encrypted
custom-format dump of `obsidian_exchange` was created with a newly generated
ephemeral key; the previously exposed key was not used. The snapshot was
loaded into target `e4-full-snapshot-20260822-01`, bound to target fingerprint
`20989486782bb23d24732d9a543e416d71b458c2191765c9824e8214208a21de`, using
PostgreSQL image
`postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`.
The target had network none, read-only root, tmpfs-only data and no published
ports. `pg_restore` completed successfully; 54 tables were present and both
source and fixture lacked the proposed `025` objects. The target, encrypted
snapshot and ephemeral key were destroyed after inspection.

This remains `NO_GO_NON_AUTHORITATIVE`, not E4 promotion evidence. The live
source changed after the snapshot point (`bot_users` count and two content
digests drifted), fixture ACLs intentionally differ because restore used
`--no-owner --no-privileges`, the machine-readable single-use authorization
receipt was not created, and production was contacted for snapshot acquisition.
No production DML, migration, restart, route wiring or action occurred.
Evidence: `docs/e4-full-snapshot-rehearsal.v1.json`. The next ordered E4 item
is a fresh target-bound rehearsal under the formal receipt contract; do not
apply `025` or promote the action route.

## 2026-08-22 — E4 receipt-bound runner boundary implementation

The next code-bearing E4 slice implemented
`relay/core/e4_rehearsal_runner_boundary.py` and
`tests/test_e4_rehearsal_runner_boundary.py`. The boundary accepts only an
`ELIGIBLE` target-bound receipt and deterministic fixture-spec fingerprint. It
emits a pinned PostgreSQL image, `network=none`, read-only root, tmpfs-only
data, no published ports or persistent volume, opaque snapshot/key references,
mandatory post-load read-only evidence and final teardown/absence checks.
Tampering with receipt status, target fingerprint, network or port arguments
fails closed; path-like and secret-like references are rejected. Seven focused
tests pass. The module is non-executing and has no Docker/database/environment/
HTTP/secret-reading surface, so no production route, migration, ACL, service or
database changed. Evidence:
`docs/e4-rehearsal-runner-boundary-review.v1.md`. The actual executor remains
blocked by the formal single-use receipt and must consume a pre-existing
production-disconnected snapshot.

## 2026-08-22 — E4 formal receipt consumption boundary

The next keyless E4 slice added owner-window and owner-approved opaque
snapshot/key-reference digests to the synthetic authorization receipt, aligned
target ID validation between authorization and boundary, and added the
test-only `SQLiteE4RehearsalReceiptLedger` at
`relay/core/e4_rehearsal_receipt_consumption.py`. It validates the exact plan,
owner approval, receipt, runner boundary and handle bindings before an atomic
`BEGIN IMMEDIATE` claim. The first claim is durable `CONSUMED`; concurrent or
later claims are `REPLAY_BLOCKED`; before-commit faults roll back and
after-commit faults remain consumed so retry is prohibited. Capability output
now distinguishes `rehearsalInvocationAllowed` from `moneyActionAllowed:false`.

Evidence: `docs/e4-rehearsal-receipt-consumption.v1.json`; ADR:
`docs/adr/0039-e4-rehearsal-receipt-consumption.md`; independent review:
`docs/e4-rehearsal-receipt-consumption-review.v1.md`. Stdlib flow, concurrent
claim, fault-boundary, compile and diff checks passed; `pytest` is unavailable
in the host and is not claimed. This remains `IN_PROGRESS`, non-authoritative
and non-production: no authenticated owner decision, trusted execution clock,
content-bound snapshot/key material, full 12-step executor, hardened Docker
target, TOCTOU-safe ownership or cleanup proof exists. The next canonical item
is the owner-gated fresh rehearsal using a real exact receipt and a genuinely
pre-existing production-disconnected encrypted snapshot; no executor,
migration, route or production contact is authorized.

## 2026-08-22 — E4 owner-gated fresh rehearsal preflight

A fresh read-only launch preflight confirmed `BLOCKED_OWNER` at
`docs/e4-owner-gated-fresh-rehearsal-preflight.v1.json`. The workspace contains
only the non-executing plan/auth/boundary/receipt-consumption contracts: no
authenticated owner decision, machine-readable eligible receipt,
production-disconnected encrypted snapshot, E4 executor or reusable historical
target exists. The historical target/snapshot were destroyed and are
non-authoritative; generic encrypted backups are not accepted without E4
manifest/content/provenance binding. Docker inventory showed only the existing
non-E4 `obsidian-postgres` and `e03-relay-p5b-rehearsal` containers; no E4 target
was present. No production DB, secrets, Docker execution, snapshot read or
file mutation occurred. Two independent read-only reviews returned
`NO_GO_BLOCKED_OWNER`. The exact next canonical item is to supply the
authenticated owner receipt plus a pre-existing disconnected snapshot; until
then no executor, snapshot acquisition, Docker target or migration may run.

## 2026-08-22 — E4 owner-artifact handoff package

Prepared a bounded keyless handoff package for the active owner-gated route:
`docs/e4-owner-decision-handoff-template.v1.json`,
`docs/e4-disconnected-snapshot-staging-manifest-template.v1.json`, and
`docs/e4-owner-artifact-handoff-runbook.md`. The templates are explicitly
`TEMPLATE_NOT_AUTHORIZED`, contain no secrets or snapshot bytes, and do not
replace authenticated owner/reviewer signatures, provenance, or an executor.
Frozen E4 manifest and runner-source hashes are recorded for offline binding;
JSON parsing, secret-pattern scan, and `git diff --check` passed. The next
canonical item remains the authenticated owner decision plus a pre-existing
production-disconnected encrypted snapshot; no rehearsal launch is authorized.

## 2026-08-22 — E4 encrypted snapshot staging

Using the owner-supplied public SSH Ed25519 recipient, the existing PostgreSQL
custom dump was streamed through `age` into
`/root/E4-owner-handoff/obsidian_exchange-cutover-20260810.dump.age`. The
ciphertext is `0600`, 460027 bytes, and has SHA-256
`47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e`; no
private key or passphrase entered the server, and no plaintext was opened or
decrypted by the agent. Added the staged manifest
`/root/E4-owner-handoff/e4-disconnected-snapshot-staging-manifest.staged.v1.json`.
This is `STAGED_NOT_AUTHORIZED`, not an eligible receipt: immutable-handle
proof, authenticated owner/reviewer provenance, target binding, one-shot
consumption, and the full hardened 12-step executor remain required.

The next operator instruction is saved at
`/root/E4-owner-handoff/04-owner-signing-key-instruction.md`: create a
separate owner signing key on Android and provide only its public half. No
payload is signed yet because exact target binding and an independent reviewer
are still required; the encryption key is not reused for signatures.

## 2026-08-22 — E4 hardened executor boundary implementation

Implemented `relay/core/e4_hardened_executor.py` and its focused
`tests/test_e4_hardened_executor.py` suite. The bounded runtime accepts only an
authenticated registry result plus a separate consumed one-shot replay gate,
uses exact plan/receipt/boundary and container-label identity binding, verifies
the encrypted snapshot by immutable handle and digest, and accepts only an
external ephemeral key FD. Its Docker adapter is argv-only, pinned,
`--pull=never`, network-none, read-only-root, tmpfs-only, non-root,
capability-dropped, no-new-privileges, bounded-health and bounded-teardown;
age-to-`pg_restore` is streamed without a plaintext snapshot file. Read-only
evidence checks the absence of proposal `025` and teardown refuses unowned
targets. The original staged ciphertext is retained; no destructive snapshot
delete is automatic.

The synthetic executor/provider suite passes 10/10; formal receipt-consumption
contract functions pass 6/6 through a local stdlib compatibility harness;
promotion 3/3, replay 6/6,
owner/reviewer verifier 3/3 and preflight 3/3 also pass with stdlib
`unittest`; compilation and diff checks are clean. No Docker, PostgreSQL,
`age`, snapshot, production service, secret or private key was accessed. The
slice is `IN_PROGRESS` and non-authoritative: current evidence has no reusable
execution receipt because its one-shot claim is consumed and the owner window
is not reusable. Evidence: `docs/e4-hardened-executor-review.v1.md`. The
independent review is recorded in
`docs/e4-hardened-executor-independent-review.v1.md`; it fixed replay/receipt
binding and stronger ephemeral snapshot/key-handoff checks. The remaining next
item is concrete authoritative verifier/receipt callback wiring through
`relay/core/e4_authenticated_gate_provider.py`; do not retry the consumed claim
or create another signing key.

## 2026-08-23 — E4 authoritative gate-provider provenance boundary

The independent executor review found that passing two `VERIFIED`/`CONSUMED`
mapping objects directly into a runtime left their provenance implicit. Added
`relay/core/e4_authenticated_gate_provider.py` and wired the executor to accept
only a provider that calls the cryptographic verifier first, then the one-shot
consumer, binds both results to the exact plan/target/snapshot/boundary and
hashes the envelope. Added the concrete lazy callback adapter at
`relay/core/e4_authoritative_gate_callbacks.py`: it calls the file-backed
promotion verifier, derives the exact public-artifact identity, consumes the
temporary replay claim, then consumes the formal receipt and emits the bound
executor gate. Its focused tests pass 3/3 with real temporary ledgers and
synthetic public artifacts; executor/provider remains 10/10 and the formal
receipt functions pass 6/6 through a local stdlib compatibility harness. No
current claim was retried, no Docker/age/PostgreSQL action occurred, and no
secret or private key was accessed. Status remains `IN_PROGRESS`/non-production:
the existing claim/window are not reusable, and actual file-backed invocation
still requires a fresh exact owner-gated receipt plus approved ephemeral key-FD
handoff and teardown decision. Do not create another signing key.

## 2026-08-22 — E4 backup inventory

A read-only filename, metadata, type, and digest scan found the PostgreSQL
custom dump
`/var/backups/obsidian-exchange/postgres/obsidian_exchange-cutover-20260810.dump`
with matching checksum, but it is unencrypted and has no E4 binding. The
`/root/backups/exchange_*.db.gz.enc` artifacts are OpenSSL-encrypted SQLite
backups using a private local backup key, so they are not qualified E4
PostgreSQL snapshot copies. No backup content was opened or decrypted and no
production contact or mutation occurred. The next canonical item is to obtain
an owner-controlled offline encryption recipient and authenticated signing
scheme before staging any encrypted copy; rehearsal remains unauthorized.

## 2026-08-23 — E4 hardened executor verification recheck

The authoritative callback, hardened executor, preflight, replay-registry and
owner/reviewer verifier paths were rechecked without invoking the current
file-backed gate or touching Docker, PostgreSQL, age, production, secrets or
private keys. Stdlib suites passed `10/10`, `3/3`, `3/3`, `6/6` and `3/3`;
Python compilation and `git diff --check` passed. Host-wide discovery remains
environment-limited because `pytest` is unavailable; its 14 import errors are
not gate evidence. The staged ciphertext remains `STAGED_NOT_AUTHORIZED`, no
authority or execution flag changed, and E4 remains `IN_PROGRESS`/non-
production. Evidence: `docs/e4-hardened-executor-verification-recheck.v1.json`.
The exact next canonical item is a fresh authenticated owner receipt, an
approved ephemeral key-FD handoff and an explicit snapshot retention/teardown
decision; do not retry the consumed claim or invoke the current handoff.

## 2026-08-23 — E4 v6 public owner-payload preparation

The owner confirmed reuse of the existing encrypted snapshot and retention of
the ciphertext after rehearsal. A fresh public payload was prepared at
`E4-owner-handoff/e4-owner-decision-payload.v6.json` with SHA-256
`2e7779db75a894be076753ab40ce5c2493bd22ca8895e75f8765c133dd14a0af`. It uses
the previously owner-selected target reference, which was never created, plus
a new short approval window and single-use nonce; the prior v5 claim is not
reused. Exact snapshot/target/manifest binding, JSON, fail-closed authority and
diff checks passed. Evidence:
`docs/e4-owner-payload-v6-preparation.v1.json`; offline instructions:
`E4-owner-handoff/08-e4-v6-owner-signing-instruction.md`. This remains
non-authoritative `IN_PROGRESS`: no owner/reviewer signature, trusted time,
fresh replay claim, key-FD handoff, Docker execution or production contact
exists. Next canonical item is the offline owner signature on v6 followed by
the independent reviewer envelope/signature.

## 2026-08-23 — E4 owner-payload refresh generator

Repeated manual transport attempts showed that long pasted shell/JSON commands
were split by the Android chat-to-Termux path, while short-lived payloads
expired before owner signing. Implemented
`relay/core/e4_owner_payload_refresh.py` to refresh an exact prior payload with
a new identity, 15-minute approval window and random nonce digest while
preserving every frozen trust/snapshot/target binding. It requires fail-closed
source and approval authority, rejects duplicate/non-finite JSON, reads through
a bounded no-follow regular-file descriptor and writes a new file exclusively
without overwrite. Focused tests pass 5/5; owner/reviewer verifier regression
passes 3/3; compilation and diff checks pass. Evidence:
`docs/e4-owner-payload-refresh-generator.v1.json`.

No signature, authority, Docker, PostgreSQL, decryption or production contact
was created. Both available Codex SSH keys were rejected by `obsidian69.io`,
so the generator was not deployed remotely and no password was requested or
stored. E4 remains `IN_PROGRESS`; the next canonical item is to deploy or run
the generator immediately before offline owner signing, then obtain the
independent reviewer envelope.

## 2026-08-23 — E4 one-shot safety freeze after split-role review

The active owner-prioritized route remains E4, but the experimental one-shot
path is now explicitly `NO_GO_IN_PROGRESS` and disabled before network or
execution effects. Review found that later v12/v13 payload attempts silently
expanded the frozen 15-minute window to 30 minutes, placed the reviewer role on
the owner device, accepted server-supplied TSA roots, signed owner/trust-root
material while online, used per-run replay state and treated retained
ciphertext as successful even though frozen plan v1 requires snapshot
destruction. Payloads v11-v13 are expired and cannot be reused.

The refresh generator again enforces exactly 900000 ms and now requires the
exact schema, frozen target/snapshot/plan, trust anchors, clock, namespaces and
public instructions; hidden authority or secret fields fail closed. The
Termux prototype separates reviewer request/response, pins the DigiCert root,
intermediate, responder, policy, nonce and genTime, binds itself and the TSA
chain in the release, and rejects a co-resident reviewer key. The legacy
private-key-streaming handoff is disabled. These changes do not authorize a
ceremony: both one-shot entry points remain hard-disabled because offline
owner/trust-root handoff, trusted final-bundle time, durable cross-run replay,
an independently frozen release and a real independent reviewer are not yet
proved. No deployment, restart, Docker, PostgreSQL, decryption, production
contact or private-key access occurred. Per owner direction, E4 verifier and
executor were not rerun; generator tests pass 10/10, compilation and diff
checks pass. Evidence: `docs/e4-one-shot-safety-freeze.v1.json` and updated
`docs/e4-owner-payload-refresh-generator.v1.json`.

The exact next canonical item is to freeze a versioned v2 plan/receipt contract
that permits retention of the immutable encrypted source while requiring and
proving destruction of the disposable target and every transient plaintext.
No new signing ceremony or rehearsal starts before that contract and its
independent review.

## 2026-08-23 — owner returns to the earliest unmet non-E4 route

The owner explicitly excluded E4 from the current work after fatigue with that
route and requested continuation of the remaining ecosystem work. This changes
the active task scope, not gate truth: E4 remains `IN_PROGRESS` with a `NO_GO`
gate decision, is not waived or superseded, and receives no authority. E1, E2,
E3 and E5 also do not
advance merely because they are in scope. Canonical ordering therefore returns
to the earliest unmet criterion, `E0/E0.3/B5.3/064A`, which remains
`BLOCKED_OWNER`.

Local public-artifact reconciliation verified the exact v4 source, candidate,
prior candidate, restrictive v3 deferral and v4 handoff SHA-256 cross-bindings.
It does not claim current implementation binding: the historical decision input
no longer matches the current `bootstrap_roles.sql` and `prepare_database.sql`
bytes. The v4 source observation window expired at `2026-08-23T03:25:06Z`; its
counts are historical and no longer current production truth. The v3 deferral
binds the prior v3 candidate only, and neither authenticated v4 owner acceptance
nor an independent reviewer acceptance exists. No production contact,
customer/secret read, signature, Docker/PostgreSQL invocation, E4 verifier/
executor call or runtime mutation occurred. Evidence:
`docs/e0-3-bot-b5-3-064a-current-authority-reconciliation.v1.json`.

Do not start another source-refresh window until a genuinely independent
reviewer on a separate offline device and the exact trust-registry/trusted-time/
revocation/durable-replay path are ready. The one next canonical item is owner
confirmation of those prerequisites followed by explicit authorization for one
bounded read-only 064A production refresh. Until then 064B, 064D, deploy,
restart, delivery, retry, row disposition and every E4 action remain prohibited.

## 2026-08-23 — 064A refresh launch preflight stops before production

The owner conversationally authorized one bounded read-only 064A refresh in
response to the exact prior proposal, but that single-use authorization was
conditional on all hard prerequisites and was not consumed. Three independent
route, state and security/DevOps reviews returned `NO_GO` before production
contact. The independent reviewer and separate offline device are not proved
ready; no concrete production-authenticated registry, trusted-time,
revocation or durable atomic replay consumer exists; and the exact secret-safe
operator command/credential mapping has not been reviewed.

The review also found technical launch blockers. The historical v4 observation
used PostgreSQL 17.10, while the PostgreSQL project now identifies `pg_dump`
before 17.11 as affected by CVE-2026-19385. The runner invokes `pg_dump` as
`postgres` without a separately attested least-privilege dump principal, its
archive/manifest cleanup is not one fail-safe absence-verified orchestration,
and the signature statement can outlive the source-evidence window because
verification does not bind statement expiry to source expiry. The expired v4
package and current implementation drift remain separate blockers.

One bounded local defect was fixed: `b64_snapshot_dump.py` previously accepted
any dirty-data result whose `status` was `IN_PROGRESS`, even though target or
legacy-shape failure uses the same status with empty counts. It now requires
the exact aggregate schema, ordered non-negative counters, arithmetic/subset
relations, known unique blockers and criterion consistency before reaching
`pg_dump`. Focused tests pass 14/14, including the target/shape failure and
ambiguous mutation cases. This guard does not make the whole refresh runner
safe and does not authorize a refresh.

Three independent post-change reviews pass the final local guard/evidence
slice after adversarial counter mutations closed the full SQL-derived state,
subset and disjointness relations. The root focused 064A/snapshot suite passes
68/68; an independent extended selected suite passes 71/71. These are local
acceptance results only and leave the operational refresh verdict at `NO_GO`.

Evidence:
`docs/e0-3-bot-b5-3-064a-refresh-launch-preflight.v1.json`. No production/DB
contact, Docker/PostgreSQL invocation, customer or secret/private-key read,
signature, new 24-hour window, retry or E4 action occurred. E0.3 remains
`BLOCKED_OWNER`. The one next canonical item is to harden and independently
review one exact 064A refresh runbook with patched digest-pinned `pg_dump`, a
least-privilege principal, complete cleanup, source-window binding and the
concrete authentication path before requesting fresh owner authorization.

## 2026-08-23 — 064A source-window v2 local protocol closure

The first bounded defect from the refresh-runbook review is closed locally.
Production verification now rejects legacy v1 statements and requires an exact
hash-bound v2 source context. The source interval is fixed to exactly 86,400
seconds and is half-open; the statement cannot outlive it, and reviewer/owner
envelopes cannot start before or outlive the statement. The offline signer
derives both epochs from the already bound candidate/source evidence rather
than accepting a free operator-supplied window. It also rejects incomplete
cleanup declarations unless the four historical absence claims are present and
literal `true`; this validates the declaration shape only and is not runtime
cleanup proof.

Adversarial coverage includes production legacy-v1 use, missing or mismatched
source context, 86,399/86,401-second and 100-day windows, exact expiry,
statement/envelope overflow, source tamper and incomplete cleanup claims. The
focused decision/signer suite passes 15/15 and the extended 064A/snapshot suite
passes 75/75. Three independent state/security, route/authority and
security/DevOps reviews pass the local slice and retain operational `NO_GO`.
Evidence:
`docs/e0-3-bot-b5-3-064a-source-window-v2-closure.v1.json`.

No production, Docker, PostgreSQL, customer data, operational secret or
operational private key was accessed; no production signature/source window/
refresh was created. Tests used only ephemeral synthetic keys in temporary
directories. The prior conversational authorization remains unconsumed, and
E4 was not touched. E0.3 remains
`BLOCKED_OWNER`. The one next canonical item is to harden one exact 064A
refresh runbook with patched immutable digest-pinned `pg_dump` 17.11+,
least-privilege credentials, complete fail-safe cleanup/absence evidence and a
concrete production registry/trusted-time/revocation/durable-replay adapter,
then independently review it before requesting fresh owner authorization.

## 2026-08-23 — 064A hardened refresh lifecycle local closure

The non-production lifecycle half of the exact hardened 064A refresh runbook
is now locally closed. A frozen plan binds the reviewed PostgreSQL 17.11
linux/amd64 image child and nine executable inputs. The hermetic core validates
the exact source container ID and least-privilege evidence, protects caller
file descriptors, rejects malformed or colliding container IDs, skips unbound
cleanup callbacks, and retains inode bindings through post-unlink/post-rmdir
link-count verification. Cleanup receipts are deliberately limited to the
registered workspace paths and exact ID-bound containers; external copies and
physical erasure are not claimed. Dump-side archive options are not confused
with restore enforcement: the future restore adapter must attest both
`--no-owner` and `--no-privileges`.

Focused tests pass 78/78 and the extended 064A/B5.3 set passes 155/155.
Independent state, route and research reviews pass the final local bytes after
adversarial plan mutation, type-alias, ID-collision, rename/hardlink race,
partial descriptor-acquisition, callback and deadline findings were closed.
Evidence:
`docs/e0-3-bot-b5-3-064a-hardened-refresh-lifecycle.v1.json`; frozen plan:
`docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json`.

This is `LOCAL PASS / OPERATIONAL NO_GO`, not authority. Production adapters,
the least-privilege principal, production registry authentication, trusted
time, revocation, durable replay, a hard process deadline and fresh exact-plan
owner plus separate reviewer acceptance do not exist. The shared source
network namespace does not prove egress isolation. No production, database,
Docker container, customer data, operational secret/private key, signature,
new source window, retry or E4 action was touched. E0.3 remains
`BLOCKED_OWNER`; the prior conversational authorization remains unconsumed.

## 2026-08-23 — 064A PostgreSQL privilege-inventory reconciliation

The loader/privilege mismatch is closed locally without changing the truthful
064A production-source count. The immutable SQLite cutover profile is now
explicitly migrations `001–023`, 54 source-backed tables, 29 sequences and two
functions. Repository migration `024` is a separate post-cutover profile that
adds two PostgreSQL-only E3 tables and two functions, producing a prospective
56/29/4 repository-complete schema. Its current production disposition is
`UNKNOWN_NOT_REOBSERVED`; repository presence is not deployment evidence.

`deploy/postgres/migration-profile.v1.json` content-binds every numbered
migration. The validator, cutover preflight and runbook select exactly the
23 production-cutover entries; missing, unlisted or byte-drifted migrations
fail closed, and the old wildcard that silently selected `024` is gone. The
production runtime ACL now refuses any table, sequence or function inventory
outside exact `001–023` before granting roles. PostgreSQL's global default
`PUBLIC EXECUTE` for future functions is revoked with the correct global
creator-role form, and migration `024` explicitly revokes `PUBLIC EXECUTE` on
both E3 functions. It receives no app, read-only or payout grants. The atomic
loader also requires exact source-set equality, rejecting both missing and
unexpected tables. The privilege verifier checks the global function default
ACL and rejects runtime-role memberships in either the member or parent
direction; bootstrap enforces the same membership boundary.

Static plus focused 064A verification passes 91/91. A loopback-only disposable
PostgreSQL 17 container independently passed the production ACL matrix,
`ACL → 024` denial matrix, exact 54-table atomic loader and runtime-schema
profile, then was removed. Evidence:
`docs/e0-3-bot-b5-3-064a-postgres-inventory-reconciliation.v1.json`.

This is `LOCAL PASS / OPERATIONAL NO_GO`. The frozen 064A plan remains a
54-table local profile and was rebound to the corrected runtime-ACL bytes; no
prior authorization covers those changed bytes. Production was not contacted
or changed, its current schema was not re-observed, and no migration, ACL,
principal, deployment, restart, refresh, customer data, operational secret,
retry or E4 action occurred. E0.3 remains `BLOCKED_OWNER`.

The next canonical item is exact `obsidian_b64_snapshot_reader` provisioning
against the frozen `001–023` profile, including no elevation/memberships,
bounded read-only role settings, exact database/schema/table privileges,
SELECT-only access to the exact 29 sequences solely for complete `pg_dump`
`last_value/is_called` state, and explicit denial of sequence USAGE/UPDATE,
function, other-schema and write capabilities.

## 2026-08-23 — owner decision: code-first continuous delivery

The owner removed the standing practice of carrying every local slice as a
permanent `NO_GO` and requested that roadmap work be implemented as project
code and deployed incrementally. This changes delivery policy, not E0–E5 gate
truth or security/custody invariants. A normal bounded, reversible change now
proceeds in one chain through implementation, proportional tests, rehearsal or
canary, rollout and post-deploy verification. `NO_GO` is reserved for a named
failed preflight or an observed blocker; it must not trigger another unbounded
design-only loop.

For the active route this supersedes the prior design-only stop. The snapshot
reader slice should produce executable provisioning code, a verifier,
adversarial tests and a disposable PostgreSQL 17 rehearsal, then perform a
bounded production rollout when the exact preflight and rollback checks pass.
Failed tests, unavailable credential transport, uncertain money outcomes,
irreversible data loss or missing rollback remain concrete stop conditions.
E4 and migrations `024+` remain outside this slice.

## 2026-08-23 — production dormant snapshot-reader rollout

The code-first `obsidian_b64_snapshot_reader` slice is deployed on the active
`E0 → E0.3 → B5.3 → 064A` route. Production now has an exact `NOLOGIN`,
`NOINHERIT`, non-elevated role with no credential, a two-connection limit,
54-table `SELECT`, and `SELECT` only on the exact 29 sequences required by
`pg_dump`. Sequence `USAGE`/`UPDATE`, function execution, write/DDL, other
user schemas, ownership and memberships are absent. The frozen catalog is
54 tables / 423 columns / 29 sequences / 2 functions with column digest
`adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99`.

The deployment runner separates the read-only observation channel from a
mandatory privileged mutation channel. The latter is bound to the exact
container ID/image/PID Unix socket, forbids ambient libpq configuration and
credential-bearing DSNs, uses an empty `0600` memfd passfile, verifies actual
Unix-socket transport and reconciles ambiguous apply outcomes with a
nonce-bound rollback. An initial apply through the mislabeled historical
admin env resolved to `obsidian_readonly` and ended fail-closed as
`FAILED_ROLE_ABSENT`; the corrected runner prevents recurrence. The final
dual-channel apply returned `DEPLOYED_DORMANT`, the post-deploy verifier is
`match`, direct login is denied, and the PostgreSQL container remains healthy
without restart. No customer rows, migrations, HBA, credential, refresh,
money action or E4 path were touched.

Static verification passes 104/104; the full disposable PostgreSQL 17
provision/denial/exported-snapshot/deploy/rollback integration passes and its
container was removed. Compilation, focused diff check and changed-file
Gitleaks pass. Three independent latest-byte reviews pass. Evidence:
`docs/e0-3-bot-b5-3-064a-snapshot-reader-dormant-rollout.v1.json`.

The next bounded deployable slice is exact first-match HBA isolation while the
role remains `NOLOGIN`, followed by short-lived SCRAM issuance/revocation,
LOGIN activation, a production SourceAdapter with independent credential FDs,
and the patched PostgreSQL 17.11 two-connection exported-snapshot rehearsal.
Those activation and refresh steps remain blocked until their own preflights
pass; this dormant rollout is not refresh authority.

## 2026-08-23 — production dormant snapshot-reader HBA isolation

The next code-first slice is also deployed on
`E0 → E0.3 → B5.3 → 064A`. The production HBA now begins with seven exact
role-scoped first-match rules: local and replication are rejected; only
`obsidian_exchange` for `obsidian_b64_snapshot_reader` from the production
PostgreSQL network namespace source `127.0.0.1/32` may use SCRAM; every other
IPv4/IPv6 database and replication path is rejected. The deployed HBA SHA-256
is `08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6`;
the exact original SHA-256
`45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82`
is retained in a root-owned recovery state.

The runner binds the exact plan, manifest, container, image, PID, PGDATA
volume, cluster system identifier, file metadata and dormant role before any
mutation. It keeps a durable phase journal and original backup, uses atomic
exchange, preserves displaced bytes across reverse-exchange and post-rename
fsync failures, always reloads a restored original policy, and provides exact
rollback/reconcile paths for bounded crash phases. Recovery rebinds the fresh
container/PID/cluster/catalog/role/HBA state before deleting known recovery
evidence; foreign or ambiguous state is retained fail-closed.

The final production apply returned `HBA_DEPLOYED_PARSED_DORMANT`: parser
errors are absent, configuration load time advanced, rollout-window logs have
no reload error, and the container stayed healthy without restart. Independent
verification is `match` / HBA `EXACT`; the role remains `NOLOGIN` with no
credential. Five existing app/payout/readonly runtime connection probes pass
using metadata-only queries. No customer rows, migrations, LOGIN/password,
refresh, money action or E4 path were touched.

HBA unit tests pass 14/14 and the selected static set passes 118/118. The exact
PostgreSQL 17 disposable integration covers namespace SCRAM allow, the full
deny matrix, reconcile from `CANDIDATE_INSTALLED`, re-apply and strict rollback;
its container and volume were removed. Compilation, diff check, Gitleaks,
landmines and three independent latest-byte reviews pass. Evidence:
`docs/e0-3-bot-b5-3-064a-snapshot-reader-hba-rollout.v1.json`.

The next bounded slice is the short-lived SCRAM credential lifecycle and
production SourceAdapter credential-FD contract while the role remains
`NOLOGIN`, followed by a disposable two-connection exported-snapshot rehearsal
before any separate LOGIN activation. Remaining activation blockers are
`LOGIN_DISABLED`, `CREDENTIAL_NOT_ISSUED` and
`TCP_SCRAM_EXPORTED_SNAPSHOT_NOT_REHEARSED`.

## 2026-08-24 — 064A short-lived SCRAM and SourceAdapter disposable closure

The next code-first contract slice is verified without activating the
production role. The runtime creates one high-entropy SCRAM verifier with an
absolute server expiry, delivers it only through two independent sealed
anonymous `0600` memfds, and serializes issue/revoke/reconcile with a bounded
advisory-lock backend. The SourceAdapter opens one digest-bound helper inside
the exact PostgreSQL network namespace, exports and holds a repeatable-read
read-only snapshot, and attests the frozen 54-table/423-column/29-sequence ACL
profile inside that same transaction. Close truth requires a reaped source
process plus fresh `NOLOGIN`, password-absent and zero-session evidence.

The dump contract now requires libpq `require_auth=scram-sha-256`, a five-second
connect timeout, a server `transaction_timeout`, and a container-side absolute
kill deadline derived from the SourceAdapter-attested credential expiry. The
hermetic core accepts only independent sealed/CLOEXEC credential memfds and
owns stable duplicates before adapter contact. Inline observation passwords,
ambient libpq configuration and production credential issuance are rejected;
the non-contract production path fails before container contact.

One disposable PostgreSQL 17.11 run used the exact retained production-original
HBA bytes, a real digest-pinned `pg_dump --snapshot`, and `pg_restore --list`.
It passed stale-FD denial, issuer death, stalled-reconciler takeover,
ambiguous issue/revoke acknowledgement, health drift and expired-lock fault
cases, then restored HBA and removed the exact container and volume. The
primary selected static suite passes 205/205; final focused suites, compile,
diff, frozen artifact binding and targeted Gitleaks pass. Architecture,
security and operations reviews all approve only an inert versioned artifact
rollout. Evidence:
`docs/e0-3-bot-b5-3-064a-scram-source-adapter-rehearsal.v1.json`.

Production was observed but not mutated: PostgreSQL remains 17.10, the reader
remains `NOLOGIN` with password `NULL` and zero sessions, HBA verification is
`EXACT`, container health is green and restart count is zero. Production
activation is a named `NO_GO`, not a standing project state: PostgreSQL 17.11
upgrade, watchdog/boot/abnormal-exit reconcile, a production Dump/Restore
supervisor and authenticated consumption of the disposable rehearsal evidence
are still absent. The exact next step is an inactive immutable artifact
publication followed by a separately bounded PostgreSQL 17.11 upgrade and
watchdog/reconcile slice; no `LOGIN` or refresh is authorized here.

## 2026-08-24 — 064A dormant runtime artifact publication

The reviewed closure from pushed commit
`abb22afc99e504cee29881d5e4b19ba15c0f343d` is published under
`/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/` as a root-owned read-only
versioned release. Its `candidate` symlink is intentionally inactive: no
systemd unit, timer or process consumes it, and no runtime command was invoked.
The 19-file import closure passes all 16 frozen-plan digest bindings.

Before/after production evidence is identical: PostgreSQL remains 17.10; the
same container remains healthy with restart count zero; the reader remains
`NOLOGIN`, password `NULL`, validity `NULL`, connection limit two and zero
sessions/advisory locks; HBA remains `EXACT` at SHA-256
`08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6`.
No database/HBA mutation, reload/restart, credential, refresh, customer-row,
money, migration or E4 action occurred. Evidence:
`docs/e0-3-bot-b5-3-064a-dormant-runtime-artifact-rollout.v1.json`.

The next bounded route item is a rehearsed PostgreSQL 17.11 upgrade plus
watchdog, boot and abnormal-exit reconciliation while preserving the dormant
role and exact HBA policy. Production `LOGIN` remains unauthorized until that
gate, authenticated rehearsal-evidence consumption and a concrete production
Dump/Restore supervisor all pass.

## 2026-08-24 — 064A production PostgreSQL 17.11 and dormant watchdog rollout

The separately bounded PostgreSQL prerequisite is deployed on
`E0 → E0.3 → B5.3 → 064A`. Production now runs the exact linux/amd64
PostgreSQL 17.11 digest. The forward transition and a controlled
force-recreate restart each produced a new container ID while preserving the
cluster system identifier, page checksums and exact HBA SHA-256. The
`obsidian_b64_snapshot_reader` role remains `NOLOGIN`, password-absent, limited
to two connections and has zero sessions. A root-owned crash-resumable journal
is rebound under the same advisory/host locks, and the enabled systemd timer
repeatedly verifies dormant authority. All seven consumers are active after a
bounded maintenance interlock was removed; payout processing was restored
last, `systemctl --failed` is empty and the restore window has no
error-priority consumer entries.

Rollback evidence is root-only and includes a fresh custom-format logical
dump, a clean-shutdown physical archive, the exact PostgreSQL 17.10 image and
unit/config preimages. A restored physical clone passed 17.10, forward 17.11
and reverse 17.10 transitions; a fresh logical restore produced the expected
54 public tables and two functions. The literal systemd lifecycle integration
also passed 17.10 → 17.11, forced restart, orphan-authority reconciliation and
reverse 17.10 without changing the production tuple.

Two failed attempts were contained and converted into regression controls.
The initial disposable integration reused production Compose labels and
interrupted the live PostgreSQL unit; production recovered on the exact
volume/system identifier, contract labels were isolated and the test now
asserts the exact production tuple before and after. The first production
staging start then retained the old 17.10 container because Compose had not
been told to recreate it, while the timer also exposed an incomplete Python
import closure. No reader authority was enabled. Units now require the full
import closure and use `--force-recreate` in both directions. During that
recovery `relay-fastapi` auto-started once and an external cancellation request
was rejected with HTTP 400; no successful provider outcome is claimed and no
customer row payloads were inspected. Consumers were subsequently held behind
a runtime condition until the final gate passed.

Evidence:
`docs/e0-3-bot-b5-3-064a-postgres-17-11-watchdog-rollout.v1.json`. Production
`LOGIN`, credential issuance and refresh remain blocked by named
prerequisites, not by a standing project state. The next canonical item is a
concrete bounded production Dump/Restore supervisor plus authenticated exact
consumption of the disposable rehearsal evidence while the reader remains
dormant. Only a later separately reviewed activation slice may change LOGIN.

## 2026-08-24 — 064A dormant Dump/Restore supervisor preflight rollout

A root-owned production supervisor preflight is deployed from immutable commit
`2d662b2481347f7a4c88b0d1847c82635c2717b5`. The enabled six-hour systemd timer
validates the exact historical disposable-rehearsal evidence, its original
16-artifact closure, the digest-pinned PostgreSQL 17.11 client, synchronized UTC
time and the current dormant watchdog result. Both rollout executions returned
`DORMANT_SUPERVISOR_VERIFIED_AUTH_PENDING` with exit zero. The supervisor has no
activation CLI: it did not call the credential issuer, dump or restore, and it
did not read customer rows or mutate PostgreSQL/HBA.

The evidence-only verifier accepts only a pinned production keyring and two
independent Ed25519 signatures over the exact evidence, plan and closure
digests, with all LOGIN/credential/refresh/migration/money/action authority
false. The implementation and adversarial 064A regression pass 158/158;
Python compilation, systemd verification, diff and targeted Gitleaks pass.
Production remains PostgreSQL 17.11 healthy with the same container/system
identifier, reader `NOLOGIN`, credential absent, seven consumers active, no
failed units and no rollout-window error-priority entries. Evidence:
`docs/e0-3-bot-b5-3-064a-dump-restore-supervisor-rollout.v1.json`.

The gate remains `IN_PROGRESS`: a production 064A keyring, fresh authenticated
owner/reviewer evidence-only acceptance and independent review are absent. The
next canonical item is to obtain and independently verify those exact inputs,
then deploy them as a separate non-activating slice and require
`AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED`. This does not authorize LOGIN,
credential issuance, a dump/restore execution entrypoint or refresh.

## 2026-08-24 — 064A authenticated evidence signing readiness rollout

The dormant supervisor now runs from immutable implementation commit
`30114cbb7ce25d49b3313d04f6564903bc29074a`; systemd points to it through
commit `6a06086dde3575439cd0b30e1fae82467b154bc2`. Its evidence keyring contract
is upgraded to v2 with deterministic public-key-derived key IDs, a seven-day
maximum validity interval, an explicit revocation snapshot, rejection of an
active revoked signer and an independently supplied expected keyring digest.
The offline ceremony generates encrypted Ed25519 private keys only on their
originating devices, publishes public entries, builds the exact keyring and
unsigned acceptance, emits one detached signature per independent role and
assembles only after the production verifier accepts the complete package.
E4 keys are not silently reused.

The focused 064A/snapshot regression passes 165/165; Python compilation,
systemd verification, diff and Gitleaks pass. The deployed oneshot returned
`DORMANT_SUPERVISOR_VERIFIED_AUTH_PENDING` with exit zero. PostgreSQL remains
healthy on the same image, container and cluster identifier; the reader is
`NOLOGIN` and credential-absent, all seven consumers are active, no units are
failed and no 064A-related error-priority entry occurred. Evidence:
`docs/e0-3-bot-b5-3-064a-authenticated-evidence-signing-rollout.v1.json`.
The first Termux `--help` probe exposed a false error receipt caused by catching
`SystemExit`; commit `bfe53faaba17a4e9e0cca83024f602d9d59c965a` narrows the
handler to ordinary exceptions and adds a zero-exit regression. No key was
created during that probe.

The gate remains `IN_PROGRESS` because the two dedicated 064A public entries,
fresh pinned keyring and detached owner/reviewer signatures do not exist yet.
The next canonical item is to receive only those public entries from separate
offline devices, compare their hashes through a second channel, create the
short-lived exact payload and obtain both detached signatures. The completed
package may then be deployed only as a non-activating slice while the reader
stays dormant. This step grants no LOGIN, credential, refresh, mutation,
migration or money authority.

## 2026-08-24 — 064A dedicated public-key intake and unsigned acceptance

The dedicated 064A owner and independent-reviewer public entries were received
without either private key or passphrase. The strict production decoder accepts
both entries; their key IDs, identity IDs and trust domains are pairwise
distinct. An explicit empty revocation snapshot, registry-version-one v2
keyring and exact two-hour unsigned evidence-only acceptance were created. The
keyring digest is
`a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c`;
the acceptance digest is
`b482504a2166b1e410e6a4b97829dbfcf818807b872f6ca73530a6d130dd54ba`;
all eight authority fields are literal `false`. The secret-free signing-request
archive SHA-256 is
`7616d3de896eb33201a59259c19befd8b2d7a552c605807488ae3a5e425352c1`.

The exact owner/reviewer ceremony and supervisor focused suite passes 21 tests;
one systemd-bus test is skipped inside the test sandbox, while host read-only
checks show both timers active, no failed units and watchdog
`DORMANT_VERIFIED`. No package was deployed, no signature exists yet, and no
credential issuer, dump, restore, customer-row read or production mutation was
invoked. Evidence:
`docs/e0-3-bot-b5-3-064a-public-key-intake-unsigned-acceptance.v1.json`.

E0.3 remains `IN_PROGRESS`. The one next canonical item is to obtain exactly
one detached signature from each originating offline device before the
acceptance expires at `2026-08-24T10:08:02Z`, assemble and verify the package
against the externally pinned keyring digest, then deploy only that completed
non-activating package and require `AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED` while
the reader remains `NOLOGIN` and credential-absent. An expired payload must be
replaced, not reused.

## 2026-08-24 — 064A authenticated evidence acceptance rollout

The two detached Ed25519 signatures validate as the distinct accountable-owner
and independent-reviewer roles over the exact current acceptance and pinned v2
keyring. Assembly and independent verifier passes returned
`AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED`. The signed acceptance raw-file SHA-256
is `d592e24c1095ed16019ed306b1e6431909d0d6ef355456d231698cd6bd09134f`;
the keyring digest remains
`a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c`.
Neither private key nor passphrase entered the server.

The completed public package is deployed under an exact digest-named,
root-owned read-only evidence directory. A separate no-timer systemd one-shot
from commit `60bc058` returned
`DORMANT_SUPERVISOR_VERIFIED_AUTHENTICATED_EVIDENCE` with exit zero. A
pre-deploy review caught that pinning the two-hour acceptance to the existing
six-hour timer would create deterministic post-expiry failures; the earlier
candidate commit `1357640` was never deployed. The recurring dormant supervisor
was preserved, remains enabled/active and still returns its expected
`AUTH_PENDING` result without consuming short-lived evidence.

Focused verification passes 21 tests with one test-sandbox systemd-bus skip;
systemd verification, compilation, diff and changed-scope secret scans pass.
Production PostgreSQL remains 17.11; watchdog is `DORMANT_VERIFIED`, reader is
`NOLOGIN` and credential-absent, five required services are active and failed
units are empty. The supervisor invoked no credential issuer, dump or restore,
read no customer rows and made no production mutation. Evidence:
`docs/e0-3-bot-b5-3-064a-authenticated-evidence-acceptance-rollout.v1.json`.

An unrelated exact duplicate `/swapfile` line in `/etc/fstab` emitted two
systemd-generator error-priority messages during daemon-reload. Swap remains
active and no unit is failed; this slice did not change `fstab` and has no
authority to remediate it.

The authenticated evidence-consumption prerequisite is `VERIFIED`; E0.3 remains
`IN_PROGRESS` because this acceptance explicitly grants no activation or
refresh authority and the production execution entrypoint intentionally does
not exist. The one next canonical item is code-first implementation and
disposable rehearsal of a separate fail-closed activation entrypoint. It must
require a new activation-specific owner/reviewer decision and may not infer
`LOGIN`, credential, refresh, mutation, 064B or 064D authority from this
evidence-only package.

## 2026-08-24 — 064A activation boundary and disposable full-lifecycle rehearsal

The separate activation-specific boundary is now project code. Its plan,
decision and receipt schemas use an Ed25519 domain distinct from authenticated
evidence acceptance. A valid decision must bind the exact target, legacy
accepted-evidence prerequisite, current live artifact digests, one run, a
180-second credential TTL, 150-second work deadline, reserved 30-second cleanup
window, 16 MiB archive ceiling, disposable restore equality and post-close
dormant verification. The evidence-only acceptance cannot parse or authorize
this decision.

The durable journal atomically claims the decision and permits one attempt with
no retry. `CLAIMED`, `RUNNING` and `HOLD` abnormal states reconcile only to
`RECONCILED_HOLD`; a cross-process lock prevents the reconciler racing a live
runner. Production consumption additionally requires the internally observed
synchronized trusted clock. The CLI deliberately verifies packages only and
registers no production executor.

A real disposable PostgreSQL 17.11 rehearsal completed the entire bounded
lifecycle with synthetic activation-only owner/reviewer keys: short-lived SCRAM
credential issue, exported snapshot, pinned `pg_dump`, distinct read-only-root
tmpfs restore, equality across all 54 table fingerprints and 13 catalog
sections, source close, credential revoke, container/workspace/archive cleanup
and dormant post-verification. The journal closed, the same decision replay was
rejected before a second executor call, and receipt SHA-256 is
`ebb45b20515124ef7217016b25502a15fcfd78b0e4bb847404c1ad183d2bb09b`.
The disposable container, volume, archive and temporary HBA copy were removed.

Focused regression passes 164 tests with one test-sandbox systemd-bus skip;
the standalone activation suite passes 30/30, compilation and diff checks pass,
and targeted secret scans find no leaks. Final production read-only checks show
PostgreSQL healthy with zero restarts, reader `NOLOGIN`, credential absent, zero
reader sessions and unchanged deployed HBA SHA-256
`08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6`.
No production database or configuration mutation occurred. Evidence:
`docs/e0-3-bot-b5-3-064a-activation-entrypoint-rehearsal.v1.json`.
Implementation commit `82531d0ccdd290cf286cad0980943cdcda10f47c` is
pushed to `master`.

E0.3 remains `IN_PROGRESS`: the production executor intentionally does not
exist and no activation package or activation-specific human signatures were
created. The one next canonical item is an independently reviewed inert
production executor plus no-contact rehearsal, followed by a fresh exact
activation signing package. The evidence-only package must not be promoted or
reused, and production activation remains unauthorized.

## 2026-08-24 — 064A inert production-executor immutable rollout

The next code-first slice is complete without creating a production execution
surface. The activation-v2 boundary now binds a single executor implementation
to a process-local one-use capability, exact target and derived plan, fixed
production roots, global watchdog interlock and two durable no-retry journals.
The dump container is network-none and reaches only an exact Unix proxy into
the attested source netns. Source table/catalog fingerprints are taken inside
the exported MVCC transaction; restore SQL connects through a held,
PID-rebound socket-directory FD. Normal and recovery workspace deletion is
inode-checked and fsync-ordered. Resource recovery enters `HOLD` before cleanup,
is idempotent after `RECONCILED_HOLD`, treats dangling entries as present and
must return an exact resource receipt before the outer journal can reconcile.

The final exact-contract disposable PostgreSQL 17.11 lifecycle returned
`CLOSED`, rejected replay with one executor call, kept the concurrent watchdog
at `ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED` and ended at reader
`NOLOGIN`, credential absent and zero sessions. Receipt SHA-256 is
`81af9379fc6efdc1a8799d600c27c54e93d75bcb05b34b71a981ac6784ddcccb`.
Focused regression passes 215/215; compile, diff, targeted secret scans and
three independent latest-byte reviews pass. Disposable containers, named
volume, workspace/archive and temporary HBA copy were removed.

Commit `bc34b7ea37df75dc30e18f82a25b5688e013413e` is pushed and its
2151 blobs are published under the exact root-owned read-only, unreferenced
release directory
`/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/bc34b7ea37df75dc30e18f82a25b5688e013413e`.
No mutable copy, current pointer, unit, timer, state root, signing package,
daemon reload, start or restart occurred. Production PostgreSQL/container/HBA,
dormant reader state and existing timers are unchanged. Evidence:
`docs/e0-3-bot-b5-3-064a-production-executor-inert-rollout.v1.json`.

E0.3 remains `IN_PROGRESS`, and production activation is a concrete `NO_GO`.
The next canonical item is cleanup-only cold recovery bound to an existing
signed package and journal but incapable of execute/lease authority. That slice
must also close the workspace create-to-durable-inode window and define one
non-contradictory signed effective-plan semantics. Only afterward may the
updated dormant watchdog and a fixed-argument, hard-timeout, no-retry launcher
be separately rolled out. Do not create fresh production activation signatures
until those prerequisites pass independent review.

## 2026-08-24 — 064A cold-recovery and effective-plan inert rollout

The cleanup-only recovery prerequisite is complete in project code and an
unreferenced immutable release. An exact historical activation package is
reverified at its signed issuance instant, including its current artifact
closure, before it can reconcile an existing exact journal after decision or
keyring expiry. Its sealed recovery capability is rejected by both execution
and credential-lease boundaries. It can only move incomplete resources through
the existing fail-closed cleanup path to `RECONCILED_HOLD`; it cannot retry the
operation.

There is now one normalized signed effective plan: the dump container is
network-none and reaches only the exact Unix proxy. The old hardened plan is a
deterministic compatibility projection, not a second contradictory signed set
of assertions. Before workspace creation, the resource journal durably records
an exact absent-name preflight and the fixed parent device/inode. Cold cleanup
of an inode-not-yet-registered workspace requires that intent, the same bound
parent, strict owner/mode/file allowlists and held-inode removal evidence;
preexisting, foreign or swapped objects remain untouched and fail closed.
Docker auto-remove observation uses one real two-second deadline shared across
all exact references, and each inspect receives only the remaining budget.

The final exact disposable PostgreSQL 17.11 run closed the normal journal,
supervised the live lease through the watchdog, rejected replay without a
second executor call, then recovered a separate pre-inode workspace after both
the decision and keyring had expired. Cold state ended at
`ACTIVATION_RECONCILED_HOLD`; the reader ended `NOLOGIN`, credential-absent and
session-free. Receipt SHA-256 is
`03446838955a2d8e6e09676762f6de55e9868c79d12d2d5ffb7f9c319669cd58`.
Focused regression passes 180/180 and the full related set passes 237/237;
compile, diff and staged secret scan pass. Architecture, security and
operations latest-byte reviews report GO for this inert release with no P0/P1.

Commit `ddc591beb815036c0fb13c0fedc880d38f8b6c63` is pushed. Its 2152 Git blobs
match the root-owned read-only release directory
`/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/ddc591beb815036c0fb13c0fedc880d38f8b6c63`.
It is unreferenced: the inactive `candidate` pointer remains on
`abb22afc99e504cee29881d5e4b19ba15c0f343d`; no mutable copy, unit, timer,
state root, daemon reload, service start/restart or signing package was created.
Production remains healthy on the same container/image with zero restarts,
exact HBA, dormant reader, zero reader sessions, healthy existing timers and no
failed units. Evidence:
`docs/e0-3-bot-b5-3-064a-cold-recovery-effective-plan-inert-rollout.v1.json`.

E0.3 remains `IN_PROGRESS`, and production activation remains a concrete
`NO_GO`. The next canonical item is an updated dormant watchdog that can invoke
only the new cleanup-only recovery orchestration for an existing exact package
and journal. After that, separately implement and review a fixed-argument,
hard-wall-timeout, no-retry production launcher. Fresh production activation
signatures remain forbidden until both prerequisites pass.

## 2026-08-24 — 064A dormant-watchdog cleanup-recovery rollout

The updated production watchdog is deployed from immutable implementation
commit `12e0d1c018eacd7d9a1a59c4cd01308bb534ef6d`; all 2153 Git blobs match the
root-owned read-only release. Unit pin commit
`dcb76b5e7599f8a69ecce52900ffcbd24ee5bcf3` is pushed. The timer oneshot alone
uses explicit `--cleanup-recovery`; PostgreSQL `ExecStartPost` remains a
dormant-only pass and was only repinned to the same immutable watchdog bytes.
PostgreSQL was neither started nor restarted during rollout.

Recovery accepts only the fixed root-owned request/package paths and an exact
existing production journal. Package-without-request, request-without-journal
and terminal journals cannot create cleanup authority; terminal/no-journal
paths do not require trusted time. `CLAIMED` or `RUNNING` is durably moved to
one no-retry `HOLD` before cleanup. The sealed recovery capability cannot
execute, issue a lease, dump or restore. Its passwordless local-admin attestor
requires exact container/image/PID/system identifier/HBA, dormant reader state,
zero sessions and idle runtime lock. Production runner and recovery both use
global-interlock-before-nonce-lock ordering, while journal discovery holds the
idle global interlock. A live activation at any boundary yields defer without
cleanup. Signed container-ID drift remains fail-closed/manual-only; this slice
does not claim host-restart/container-recreate recovery.

Focused regression passes 118/118 and the expanded related set passes 193/193
with one explicit Docker-upgrade opt-in skip. The disposable lifecycle closed
the normal journal and recovered a separate incomplete journal to
`ACTIVATION_RECONCILED_HOLD`; architecture, security and operations latest-byte
reviews report GO with no P0/P1. Compilation, diff, staged secret scan and
systemd verification pass; systemd reports only the existing unrelated xray
`nobody` warning.

The first immutable no-package oneshot and the first recurring timer tick both
returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`. Request, package and activation
state root remain absent. PostgreSQL kept the same MainPID, container ID/PID,
start time, image, system identifier and restart count zero; reader remains
`NOLOGIN`, password-absent and session-free with exact HBA. Timer is
enabled/active/waiting, failed units are zero, and candidate remains
`abb22afc99e504cee29881d5e4b19ba15c0f343d`. Exact rollback preimages are
retained under
`/var/lib/obsidian-exchange/deployment-preimages/e0-e0.3-b5.3-064a-watchdog-20260824T225527Z`.
Evidence:
`docs/e0-3-bot-b5-3-064a-dormant-watchdog-cleanup-recovery-rollout.v1.json`.

E0.3 remains `IN_PROGRESS`, and production activation remains a concrete
`NO_GO`. The next canonical item is a separate fixed-argument,
hard-wall-timeout, no-retry launcher with independent review. Do not create or
sign a fresh production activation package until that launcher prerequisite is
complete.

## 2026-08-25 — 064A production-launcher inert rollout

The separate launcher prerequisite is complete. Activation plan and decision
schemas are v3, and their exact artifact closure now includes both launcher and
watchdog bytes. Before touching the observation credential the fixed launcher
requires an exact-empty production activation root; the same preflight repeats
under the global interlock before a nonce can be claimed. A parent supervisor
permits one child attempt, blocks inherited termination signals across fork,
uses PDEATHSIG plus a post-setsid readiness handshake, terminates the entire
process group and enforces an exact 180-second outer wall with no retry.

The real disposable PostgreSQL 17.11 rehearsal closed the normal lifecycle,
rejected replay without a second executor call, supervised the live lease and
recovered both cold-expired and hard-killed incomplete state to
`ACTIVATION_RECONCILED_HOLD`. Hard-kill process-group termination was observed;
automatic recovery attempted once and did not re-execute. Focused regression
passes 164/164; diff, staged secret scan and systemd verification pass. Three
independent latest-byte reviews report GO with no P0/P1.

Implementation commit `34bc167ebf192103f588524b521713ab588245e3` and pin commit
`2117e14a8bda531719f671b611f6c7f9edc1ffbc` are pushed. All 2157 Git blobs match
the root-owned read-only immutable release. The static launcher, recurring
watchdog and PostgreSQL dormant `ExecStartPost` all resolve to that exact
release. The launcher is loaded/inactive/static and was not started;
PostgreSQL was not restarted. A manual v3 watchdog tick and a subsequent timer
tick both returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`. Timer, PostgreSQL,
container, exact HBA and dormant reader invariants are healthy; request,
package and activation state remain absent. Evidence:
`docs/e0-3-bot-b5-3-064a-production-launcher-inert-rollout.v1.json`.

E0.3 remains `IN_PROGRESS`, and production activation remains a concrete
`NO_GO` only because a fresh exact v3 package and two independent external
owner/reviewer signatures are absent. The next canonical item is that fresh
secret-free signing handoff and ceremony. Old evidence-only and v2 packages
must not be promoted or reused.

## 2026-08-25 — 064A production activation signing-readiness rollout

The external-signature boundary is now anchored before any short activation
decision exists. Implementation commit
`8231d1ec61345118b184163e912abb63712fea0a` adds an exact production activation
trust registry, domain-separated activation key IDs, proof that each retained
evidence key ID derives from the same public key, and an exact production
keyring projection. A self-declared identity, key, revocation list or registry
version cannot become production authority. The v3 ceremony builds
deterministic secret-free offline and request archives, accepts no caller-
controlled target/time/nonce/hook/release, verifies each detached signature
before root-only import, and invokes the immutable verifier before assembly.
Assembly creates no runtime request and starts no launcher.

Pin commit `176893d808d348b8a8bbda0c017c28a2e7806065` and the implementation
commit are pushed. Both root-owned read-only releases have all 2162 Git blobs
verified. The three installed systemd units point at the exact implementation
release; PostgreSQL was not restarted and the launcher remains inactive/static.
The post-pin watchdog returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST` with the
same container, PID, start time, system identifier, exact HBA, restart count
zero and dormant credential-absent reader. The deterministic 235520-byte
offline kit SHA-256 is
`1476cf4d0136ed9c0f57f9fb16c8e391b8d7d492e0c7c1e650199fa8c8b39774`.

Focused activation/ceremony tests pass 59/59 and the pin/deployment subset
passes 80/80. The expanded unit scope passes 363 tests; seven pre-existing
watchdog ownership tests cannot run on this sandbox filesystem because chown to
uid/gid 70 returns `EINVAL`. A real disposable PostgreSQL 17.11 lifecycle
closed normally, rejected replay without a second executor call, supervised
the live lease, and reconciled cold-expired and hard-killed states to HOLD;
receipt SHA-256 is
`cd78ac9fd910f6cb2458e1eff664a2bb1b59f2ea0b6e419266927e7e62840a13`.
All disposable resources are absent. Gitleaks, diff check, compilation and
systemd verification pass; independent agent review was unavailable under the
current orchestration restriction and was not fabricated. Evidence:
`docs/e0-3-bot-b5-3-064a-production-activation-signing-readiness-rollout.v1.json`.

E0.3 remains `IN_PROGRESS`, and activation is now `BLOCKED_OWNER`: both
external signer devices must first receive and independently verify the static
secret-free kit. Only when both are ready may one fresh 15-minute v3 request be
created and signed. No request, production credential, dump, restore,
customer-row read, launcher start, 064B/064D action or E4 action occurred.

## 2026-08-25 — 064A Termux signing closure and inert authenticated decision

Both independent signer devices verified the original secret-free kit. The
first real online preflight failed closed because the ceremony expected an
`actionAllowed` watchdog field that the deployed watchdog does not emit; its
actual non-escalation field is `authorityIncreased:false`. Commit
`aafcd312ac41406f384317b23387e3f46efd687a` aligns the exact contract and adds
accept/missing/true regression coverage. No plan or short decision existed at
that failure point.

The first offline signing attempt then proved that Android/Termux denies the
hard-link publication used by the signer. OpenSSL verified the encrypted key
and passphrase, the derived reviewer public-key DER SHA-256 matched the pinned
profile, and a direct filesystem probe returned `Permission denied` for the
hard link. Commit `b36c3ebc4ec80526ed3a7abf4b9fb6b125e0d822` changes only
offline result publication to exclusive final-name creation, full write/fsync,
mode/owner/link/size verification and cleanup on failure; online/server output
keeps the existing hard-link atomicity. Focused ceremony/launcher/deployment
tests pass 39/39, compile/diff/staged secret checks pass, and both immutable
fix releases match all 2163 Git blobs. Both devices independently verified the
replacement kit SHA-256
`e77eb3adad4965ed78567b1eb3f3683a6ad3822c874ade9680277d0a1b06fac9`.

The exact fresh decision SHA-256
`de644329e9f428007e06d138a962d8980a133058376daa2732d4c88bb001a0be`
then received valid detached signatures from the accountable owner and the
independent reviewer. Both imports, assembly and immutable re-verification
passed with `SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED`; completed raw-file
SHA-256 is
`050a88bee310e0de0dfe72619e7f26d4ce17e75884f0f4aeecb5141060725ac1`.
No runtime request/package/state, credential, dump, restore, customer-row read
or launcher start occurred.
The decision then expired unused. Post-expiry verification returns
`INSUFFICIENT_DECISION_WINDOW_REMAINING`; the recovery package/request, launch
request and activation root remain absent, launcher is inactive, both safety
timers and PostgreSQL are active, failed units are zero, and the dormant reader
remains `NOLOGIN`, credential-absent and session-free.

`BLOCKED_OWNER` is cleared, but E0.3 remains `IN_PROGRESS`: no reviewed
production CLI currently commits the verified coordination artifacts into the
exact watchdog recovery package/request, launcher commit request and four
empty activation-state roots. Manual assembly is forbidden and the inert
signed decision is non-reusable after expiry. The next canonical slice is that
fixed-scope committer with partial-publication rollback, fault injection,
disposable rehearsal and inert production rollout before any new signatures.
Evidence:
`docs/e0-3-bot-b5-3-064a-termux-signing-inert-decision.v1.json`.

## 2026-08-25 — 064A atomic runtime-package committer inert rollout

Implementation commit `e466268d9c518c7025f3b6c5b2f3d23407e5a4e9`
adds the missing no-argument runtime-package committer to the signed activation
artifact closure. It accepts only the fixed root-only coordination directory,
re-verifies the two-party v3 decision, trusted time, live artifact closure,
exact dormant production tuple and absent runtime paths, then stages and
publishes the recovery package, four empty activation roots, recovery request
and launch request in that order. Directory publication uses
`renameat2(RENAME_NOREPLACE)` and marker publication uses no-replace hard links.
It never invokes the launcher and exposes no caller-controlled target, time,
release, nonce or hook.

Six explicit boundary faults, four post-publication fsync faults and a marker
unlink fault prove exact rollback. An existing target is preserved. Immutable
release tests pass 20/20; the non-Docker 064A cluster passes 291/291, full
watchdog regression 52/52 and focused pin tests 59/59. Compile, diff, staged
gitleaks and systemd verification pass. Implementation and pin release
`8c31c55af2e0994991fe73e00c333b749dd5f611` each match all 2166 Git blobs.

The three installed systemd units now pin the immutable implementation. No
service was started or restarted. Launcher remains inactive, both safety
timers and PostgreSQL remain active, failed units are zero, all runtime commit
paths remain absent, and the reader remains `DORMANT_VERIFIED`, `NOLOGIN`,
credential-absent and session-free. The old signed decision is rejected with
`INVALID_ACTIVATION_ARTIFACT_SET` because it did not bind the committer and is
non-reusable.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER`. The new 266240-byte secret-free
kit SHA-256 is
`0b11ef3a6f1cd071a7ed78053c9a6470aad104e88d4fbc63723aacdf541f66c0`.
Both external devices must independently verify it before one new 15-minute v3
request is created. Evidence:
`docs/e0-3-bot-b5-3-064a-runtime-package-committer-inert-rollout.v1.json`.

## 2026-08-25 — 064A activation-parent contract inert rollout

The next exact two-party decision failed closed before runtime publication.
The deployed committer required a root:root non-group-writable parent, while
the host production activation parent was the legacy shared
`root:obsidian-payout 2770` directory. Decision SHA-256 `9eee5a12...` expired
after `RUNTIME_COMMIT_PARENT_UNSAFE`; it and both signatures are non-reusable.
No runtime package/request/state, credential, dump, restore, customer-row read
or launcher start occurred.

Implementation commit `f10098625854aefcdfbaadf8f9d75e003f298497` now binds
the exact host owner/group and requires sticky+setgid mode `3770`. Sticky
semantics preserve group inheritance but prevent a payout-group member from
removing the root-owned activation tree after publication. Pin commit
`d67171c7f5b1930b75cb3198a8764be7c3dc6073` targets that implementation. A
restricted-namespace GID remap initially suggested `65534`; the exact host
preflight rejected those candidate releases before mutation, and they remain
unreferenced/superseded.

Both final immutable releases match 2167 Git blobs. Focused tests pass 60/60,
expanded final 064A tests 135/135 and host-namespace watchdog regression 52/52.
Production mode changed reversibly from `2770` to `3770`; the three units pin
the final implementation. PostgreSQL kept the same PID/start tuple and restart
count zero, the launcher start timestamp remains zero, and the post-rollout
watchdog returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`. Seven consumers and
both safety timers are active, failed units are zero, all runtime commit paths
are absent and the reader remains dormant/credential-absent/session-free.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER`. The new 266240-byte secret-free kit
SHA-256 is
`1e24f747e5bca8fb9ae7f0cb3b1b020958be5d25dec4ce8925308853d7de9b35`.
Both external devices must independently verify this exact kit before exactly
one new 15-minute request is created; no prior decision or signature may be
reused. Evidence:
`docs/e0-3-bot-b5-3-064a-activation-parent-contract-rollout.v1.json`.

## 2026-08-25 — 064A fresh request owner-only abort and custody blocker

Both signer workflows reported exact archive and internal-checksum `PASS` for
the parent-contract kit. One fresh 15-minute v3 request was then created with
decision digest `1d868150...`. The owner created a local detached signature,
but it never reached the server; no reviewer signature was produced or
imported. Only 92 seconds remained above the mandatory five-minute commit
floor, so coordination was archived and the short transfer link removed. No
runtime package/request/state, credential, dump, restore, customer-row read or
launcher start occurred. The request, nonce and local signature are forbidden
from reuse.

The owner-terminal file inventory also exposed both owner and reviewer private-
key files. The reviewer key was not read or used, but co-residency means two
valid signatures would not prove independent device/trust-domain custody.
E0.3 therefore remains `IN_PROGRESS`/`BLOCKED_OWNER`. The next canonical item
is reviewer-key rotation on a genuinely separate controlled device, explicit
revocation of the co-resident key, pinned trust-registry update, new secret-
free kit and two-device verification before another short request. Evidence:
`docs/e0-3-bot-b5-3-064a-fresh-request-owner-only-abort.v1.json`.

## 2026-08-25 — 064A secret-free reviewer-key rotation kit

Pushed commit `e9f4109dd4661b449bbae7a56c6b9bac397725b4` implements a
deterministic fail-closed builder for the narrow custody-remediation handoff.
It runs only from an exact root-owned read-only immutable release, includes
only the public generation dependencies, README, manifest and checksums, and
creates a new mode-0600 archive without overwrite. It pins the old reviewer
key IDs and the replacement identity/trust-domain labels, but contains no
private key, passphrase, credential or runtime request and grants no authority.

Eight focused tests pass; compilation, diff, staged gitleaks, archive checksums
and manifest self-hash pass. The immutable release matches all 2171 Git blobs.
The 122880-byte handoff is `/root/rot2.tar`, SHA-256
`358da6857c1c5e61ebbe16acf782950bd368a46eb59626467d25cef5ef3f3a75`.
Production units and pins were not changed. PostgreSQL retained MainPID
`3136948`, active timestamp and restart count zero; launcher start timestamp is
zero, runtime/coordination paths are absent and failed units remain zero.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER`. Exact next: on a genuinely separate
controlled reviewer device containing no owner key and no prior reviewer key,
verify this kit, generate the encrypted replacement locally and return only
its public profile plus SHA-256. Server-side validation, explicit old-key
revocation, pinned trust-registry update and a rebuilt/two-device-verified
activation kit must precede any new request. Evidence:
`docs/e0-3-bot-b5-3-064a-reviewer-key-rotation-kit.v1.json`.

## 2026-08-25 — 064A reviewer trust rotation inert rollout

The separate reviewer workflow returned only a 399-byte canonical Ed25519
public profile, SHA-256
`3e9a8dc12bd7f11bbc0ddc8048095710bc9670090daaf5c66b11c9417f45ea61`.
Project parsing validated its role `INDEPENDENT_REVIEWER`, identity
`reviewer_independent_2026_r2`, trust domain `reviewer_device_02`, evidence key
ID `b64e_cd9e...` and derived activation key ID `b64a_4c31...`. No private key
or passphrase was received.

Pushed implementation commit `dd1934f865381ae139b4cb6037d157ff34d825b2`
advances the exact pinned registry to version 2 and chains the prior semantic
registry hash. Both old reviewer activation/evidence IDs are explicitly
revoked with reason `CO_RESIDENT_PRIVATE_KEY_CUSTODY_INVALID`; the unchanged
owner and new reviewer are the only active roles. The loader derives both
public-profile digests from active entries and rejects provenance, digest,
revocation, identity, trust-domain or source-evidence drift. Pushed pin commit
`8670bbdf058c5263c21b6f7290cc35c9fabc3a96` points the three inert production
units at that implementation. Both immutable releases match all 2173 Git
blobs. Registry/ceremony tests pass 67/67, expanded non-Docker 064A tests
298/298 and pin-focused tests 108/108; compile, JSON, diff, staged gitleaks and
systemd checks pass, with only the unrelated existing xray/nobody warning.

The rollout saved exact preimages, atomically replaced only the three unit
files and daemon-reloaded systemd. No service was restarted and the launcher
was not started. PostgreSQL retained MainPID `3136948`, active timestamp and
restart count zero; the watchdog returns
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST`, seven consumers and both safety timers
are active, failed units are zero, and coordination/runtime paths remain
absent. The replacement 276480-byte activation kit is `/root/a8670.tar`,
SHA-256 `fe12dd66722ca8b4b9a8a6c0bf805f341ef618a12c6fb20e58933cbab42c3002`;
all internal checksums and manifest self-hash pass, owner profile is unchanged
and the new reviewer profile is exact.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER`. Both external signer devices must
independently verify this exact kit, and the reviewer must confirm its embedded
profile SHA matches `3e9a8dc1...`. Only after both PASS reports may one fresh
15-minute request be created; all prior requests, nonces and signatures remain
forbidden from reuse. Evidence:
`docs/e0-3-bot-b5-3-064a-reviewer-trust-rotation-rollout.v1.json`.

## 2026-08-25 — 064A registry-v2 request path-preflight abort

Both external workflows reported exact replacement-kit/profile checks. One
fresh registry-v2 request was created with decision digest `1232c5d8...`, but
no signature was created: the pasted digest lost its final character into a
separate shell command, and the assumed `$HOME/a8670` ceremony path was absent
on both devices. With 467 seconds remaining above the mandatory commit floor,
server coordination was archived and the short request path removed rather
than rushing path repair and two signatures. The request, nonce and decision
are non-reusable; runtime paths remain absent and launcher was not started.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER`. Exact next: before creating another
request, locate or freshly extract the verified kit into a known absolute path
on each signer device and prove the ceremony script plus role-specific public/
private files exist. Both devices must report `PATHS_READY`; only then create
one new request. Evidence:
`docs/e0-3-bot-b5-3-064a-registry-v2-request-path-abort.v1.json`.

## 2026-08-25 — 064A explicit single-owner v4 inert rollout

The owner chose an explicit `ACCOUNTABLE_OWNER_ONLY` activation model after
the reported reviewer device proved to share the owner boot identity and both
private-key paths. This deliberately reduces separation of duties but removes
the false independent-custody claim. Decision/signature domain v4, trust
registry v3 and a digest-pinned single-owner policy retire both reviewer
generations and reject all v3/two-party packages.

Pushed implementation commit
`006744f9ebdd9c80e93b9896f2dabc2f6f1d7e31`, pin commit `1711f49` and
bytecode-hardening commit `c94ad6a` are deployed inertly. The immutable release
matches all 2176 Git files. The non-Docker 064A regression passes 300 tests; a
real disposable PostgreSQL rehearsal returned
`DISPOSABLE_ACTIVATION_REHEARSAL_VERIFIED`, one executor call, journal
`CLOSED`, supervised live lease and successful cold/hard-kill recovery. Its
HBA rolled back byte-exact and all created disposable resources were removed.

Only the three unit files were replaced and systemd daemon-reloaded. No service
was restarted and the launcher was not started. PostgreSQL retained MainPID,
container PID, active timestamp and restart count zero; the timer returns
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST`, and coordination/runtime roots are
absent. The final 286720-byte owner-only offline kit is
`/root/obsidian-064a-single-owner-v4-offline-kit-006744f-preflight.tar`,
SHA-256 `012c53c82a6f53e360ed60947ea968504cada26b1e606fc42d63b25ddd0d59d6`.
It contains no reviewer profile, request, decision, signature or private key.
Pushed commit `5ef401a` adds an offline `preflight-owner-paths` command that
decrypts and matches the local owner key before request creation without
creating a signature.

E0.3 remains `IN_PROGRESS`/`BLOCKED_OWNER_PATHS_READY`. Exact next: verify one
absolute owner-device script/profile/private-key path and report
`OWNER_PATHS_READY`. Only then create one final fresh request and accept one
`ACCOUNTABLE_OWNER` signature. Evidence:
`docs/e0-3-bot-b5-3-064a-single-owner-v4-inert-rollout.v1.json`.

## 2026-08-25 — 064A signed v4 attempt reconciled HOLD

The fresh owner-only decision `14f6b0bf...` was imported, assembled and
committed, but the launcher stopped fail-closed before credential issuance.
The `3770` production parent propagated gid `986` to the private activation
root; the watchdog contract requires exact `root:root/0700`. Manual
cleanup-only reconciliation moved both journals to terminal
`RECONCILED_HOLD`; credential issuance is false, all temporary resources are
absent, customer rows were not read, HBA was unchanged and PostgreSQL did not
restart.

Corrected implementation commit `dee25d1b8b1aba6fc0e574a7bdb3ea0a220522e6`
rebinds the root with `fchown(0,0)` before `fchmod(0700)`. Immutable release and
unit pin commit `6c7fdc4` are deployed; 148 reconciliation tests, 63 pin tests
and the exact production-parent metadata preflight pass. E0.3 remains
`IN_PROGRESS_RECONCILED_HOLD_NO_RETRY`; the signature/nonce are consumed.
Next canonical slice is terminal-evidence archive/cleanup code and verification,
not another request. Evidence:
`docs/e0-3-bot-b5-3-064a-single-owner-v4-reconciled-hold.v1.json`.

## 2026-08-25 — 064A terminal evidence archive rollout

The reconciled owner-only run is now closed at the runtime-path boundary. A
new root-only archiver in pushed commit
`16fdc05168e20151f646cf4cb97746fbde809e69` verifies the exact historical
11-artifact signed closure from immutable release
`c6c3eaba1b78b06235741ce88e003162c35d4bcb`, while separately binding its own
operational immutable commit and SHA. This preserves verification of the
consumed signature without placing the later runtime-package-committer fix
inside that old signature domain and without requesting another signature.

All 2180 release blobs match, 12 archive and crash-prefix tests pass, and pin
commit `51c2f614df2e5eed3f1225d4831dc01e4e0857f9` is deployed. The three units
were daemon-reloaded without a service restart; PostgreSQL MainPID/container
PID/restart count stayed `3136948`/`3137013`/`0`. An earlier unreferenced
`0e9c3b4...` release was rejected before unit mutation when preflight exposed
the one historical committer digest difference.

After exact `RECONCILED_HOLD`, absent-resource and dormant checks, the four
runtime components were atomically renamed on the same filesystem into
`/var/backups/obsidian-exchange/b64-064a-terminal-evidence-v1/b64-064a-terminal-ZektkcmxVfBGwtHX5lnM03p9Y3OfJ2gm`.
Manifest SHA-256 is
`66cd11835f658845a15787230a4b58fdff665dba7800e3bdd82072064eb1576c`.
The root-only archive verifies idempotently, staging and all source paths are
absent, and evidence was moved rather than deleted.

The recurring watchdog now returns `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`;
the reader is `NOLOGIN`, credential absent and session-free. No activation,
credential issuance, customer-row read, HBA change, authority increase or
PostgreSQL restart occurred. E0.3 remains
`IN_PROGRESS_TERMINAL_EVIDENCE_ARCHIVED_NO_RETRY`: the consumed signature and
nonce cannot be reused, and this rollout grants no new request authority. A
later production attempt requires an explicit owner decision and fresh nonce.
Evidence:
`docs/e0-3-bot-b5-3-064a-terminal-evidence-archive-rollout.v1.json`.

## 2026-08-26 — 064A terminal archive v2 and exact release tree

Pushed commit `e725d49932107d128b1621b7bdb37e2d499872cb` closes the
post-terminal replay boundary for both `CLOSED` and `RECONCILED_HOLD`. Archive
publication is forbidden until trusted time reaches the signed decision
expiry. V2 staging binds expiry and archive authorization time, rechecks
trusted time before resume and rejects legacy staging; the completed v1 final
archive remains idempotently readable. `CLOSED` additionally requires and
archives its canonical digest-bound execution receipt. Row-read evidence is
tri-state: `CONFIRMED` for `CLOSED`, `POSSIBLE` for HOLD after credential
issuance and `NOT_READ` only for HOLD without credential issuance.

The ceremony now compares the complete sealed release directory against the
exact Git tree, including entry set, modes, owners, link counts, executable
bits and every blob. This check found untracked pytest/bytecode caches in the
previous `16fdc05...` directory, so it is no longer referenced. The clean
2181-blob release is deployed through pushed pin commit
`af64ee6492c3af17321ba05566297bb584f7ede6`. The three units alone were
replaced and daemon-reloaded; no service or PostgreSQL restart and no launcher
start occurred.

Expanded tests pass 192/192 and pin tests 88/88. A clean disposable PostgreSQL
17.11 lifecycle passed `CLOSED`, one-call/replay, live-watchdog, cold-expiry and
hard-kill recovery; receipt SHA-256 is
`916a18307f8d093316ecb1b571cb6908aa62444b305ca4887fb5f01df363c713`,
and all disposable resources were removed. The loaded production watchdog
returns `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`; MainPID/container PID/restart
count remain `3136948`/`3137013`/`0`, reader authority is dormant, runtime and
coordination paths are absent, launcher is inactive/static and failed units
are zero.

E0.3 remains `IN_PROGRESS`; a new production activation is `BLOCKED_OWNER`.
This slice authorizes no request, credential, signature, retry or launcher
start. Exact next canonical item: the accountable owner explicitly authorizes
or declines one fresh single-owner v4 production 064A attempt with a fresh
nonce. Evidence:
`docs/e0-3-bot-b5-3-064a-terminal-archive-v2-rollout.v1.json`.

## 2026-08-26 — 064A fresh owner attempt readiness

The accountable owner explicitly authorized one fresh single-owner v4
production attempt with a new nonce. Exact live preflight is green: the
PostgreSQL container and cluster identity are unchanged and healthy with
restart count zero; the snapshot reader is dormant, credential-absent and
session-free; HBA, customer-row reads and authority are unchanged; NTP is
synchronized; the watchdog timer is active/waiting, the launcher is
inactive/static with start timestamp zero, failed units are zero, and all
coordination/runtime paths are absent.

The tracked pin-level ceremony controller verified the full sealed e725 tree
and installed e725 units. It created a deterministic 286720-byte, 12-file
secret-free owner kit at
`/root/064A-activation-handoff-e725-20260826T0206Z/obsidian-064a-single-owner-v4-offline-kit-e725.tar`,
SHA-256
`8ed608174eeb8add80f80940674be4087a0190dc83438a7ad702115c197f9622`.
All internal checksums and the manifest self-hash pass; the manifest binds
implementation `e725d49`, trust registry `d42dbdc...`, and explicitly contains
no private key, passphrase, credential or runtime request. A diagnostic run of
the historical controller copy inside e725 correctly rejected the known
polluted superseded `16fdc05` release to which that older copy is self-pinned;
it created no output or authority.

No fresh plan, nonce, short decision, signature, coordination root, runtime
package, credential or launcher start exists. E0.3 remains `IN_PROGRESS` and
the exact blocker is now `BLOCKED_OWNER_PATHS_READY`. The one next canonical
step is an offline `preflight-owner-paths` report of `OWNER_PATHS_READY` from
the owner device using the exact new kit and existing encrypted owner key.
Only then may the server open one 15-minute signing request. Evidence:
`docs/e0-3-bot-b5-3-064a-fresh-owner-attempt-readiness.v1.json`.

## 2026-08-26 — 064A replacement hardening supersedes e725 readiness

This gate entry supersedes the preceding e725 readiness entry. The owner
authorization for exactly one fresh single-owner v4 attempt remains bounded,
but the e725 owner kit (SHA-256 `8ed60817...f9622`) is permanently
`SUPERSEDED_DO_NOT_USE` after final review identified crash-prefix gaps. No
short request, fresh nonce, decision, signature, credential, launcher start or
production data read was created from it.

Replacement code makes launch the sole authority marker and adds deterministic
hard-kill recovery for publication rollback, execution receipts and terminal
archive staging. The watchdog leaves a CLAIMED pre-launch prefix unchanged,
manual HOLD cannot consume an automatic-close residual receipt, archive
evidence requires its pre-existing execution lock and stable signed target,
and CLI receipts never claim that an uncertain published authority set is
absent. A single cross-module real-SIGKILL regression covers state publication,
nonmutating watchdog inspection, launch resume, terminal reconciliation and
archive publication. Final architecture, security and operations reviews pass
with no P0/P1/P2 finding. The unsandboxed affected/ceremony suite passes
333/333; the broader managed suite passes 491 tests with only seven uid-70
`chown` cases unavailable in its restricted namespace. The exact isolated
PostgreSQL 17.11 lifecycle returned
`DISPOSABLE_ACTIVATION_REHEARSAL_VERIFIED`, closed/replay-rejected the journal,
covered live-lease/cold/hard-kill recovery, restored HBA byte-exact and made no
production contact or mutation; its container and volume were removed. The
exact production evidence filesystem passes a cleaned
`O_TMPFILE + linkat + fsync` publication capability probe.

E0.3 remains `IN_PROGRESS`; the exact status is
`HARDENING_REPLACEMENT_ROLLOUT`. Next: immutable replacement release and inert
unit deployment. A replacement owner kit and exact `OWNER_PATHS_READY` report are
required before opening the single 15-minute request.

## 2026-08-26 — 064A crash-safe replacement rollout and owner paths gate

Implementation commit `fbcf49928f82d22d277521ab1e388f3aec63046d` is pushed
and published as an exact root-owned read-only 2185-blob release. Pushed pin
commit `3f348a840ca2826c4956dff00f99bbefceed2883` updates exactly three deployed
unit files; rollback preimages are retained. No service was restarted and the
launcher was not started. PostgreSQL retained the exact MainPID, container PID,
start time and restart count zero; a natural watchdog tick from the replacement
release returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST` with dormant reader,
absent credential, zero sessions and no authority/data/configuration effect.
Runtime and coordination paths remain absent.

The replacement secret-free owner kit is 348160 bytes with SHA-256
`fb94e7096587e7aed9a297db490df6413b24f1f5328af1e6a335e752d791f8c4`.
Internal checksums, manifest self-hash, exact release/unit pins and server
preflight pass; it contains no request, credential or completed authority. The
e725 kit remains permanently prohibited. E0.3 remains `IN_PROGRESS`; its exact
status is `BLOCKED_OWNER_PATHS_READY`. The next canonical step is the external
owner-device `preflight-owner-paths` report for only the fbcf499 kit. No fresh
plan/nonce/request may be created until the report is exactly
`OWNER_PATHS_READY`. Evidence:
`docs/e0-3-bot-b5-3-064a-fresh-owner-attempt-readiness.v1.json`.

## 2026-08-26 — 064A signed attempt closed fail-safe; corrective release deployed inertly

One owner-only v4 decision was then actually signed and launched once. It
stopped fail-closed as `ACTIVATION_CLOSE_UNCERTAIN`, did not retry, and its
nonce/decision are permanently consumed. Post-expiry manual reconciliation
and a v2 terminal archive reached `RECONCILED_HOLD`; the archive validates
disabled/absent/session-free current authority, no 064A customer-row read and
all runtime resources absent. `credentialIssued=false` is not asserted as
proof that a transient LOGIN could never have occurred, but it is durable
evidence that the source/read path was never reached; current authority is
conclusively dormant.

The concrete P1 blocker was an incompatible libpq session preference: the
launcher passed `target_session_attrs=read-write` to `obsidian_readonly`,
whose default transaction mode is deliberately read-only. Exact binding
therefore failed before credential mutation, and cleanup repeated it. Commit
`37bd98a313fde587980bbd9a37161e2b8eeb7582` changes only this observation DSN
to `read-only`; the admin socket remains `read-write`. Direct DSN and
pre-mutation regressions pass 47/47, expanded related tests pass 351 with
seven expected uid-70 sandbox deselections, and pin/deployment tests pass
45/45. Independent architecture, security, patch and post-deploy operations
reviews report GO.

Pin commit `5ea98d80705f5e3f6ba5c2e36137596f3b06c021` deploys the verified
2186-blob root-owned read-only release through the three unit files only, with
rollback preimages and daemon-reload; it does not start the launcher or restart
PostgreSQL. Post-rollout watchdog returns
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST`; PostgreSQL's PID/container/restart
tuple is unchanged, the timer is active/waiting and failed units are zero.

E0.3 remains `IN_PROGRESS/FAIL_CLOSED_FIX_ROLLED_OUT_NO_NEW_SIGNATURE`.
This corrective rollout opens no request and asks the owner for no signature.
The consumed attempt cannot be reused. A future fresh production attempt is
not a next automatic step: it exists only if the owner later makes a separate
explicit decision after reviewing the terminal evidence. Evidence:
`docs/e0-3-bot-b5-3-064a-read-only-observation-fix-rollout.v1.json`.
