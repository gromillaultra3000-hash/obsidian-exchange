# E5: пошаговый owner/reviewer handoff для новичков

Статус: инструкция и подготовка; текущий E5 issuer-selection остаётся
`BLOCKED_OWNER`. Этот документ не является решением, подписью, waiver или
разрешением на selection, crypto, runtime или production.

## 1. Что именно мы пытаемся получить

Нужно доказать не фразу «owner согласен», а следующую цепочку:

1. система создала один неизменяемый `decision result`;
2. accountable owner увидел именно его и сделал решение;
3. independent reviewer, на другом trust domain, увидел тот же result и сделал
   отдельное решение;
4. оба решения подтверждены реальными аутентификаторами;
5. verifier проверил подписи, роли, exact hashes, свежесть и replay;
6. только после этого появился authenticated handoff.

Названия трёх объектов:

- `decision result` — что именно оцениваем;
- `assertion` — криптографическое доказательство конкретного owner/reviewer;
- `handoff` — конверт, связывающий result, обе assertion и контекст.

Одна только строка `owner_assertion_sha256` — это hash заявления, а не проверка
подписи. Нельзя вручную заменить `false` на `true`: текущая v1-схема намеренно
содержит `const: false` и является только evidence-only boundary.

## 2. Кто участвует

`ACCOUNTABLE_OWNER` — владелец, который отвечает за решение.

`INDEPENDENT_REVIEWER` — другой человек, который проверяет решение независимо.
Он не должен использовать тот же private key, устройство, trust domain,
recovery authority или аккаунт. Второй браузерный профиль, VM или второй
пользователь на одном ноутбуке независимость не создают.

Для первой процедуры нужны:

- два физических устройства, по одному у каждого человека;
- две отдельные аутентификационные области;
- публичный канал для сравнения hash (например, голосом или очно);
- owner-controlled coordination directory;
- никакие production credentials, DSN, customer data, seed или private key.

Если есть только одно устройство или только один человек, процедура не
считается выполненной. В этом случае фиксируется `BLOCKED_OWNER`.

## 3. Какие файлы уже есть

Это публичные входы. Их можно читать и копировать на оба устройства:

| Файл | Назначение |
|---|---|
| `native-wallet/.../ed25519-corpus-review-independence-issuer-selection-scorecard-v1.json` | текущая scorecard и состояние `NOT_EVALUATED` |
| `native-wallet/.../ed25519-corpus-review-independence-issuer-selection-decision-result-v1.schema.json` | схема будущего result; это ещё не result |
| `native-wallet/.../ed25519-corpus-review-independence-owner-reviewer-handoff-v1.schema.json` | текущая inert handoff-схема |
| `docs/e5-issuer-selection-owner-reviewer-deferral.v1.json` | restrictive deferral и текущий blocker |
| `docs/adr/0029-ed25519-owner-reviewer-decision-handoff.md` | объяснение границ handoff |
| `docs/adr/0028-ed25519-review-independence-issuer-selection-scorecard.md` | две ещё не выбранные модели issuer authentication |

Текущие SHA-256 для проверки:

```text
deferral:        48356a1e547e6216916f6396f389218742a76704fd310f56559e4abd5f258850
decision schema: 8a24576939b041cc810371a0b7908a6e20804eeefa599976b5a92a847bfb1299
handoff schema:  f7e67e8eb46951b2f8d17aa465e962cc2e49e33c3ee3fdf838b19a2783b66f8a
scorecard:       88fcb8bb419599b45137966a168c5b5513c10665658e7d3c81c2f8455e37fd3f
```

Проверка на каждом устройстве выполняется по raw bytes:

```bash
sha256sum docs/e5-issuer-selection-owner-reviewer-deferral.v1.json
sha256sum native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures/ed25519-corpus-review-independence-issuer-selection-decision-result-v1.schema.json
sha256sum native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures/ed25519-corpus-review-independence-owner-reviewer-handoff-v1.schema.json
sha256sum native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures/ed25519-corpus-review-independence-issuer-selection-scorecard-v1.json
```

Если хотя бы один hash отличается, работа останавливается. Нельзя брать файл
«похожего имени», старую копию или результат из переписки.

## 4. Чего сейчас не хватает

В репозитории пока нет трёх вещей, поэтому настоящую authenticated процедуру
нельзя честно завершить одной командой:

1. concrete `decision-result.json`, созданного из актуального набора evidence;
2. выбранного и утверждённого authentication method;
3. реального verifier/trust registry, который проверяет assertion и replay.

Текущая scorecard предлагает две разные модели:

- `threshold_dsse_offline_roots` — offline root ceremony, 2-of-3 roots,
  DSSE exact-byte parser, recovery и revocation;
- `dual_webauthn_human_issuers` — две отдельные WebAuthn security keys,
  RP/origin policy, enrollment, revocation и assertion verifier.

Система не имеет права выбрать одну автоматически. Сначала owner и reviewer
должны получить отдельный ADR/решение о методе; затем можно реализовать именно
его. Существующий `scripts/b64_064a_offline_signer.py` относится к E0.3/064A,
а не к E5 issuer-selection. Нельзя использовать его как доказательство E5.

## 5. Правильная последовательность действий

### Шаг A. Подготовить public package

Codex/оператор создаёт один public package с exact текущими входами. Он должен
содержать manifest, в котором для каждого файла записаны относительный путь и
SHA-256. Пакет копируется на оба устройства.

Private keys, passphrases, WebAuthn assertion bytes и raw credential material в
этот package не входят.

### Шаг B. Создать concrete decision result

Это делает verifier-side tool после выбора exact current inputs, а не человек
вручную в редакторе. Файл должен быть, например, в защищённой coordination
directory:

```text
<coordination>/public/decision-result-<decision-id>.json
```

Он должен содержать поля из текущей schema:

- `decision_id` и `result_sha256`;
- `outcome` из закрытого enum;
- `candidate_option_id` и `selected_option`;
- `selection_scorecard_sha256`;
- exact context/source digests;
- `subject_review_domain_id`;
- `issued_at_epoch_ms`, `expires_at_epoch_ms`, `caller_nonce_sha256`.

Для нынешнего состояния scorecard честное состояние — `NOT_EVALUATED`,
`selected_option:null`, без capability. Этот result не означает, что issuer
выбран.

После создания result его hash сравнивается на обоих устройствах по
независимому каналу. Если result изменился, старый review уничтожается и
начинается новый decision ID/nonce.

### Шаг C. Reviewer проверяет и подписывает первым

Reviewer на своём физическом устройстве:

1. открывает public package;
2. сверяет hashes;
3. проверяет, что `selected_option:null`, `NOT_EVALUATED` и authority flags
   restrictive;
4. проверяет source/context digests и срок действия;
5. выбирает только одно: `ACCEPT`, `DEFER` или `REJECT`;
6. подтверждает решение своим выбранным authenticator’ом;
7. получает `reviewer assertion envelope`.

Reviewer assertion должна связывать не свободный текст, а canonical message:

```text
domain separator
role=INDEPENDENT_REVIEWER
reviewer identity/trust domain
decision
decision_result_sha256
context_handoff_sha256
selection_scorecard_sha256
issued_at / expires_at
fresh nonce
```

Reviewer передаёт owner только public envelope или его approved hash. Private
key, passphrase и raw credential material не передаются.

### Шаг D. Owner проверяет reviewer и countersigns вторым

Owner на другом устройстве:

1. заново сверяет public package и result hash;
2. проверяет, что reviewer identity/domain не совпадает с owner;
3. проверяет reviewer assertion своим verifier’ом;
4. читает тот же result, а не пересказ reviewer;
5. выбирает `ACCEPT`, `DEFER` или `REJECT`;
6. подтверждает собственное решение своим authenticator’ом;
7. создаёт owner assertion, связанную с exact reviewer assertion digest.

Owner не должен редактировать reviewer envelope или копировать его private
материал. Итогом должны быть две разные assertion с разными identities,
domains, nonces/IDs и подписями.

### Шаг E. Verifier собирает authenticated handoff

Verifier проверяет одновременно:

- подпись reviewer по доверенному registry;
- подпись owner по доверенному registry;
- exact result/context/scorecard hashes;
- роли и pairwise independence;
- issued/expiry и trusted time;
- single-use handoff ID и caller nonce;
- отсутствие replay/revocation/epoch rollback;
- decision compatibility.

Verifier должен создать новый authenticated handoff version, а не менять
текущий v1-файл. Текущий v1 зафиксирован как structural-only и не способен
вмещать честное `owner_authenticated:true`.

Минимальные public outputs выглядят так:

```text
<coordination>/public/decision-result-<id>.json
<coordination>/public/reviewer-assertion-<id>.json
<coordination>/public/owner-assertion-<id>.json
<coordination>/public/verification-report-<id>.json
<coordination>/public/authenticated-handoff-<id>.json
```

Для WebAuthn raw assertion bytes остаются во внешнем encrypted review
workspace; в repository попадают только разрешённые hashes и verification
result. Private keys никогда не попадают в repository.

## 6. Что означает итог

Если хотя бы один участник выбрал `DEFER` или `REJECT`, итог остаётся
restrictive: `selection_allowed:false`, `crypto_call_allowed:false`,
`runtime_integration_allowed:false`.

Даже две корректные подписи `ACCEPT` не означают production signing. При
текущем `NOT_EVALUATED` result они не могут автоматически выбрать issuer:
нужен отдельный валидный selection outcome и сохранённое правило tie/ADR.
Production flags всё равно остаются false до независимых E5 operational gates.

## 7. Что нельзя делать

- писать `true` в `owner_authenticated` вручную;
- использовать один ноутбук с двумя аккаунтами или VM;
- отправлять private key/passphrase в Telegram, chat, Git или email;
- класть production credentials, DSN, seed, customer data или raw WebAuthn
  evidence в repository;
- принимать hash без проверки raw-byte файла;
- использовать E0.3 signer как E5 verifier;
- считать тестовый synthetic `ACCEPT` настоящим решением;
- запускать selection, crypto, wallet signing или production action после одной
  подписи.

## 8. Что нужно решить перед реализацией команд

Чтобы перейти от этой инструкции к рабочему test-only verifier’у, нужны ровно
три внешних решения:

1. кто конкретно является independent reviewer;
2. есть ли у owner и reviewer два отдельных физических устройства;
3. какой authentication method утверждён отдельным решением: DSSE offline
   roots или dual WebAuthn.

После этого можно отдельно реализовать generator/verifier, fixture для
concrete decision result, authenticated handoff v2 и их negative/replay tests.
До этого текущий статус честно остаётся `BLOCKED_OWNER`.

## 9. Если оба участника работают с телефона

Рабочая рекомендация для телефонного сценария — `dual_webauthn_human_issuers`,
но с device-bound/non-backup credentials. Телефон может быть экраном и местом,
где человек подтверждает действие биометрией или PIN; verifier всё равно
проверяет реальные WebAuthn bytes, RP ID, origin, ES256, UP/UV и backup flags.

Обычный synced passkey из iCloud Keychain, Google Password Manager или другого
синхронизирующего провайдера нельзя автоматически считать подходящим: он может
быть multi-device/backup-eligible, а текущий E5-профиль требует
`backup_eligible:false` и запрещает backup flags. Если сам телефон не может
дать credential с нужным состоянием, практический вариант — отдельный
device-bound FIDO2 security key на каждого человека, подключаемый к телефону
через NFC или USB-C. Это по-прежнему телефонная процедура, но ключ не
синхронизируется между устройствами.

До регистрации verifier должен проверить фактические assertion flags, а не
название в интерфейсе. В текущем preflight требуются UP+UV, запрещены BE/BS,
AT/ED и разрешён только exact flags byte `0x05`; также обязательны exact RP ID,
origin, enrollment provenance, revocation snapshot и single-use challenge.

Если у обоих есть только synced phone passkeys и нет device-bound credential,
не нужно обходить правило или подменять его DSSE-файлом. Остаётся
`BLOCKED_OWNER`; сначала требуется отдельное решение об изменении профиля и
его security trade-offs.

## 10. Что делать именно вам на Android

Сейчас не начинайте с Google Password Manager и не создавайте passkey
«наугад». В репозитории пока нет Android APK или web-страницы с настроенным
RP ID, origin, challenge и verifier’ом. Без них телефон не знает, какой именно
текст подписывать, а сервер не умеет проверить результат.

Порядок реализации будет таким. Первый пункт уже начат в rehearsal-коде; на
телефонах пока всё равно ничего не открывайте и passkey не создавайте.

1. **Сначала готовится test-only pre-auth boundary.** Сейчас добавлен
   `native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support/e5_android_webauthn_preauth.py`.
   Он создаёт две разные role-specific challenge-сессии, связывает их с тремя
   exact SHA-256 контекстами, проверяет роль, независимость, срок, origin/RP ID,
   целостность ссылки и replay. Это ещё не криптографический verifier: public
   key, credential registry, ES256-проверка и Android API пока отсутствуют.
   Поэтому все authority flags остаются `false`.
2. **Мы выдаём две разные ссылки или два одноразовых QR-кода.** Reviewer
   получает только reviewer-ссылку, owner — только owner-ссылку. В каждой
   ссылке уже зашиты role, exact result hash и одноразовый challenge.
3. **Reviewer открывает свою ссылку на своём Android.** Он проверяет домен,
   роль, displayed result hash и expiry, нажимает `Register/Approve`, а в
   системном окне Android подтверждает действие fingerprint/PIN. Private key
   остаётся внутри credential provider; reviewer передаёт только public result.
4. **Owner открывает свою ссылку на другом Android.** Он сначала проверяет
   reviewer result/hash и то, что роль owner, затем также подтверждает своим
   fingerprint/PIN. Его assertion связывается с reviewer assertion digest.
5. **Verifier проверяет обе стороны.** При любой ошибке в domain, role, RP ID,
   origin, flags, сроке, nonce, credential status или независимости результат
   отклоняется. Никто не редактирует JSON руками.
6. **Мы сохраняем только public evidence.** Private keys, passphrases, seed,
   production credentials и raw WebAuthn bytes не попадают в Git или чат.

На текущем тестовом срезе результат проверки специально выглядит так. Сначала
проверяется transport/preflight-слой, а затем должен появиться отдельный
криптографический verifier:

```text
preAuthStructurallyValid: true
cryptographicVerificationImplemented: false
authenticated: false
selectionAllowed: false
cryptoCallAllowed: false
runtimeIntegrationAllowed: false
```

Preflight дополнительно проверяет, что envelope:

- не содержит лишних или пропущенных полей;
- использует canonical unpadded Base64URL;
- содержит `webauthn.get`, exact challenge и exact origin;
- содержит ровно 37 байт authenticator data;
- содержит правильный RP ID hash и flags byte `0x05`;
- не превышает лимиты размера и не содержит дублирующихся JSON-полей.

Но этот слой не проверяет public key, credential registry, revocation или
ES256 signature. Поэтому даже успешный preflight всё ещё не является входом,
решением или разрешением.

Следующий test-only RP-контракт уже подготовлен в
`native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support/e5_android_webauthn_rp_contract.py`.
Его логика такая:

1. `GET /e5/webauthn/reviewer/<session-id>` показывает reviewer-view;
2. `GET /e5/webauthn/owner/<session-id>` показывает другой owner-view;
3. `POST .../<session-id>/assertion` принимает только закрытый JSON с
   assertion envelope;
4. успешный ответ имеет статус `PREFLIGHT_ONLY`, а не
   `AUTHENTICATED`;
5. сессии не сохраняются, replay ledger не включён, socket и production route
   не запускаются.

Поэтому эти пути пока являются тестовым контрактом для будущего сервера, а не
ссылками, которые можно открыть на Android.

Для локальной rehearsal-среды также подготовлен
`e5_android_webauthn_test_server.py`. Он требует явные TLS certificate/key
paths, разрешает только loopback и не запускается автоматически. Адрес
`https://localhost` означает localhost самого устройства, поэтому такой
режим не подходит для двух разных Android-телефонов.

Чтобы телефоны реально подключились, понадобится отдельный staging HTTPS-домен,
его сертификат и явное связывание домена с RP ID/origin. До этого ссылки не
выдаём и credentials не регистрируем.

`pay.obsidianbtc.org` для этого не подходит: по текущему E0.4 inventory это
существующий публичный payment-alias с wildcard-проксированием на неизвестный
upstream `127.0.0.1:8080`. Его нельзя переиспользовать как WebAuthn RP, пока
отдельно не доказаны ownership, payment-scope, runtime, TLS, release и
rollback. Нужен отдельный staging subdomain, например
`webauthn-staging.obsidianbtc.org`, с отдельной DNS/TLS и deployment-политикой.

То есть «ссылка сформирована и не испорчена» ещё не означает «человек
аутентифицирован». Реальные ссылки появятся только после отдельного RP/
verifier endpoint и owner-approved authentication decision.

Android Credential Manager получает параметры создания passkey от server,
создаёт credential через системный UI, а public key затем должен пройти
server-side verification. Поэтому сначала нужен наш test-only server-side
flow; одних телефонов и Google Password Manager недостаточно.

Практический критерий остановки на телефоне: если Android credential выдаёт
`BE=1` или `BS=1`, регистрацию не принимаем. Если Credential Manager не даёт
проверяемый `BE=0/BS=0`, нужен отдельный device-bound FIDO2 key на каждого,
который подключается к Android через NFC/USB-C. Если и этого нет, процедура
остаётся `BLOCKED_OWNER`.
