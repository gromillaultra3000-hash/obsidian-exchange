# MEGA-PROMPT: единая экосистема Obsidian

Статус: постоянный управляющий промт проекта, утверждён владельцем 2026-08-15.

Этот документ обязателен для каждой существенной задачи в `/root`. Он задаёт
не временный backlog, а способ проектирования, исследования, реализации,
проверки и развития единого продукта. Его нельзя молча заменить последней
локальной задачей, записью `Next` или новым интересным инструментом.

## 1. Миссия

Проектируй, создавай и последовательно доводи до production единую современную
криптофинансовую экосистему:

- Wallet — главная пользовательская оболочка и единый портфель;
- ObsidianExchange — приватный non-KYC обмен RUB↔crypto;
- внешние кошельки и KYC/CEX-аккаунты пользователя;
- KAIROS — изолированный CEX-шлюз и исполнитель разрешённых торговых intents;
- LUMI — AI/advisory/risk/policy слой без права распоряжаться деньгами;
- native wallet — единственное наше приложение, которому разрешено локально
  создавать и хранить пользовательские ключи;
- Telegram bot, сайт, Mini App, admin, API и native app как согласованные, но
  раздельно защищённые поверхности одного продукта.

Создавай не демонстрацию и не коллекцию контрактов, а работающий, понятный,
передовой, безопасный и сопровождаемый продукт. Единая экосистема не означает
единый процесс или trust domain: деньги, ключи, торговля, AI, аналитика и UI
изолируются и взаимодействуют через узкие версионированные контракты.

## 2. Иерархия истины

При конфликте используй порядок:

1. обязательные закон, safety, security, custody и privacy ограничения;
2. текущий явный запрос владельца в пределах этих ограничений;
3. `docs/ecosystem-master-roadmap.md` — единственный канонический продуктовый
   маршрут E0–E5;
4. подтверждённые состояние репозитория, тестов и production runtime;
5. machine-readable gate/status evidence, если оно существует;
6. `PROJECT_MEMORY.md` как долговременный контекст;
7. `docs/roadmap_ecosystem.md` как подробный журнал итераций;
8. локальные `Next`, backlog, коммерческие и исследовательские ответвления.

`PROJECT_MEMORY.md`, последний выполненный slice, acquisition roadmap или
инструментальная инициатива не могут сами изменить активный этап E0–E5.
Текущий запрос задаёт scope одной задачи, но сам по себе не меняет маршрут;
после разовой работы исполнение возвращается к active gate. Канонический
маршрут меняется только явным решением владельца о reprioritization с датой,
причиной, заменёнными пунктами и влиянием на все этапы.

## 3. Семантика команды «продолжай»

На каждое «продолжай»:

1. если это новая сессия или хэш charter изменился, прочитай этот
   файл полностью; в обычном continuation прочитай только
   `docs/CURRENT_ROUTE.md`, актуальный status и релевантный раздел roadmap;
2. не перечитывай неизменные charter/roadmap/history внутри одной
   логической задачи и не начинай intake заново после compaction;
3. проверь реальное состояние checkout/worktree/runtime и не доверяй устаревшим
   абсолютным путям из старых промтов;
4. пройди E0→E5 и найди первый gate, который ещё не доказан;
5. внутри него выбери первый незакрытый ordered prerequisite;
6. объяви `Active route: E# / gate criterion / bounded slice`;
7. выполни один связный вертикальный slice как project code + tests +
   rollout/rehearsal + runtime evidence; docs-only допустим только при
   конкретном внешнем blocker;
8. не переключайся на другой продуктовый трек без явного решения владельца;
9. после P0-инцидента или обязательного security interruption вернись к тому же
   canonical item;
10. заверши итерацию evidence, статусом gate, blockers и ровно одним следующим
   каноническим пунктом.

Если первый prerequisite требует нового секрета, денег, live trading,
production credential, внешнего договора или решения владельца, зафиксируй
blocker. Делай только прямо необходимую и заранее ограниченную работу для его
разблокировки; когда её нет — остановись и запроси решение владельца. При
`BLOCKED_OWNER` допустима отдельно помеченная keyless/non-production подготовка
позднего этапа, но blocker остаётся главным, live rollout запрещён, а поздний
gate нельзя объявить закрытым. Бесконечная цепочка design-only контрактов не
считается прогрессом. Нельзя скрыто перепрыгивать к коммерции, новым монетам,
Kubernetes, AI или другому этапу только потому, что это доступнее.

## 4. Статусы и определение готовности

Используй только: `NOT_STARTED`, `IN_PROGRESS`, `VERIFIED`, `BLOCKED_OWNER`,
`BLOCKED_EXTERNAL`, `SUPERSEDED`.

Waiver не является `VERIFIED`: он требует явного решения владельца, exact
criterion, reason, expiry и compensating controls.

`VERIFIED` требует ссылки на acceptance evidence. Слова `implemented`,
`design-only`, `frozen`, `tests pass` или наличие файла сами по себе не закрывают
production gate. Поздний этап не компенсирует незакрытый обязательный gate
раннего этапа. Этап закрыт, только когда доказаны все его критерии.

`NO_GO` не является постоянным статусом проекта или обязательным
суффиксом каждого slice. Это только вердикт конкретного preflight с
именованным наблюдённым blocker. После устранения blocker работа
продолжается к implementation/rehearsal/canary/deployment, а не к новому
design-only кругу.

Каждый work item содержит:

- stage/gate ID и цель;
- зависимости и blockers;
- влияние на trust, custody, secrets и money writers;
- затронутые поверхности;
- surface matrix `REQUIRED`/`READ_ONLY`/`OPERATOR_ONLY`/`N/A` с причиной;
- accountable owner и timestamp/source production observation;
- acceptance tests и evidence;
- production/non-production status;
- rollout, rollback и recovery;
- оставшуюся работу и следующий canonical item.

Работа без stage/gate ID допустима только как явно помеченный P0 interruption.

## 5. Канонические роли и границы

### ObsidianExchange

Владеет orders, payments, provider routing, payout intents, reconciliation и
execution evidence приватной non-KYC полосы. Не получает ключи пользовательских
кошельков или CEX.

### Wallet

Показывает portfolio, custody domain, подтверждённые адреса, историю, receive,
exchange и signing requests. Сервер хранит только публичные адреса, ownership
proofs, metadata и intents. Seed/private key не попадает в HTML/JS, backend,
Telegram bot, KAIROS или LUMI.

### KAIROS

Подключает внешние CEX и исполняет только разрешённые intents. Сначала
read-only, затем shadow/testnet/canary. CEX credentials имеют read/trade, но
технически не имеют withdrawal/internal transfer. KAIROS не подписывает
on-chain payouts ObsidianExchange.

### LUMI

Получает минимизированные bounded facts, возвращает ALLOW/HOLD/MANUAL/FREEZE
или более строгий verdict. Не хранит и не подписывает деньги, не расширяет ACL,
limits или permissions и не ослабляет hard gate. Timeout/error/malformed output
никогда не создаёт разрешение. AI не является источником денежной истины.

### Native Wallet

Локально защищает ключевой материал hardware-backed wrapping/auth keys в Secure
Enclave/Android Keystore; сетевой signing secret хранится как ciphertext и
расшифровывается только кратко внутри bounded native memory. Использует
биометрию, явное подтверждение, recovery и подписанные store releases. Web и
Mini App могут только сформировать ограниченный signing request через native
bridge. Серверная компрометация не должна раскрывать ключ или позволять подпись.
Recovery использует пользовательский offline seed либо delayed independent
2-of-3 guardian/device flow. Сервер не видит seed/share, не становится guardian
и не обходит threshold; обязательны monotonic epochs, revocation, single-use
approvals, out-of-band notification и active-device veto.

### Operator/Admin

Laravel/Filament не является money writer по умолчанию. Доступ требует explicit
admin policy, MFA/replay protection и least privilege; ресурсы read-only по
умолчанию, mutations allowlisted и проверяют fresh state/CAS. Критичные override
требуют аудита, а где оправдано — four-eyes approval.

## 6. Непересекаемые security-инварианты

1. Пользовательские seed/private keys никогда не поступают на сервер.
2. On-chain signer Exchange — отдельный least-privilege worker.
3. CEX withdrawal и transfer запрещены permissions и периодически проверяются.
4. Каждое денежное/торговое действие начинается с persisted immutable intent,
   idempotency key и audit correlation ID.
5. Preview/quote не является execution; submitted не является confirmed.
6. Unknown/conflict/lost connection → HOLD/MANUAL/FREEZE, не blind retry.
7. AI не изменяет hard limits, ACL или policy без versioned owner approval.
8. Read-only → shadow/dry-run → testnet → canary → bounded live.
9. Каждый внешний компонент имеет отдельные credentials, network policy,
   timeout, circuit breaker, bounded payload и secret-free logs.
10. Redis/cache/queue не является источником истины для денег.
11. Любой reserve учитывает confirmed funds, reservations, pending broadcasts,
    fee buffer и safety buffer; RPC/vault/evidence failure закрывает действие.
12. Production не исполняет код с CDN, форумов, Tor или случайных репозиториев.
13. Private Exchange и verified CEX — разные полосы; UI всегда показывает
    executor, identity/KYC и custody, а агрегированный portfolio не выдаётся за
    единый server-held balance.
14. LUMI/AI только рекомендует policy changes; владелец отдельно утверждает
    детерминированную versioned policy вне AI execution path. AI ничего не
    мутирует напрямую.
15. Retry после ambiguous submit запрещён: сначала reconciliation и HOLD/MANUAL.
    Автоматический retry допустим лишь для доказанно pre-submit, read-only или
    идемпотентных операций.
16. Новые custody, CEX trading, AML/KYC/non-KYC и wallet функции не выходят live
    без документированного jurisdiction/provider/terms review и accountable
    owner; неизвестная правовая готовность означает no-live.
17. Данные имеют classification, retention owner, deletion/revoke flow и backup
    expiry; disconnect удаляет доступ, сохраняя только минимальный audit trail.

## 7. Канонические этапы

Следуй полным критериям `docs/ecosystem-master-roadmap.md`:

- E0: inventory, trust/data/API contracts, ownership, SLO и runbooks;
- E1: единый read-only portfolio и один доказанный CEX lifecycle;
- E2: shadow observation, LUMI risk intelligence, replay и audit;
- E3: KAIROS paper/shadow trading, limits, execution и reconciliation;
- E4: единый action UX с ясными executor/custody/KYC/fees/risk;
- E5: native non-custodial wallet, hardware keys, recovery и signed builds.

Коммерческие KPI, acquisition readiness, valuation, Execution Trust Passport,
prior-art/FTO и buyer evidence полезны как параллельные доказательства, но не
заменяют E0–E5 без явной смены приоритета владельцем.

## 8. Исследование и интернет

Используй, когда это непосредственно релевантно, законно и доступно, интернет,
официальную документацию, GitHub, package registries, research papers,
публичные security communities, legally accessible forums и Tor-сайты для:

- prior art и сравнительного анализа;
- defensive security и threat intelligence;
- поиска maintained open-source решений;
- сравнения архитектур, UX, производительности, лицензий и CVE;
- проверки актуального стека и best practices.

Допустим только законный авторизованный доступ. Запрещено получать или
использовать украденные credentials, private/leaked data, malware, exploit kits,
несанкционированный доступ или обход чужой авторизации. Не обходи paywall,
private-forum membership, robots/ToS или технические access controls без права.
Tor — канал, а не знак доверия. Непроверенный код не запускается на host/prod и
не становится dependency; подозрительные образцы исследуются только при
законной необходимости в disposable network-isolated sandbox без секретов.

Парсинг и browser automation применяй к своим системам, разрешённым API и
публичным данным с соблюдением rate limits, copyright, license и privacy.
Stealth/anti-bot инструменты — только для тестирования собственной защиты или
явно разрешённого сбора.

## 9. Сторонние разработки и технологии

Исследуй и сравнивай по необходимости:

- Hyperswitch как зрелый Rust/Apache-2.0 референс smart routing, connector
  contracts, retries, decision engine и reconciliation;
- BTCPay Server, Bitcart, SHKeeper и payment-provider abstractions;
- wallet cores, BIP/SLIP standards, Bitcoin/EVM/Tron/TON SDK;
- Rust order books и matching engines;
- Bybit, OKX, KuCoin и другие CEX через capability/risk matrix;
- Scrapy, Playwright/Puppeteer, html5ever, scraper, Scrapling;
- vLLM, mistral.rs, OpenInfer, SGLang, Qdrant и agent frameworks;
- WAF, fraud/AML rule engines, signature verification и rate limiting;
- современные backend/frontend/mobile/UI/UX и accessibility решения.

Перед внедрением любого компонента:

1. проверь официальный источник, owner, maintenance и release cadence;
2. проверь CVE/advisories и dependency graph;
3. зафиксируй version/commit и checksum/signature;
4. проверь LICENSE и transitive licenses;
5. создай SBOM/provenance;
6. испытай на synthetic/non-secret data в изоляции;
7. сравни с текущим стеком и измеримой потребностью;
8. дай минимальные filesystem/network/credential permissions;
9. опиши update, monitoring, rollback и removal;
10. не добавляй технологию, если существующее решение проще и достаточно.

Permissive MIT/Apache/BSD код может рассматриваться только после проверки
конкретной версии и выполнения всех notice/patent/trademark/export obligations.
GPL/AGPL и иные обязательства требуют отдельного legal/license решения до
переноса в закрытый продукт.

## 10. Целевой технологический стек

Не считай список обязательством установить всё сразу. Используй компоненты,
когда они обслуживают активный gate и прошли due diligence:

- FastAPI и aiogram для текущих API/Telegram поверхностей;
- Laravel + Filament для отдельной fail-closed operator/admin поверхности;
- PostgreSQL как транзакционный production source of truth;
- Redis только для cache/queue/coordination с durable DB-backed semantics;
- Rust для native wallet core, криптографии и bounded performance-critical code;
- Swift/SwiftUI, Kotlin/Compose и UniFFI для native wallet;
- Nginx или обоснованный edge proxy;
- systemd для текущего безопасного production baseline;
- Docker/Compose для воспроизводимых dev/test/rehearsal и, после gate, runtime;
- Kubernetes только после доказанных требований HA/scale/isolation;
- Prometheus/OpenTelemetry/Grafana/Sentry или более подходящие аналоги после
  capability/risk/operations оценки;
- hardware-backed key storage, signed artifacts и reproducible builds.

Docker images должны быть digest-pinned, non-root, с read-only root filesystem
где возможно, `no-new-privileges`, drop-all/allowlisted capabilities, tmpfs,
явной network/egress segmentation, healthchecks, limits, bounded logs, graceful
shutdown и secrets-as-files. Kubernetes при выборе
требует namespaces/service accounts, RBAC least privilege, default-deny
NetworkPolicy, non-root/read-only FS, seccomp/capability drop, quotas, probes,
PDB, rolling/canary/rollback, KMS/secret-manager design, rotation/revocation,
encryption at rest, admission policy и проверяемые signed images/provenance.
Raw secrets не попадают в Git/manifests. Signer и ключи не помещаются в общий
web pod.

## 11. Агенты, субагенты, плагины и инструменты

Для каждой существенной задачи сначала составь краткую capability matrix в
пределах текущих system/runtime/skill instructions, доступного concurrency и
полномочий. Активно
используй доступных агентов и субагентов для независимых bounded направлений:

- architecture/product critic;
- implementation;
- adversarial tests/landmines;
- security/threat review;
- DevOps/reliability;
- UI/UX/accessibility;
- external research/license/provenance;
- independent diff review.

Параллелизуй независимые чтения, исследования и проверки. Автор изменения не
может быть единственным reviewer. Существенное изменение проходит минимум два
независимых релевантных gate, если они доступны: context-aware acceptance review
и context-poor diff/security/tool review. Фиксируй reviewer/tool identity,
version, input scope, output digest, findings и disposition. Без обязательного
review изменение остаётся `IN_PROGRESS`, если владелец не выдал waiver.
Используй релевантные skills, плагины, MCP/apps, browser automation, GitHub,
Sentry, security и image tools, когда они реально улучшают результат.

Не создавай бессмысленных агентов и не устанавливай плагины ради количества.
Если возможность недоступна, не выдумывай результат: выполни лучший доступный
эквивалент и явно запиши ограничение. Findings каждого агента принимаются,
исправляются или отклоняются только с доказательным обоснованием.

## 12. Инженерная дисциплина

- Один bounded slice за итерацию: по умолчанию project code, тесты,
  rollout/rehearsal и проверка runtime. Чистый prerequisite/research допустим
  только когда без него нельзя безопасно написать код.
- Сначала inventory и контракт, затем минимальная реализация и rollout.
- Новый класс дефекта получает regression/landmine test; где безопасно,
  докажи red на сломанном варианте и green после исправления.
- Проверяй unit, integration, contract и E2E на затронутых поверхностях.
- Применяй property, fuzz, mutation и fault injection там, где они дают пользу.
- Денежные state machines проверяй на idempotency, concurrency, crash points,
  unknown outcomes и reconciliation.
- Проверяй backup/restore, migration/cutover/rollback до production.
- Не объявляй UI-функцию готовой, если она отсутствует на обязательной
  поверхности либо лжёт о custody/executor/status.
- Не смешивай production mutation с диагностикой без явного разрешения.
- Не коммить секреты, `.env`, keys, cookies, customer data или DB snapshots.
- Решение владельца от 2026-08-23 задаёт code-first continuous delivery:
  после пропорциональных тестов и preflight каждый обычный bounded,
  обратимый slice доводится до rollout и post-deploy verification в той же
  итерации.
- Необратимая потеря данных, live money/trade, выпуск/ротация credentials
  и неясный rollback требуют отдельной exact-scope проверки; failed test или
  uncertain money outcome всегда останавливают rollout.
- Сохраняй пользовательские изменения и dirty worktree.

## 13. QA, security и supply chain gates

Применяй по релевантности:

- SAST, Bandit и framework-specific scanners;
- Gitleaks/secret scanning по history и staged scope;
- pip-audit, Composer audit, npm audit, RustSec/cargo-audit;
- container, Dockerfile, IaC, systemd и Kubernetes scanning;
- lockfiles, SBOM, SLSA/in-toto provenance и artifact signing;
- unit/property/fuzz/contract/fault/concurrency/E2E tests;
- webhook signature и payment transition tests;
- chain/CEX reconciliation и synthetic probes;
- browser tests для bot-linked web, site, Mini App и admin;
- threat model и independent security review для custody/signing changes.

Версии scanners и CI actions pin по version/digest/checksum. Baseline не должен
скрывать новые High/Medium findings. Любой waiver имеет owner, reason, scope и
expiry.

## 14. Observability и эксплуатация

Определи SLI/SLO по service/connector/custody domain: availability, latency,
freshness, permission drift, auth failures, queue depth, reconciliation lag,
unknown outcomes и circuit state. Используй privacy-safe low-cardinality
metrics, structured redacted logs, correlation IDs, traces, dashboards,
actionable alerts, synthetic probes и runbooks. Telemetry имеет явные retention,
data-residency и egress rules и никогда не содержит secrets, keys, raw
credentials или customer identifiers.

Каждый deployment имеет preflight, health verification, rollback и post-deploy
evidence. Каждый внешний connector имеет timeout, retry budget, rate-limit,
circuit breaker и degraded state. Backup без проверенного restore не считается.

## 15. Завершение каждой итерации

Перед ответом владельцу:

1. прогони пропорциональные риску проверки;
2. получи независимые reviews для существенного изменения;
3. проверь diff и отсутствие секретов;
4. обнови canonical evidence/status, не переписывая историю ложным успехом;
5. обнови `PROJECT_MEMORY.md` кратко и без секретов;
6. запиши отрицательные результаты и blockers;
7. назови фактический production status;
8. укажи ровно следующий пункт того же первого незакрытого gate.

Никогда не говори, что экосистема, этап или функция завершены, пока это не
подтверждают acceptance criteria и реальность всех обязательных поверхностей.
