# E4 owner-artifact handoff

> **SUPERSEDED / HISTORICAL — DO NOT EXECUTE.** This preparation runbook no
> longer describes the active E4 route. The current one-shot ceremony is
> hard-disabled and no new payload may be signed. Follow
> [09-e4-safety-freeze-and-next-step.md](09-e4-safety-freeze-and-next-step.md).
> The only next canonical item is a versioned v2 plan/receipt contract for
> retained immutable ciphertext plus proved destruction of the disposable
> target and transient plaintext.

Этот короткий runbook описывает, как сохранить и подготовить два шаблона для владельца. Он не запускает rehearsal и не выдаёт полномочий.

Исторический маршрут: `E4 / owner-gated fresh rehearsal / owner-artifact preparation`.

## Что сохранить

- [e4-owner-decision-handoff-template.v1.json](e4-owner-decision-handoff-template.v1.json)
- [e4-disconnected-snapshot-staging-manifest-template.v1.json](e4-disconnected-snapshot-staging-manifest-template.v1.json)

Оба файла имеют статус `TEMPLATE_NOT_AUTHORIZED`. Их нельзя переименовывать в receipt или считать подписью владельца.

## Порядок подготовки

1. Сохранить файлы на контролируемый offline-носитель. Проверить, что в них нет приватных ключей, паролей, connection strings, plaintext snapshot или production credentials.

2. Проверить frozen inputs из обоих шаблонов:

   ```text
   2489745da1fd584c3d77965ebc7b4776ddad3115bcbea5dc7a623fc3d2981a03  deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json
   eb70458a03fdb5b744f44f0fd390e78f17a65226e2a48b2c763db3ff2623cc2c  relay/core/e4_rehearsal_runner_plan.py
   ```

3. Владелец выбирает свежий disposable target и заполняет только публичные идентификаторы и SHA-256: `targetRef`, `targetFingerprintSha256`, `snapshotSha256`, `snapshotRefSha256`, `keyRefSha256`, короткое окно действия и одноразовый nonce. Target должен отсутствовать до старта.

4. В manifest указывается уже существующая зашифрованная immutable snapshot copy. Нельзя создавать production snapshot специально для этой проверки, переносить plaintext в репозиторий или чат, раскрывать key material либо использовать исторический уничтоженный target `e4-full-snapshot-20260822-01`.

5. Владелец подписывает canonical decision offline через заранее доверенный issuer/trust root. Отдельный reviewer по независимому trust path проверяет binding, происхождение snapshot, scope, срок действия и отсутствие production contact, затем подписывает review envelope.

6. В handoff передаются только заполненные публичные manifest/envelope и их digest. Приватные ключи, seed-фразы, пароли, токены и connection material не передаются.

7. До запуска требуется отдельная read-only проверка реального authenticated envelope и provenance. Самохэшированный объект из `relay/core/e4_rehearsal_runner_authorization.py` не заменяет криптографическую аутентификацию владельца.

8. Даже после получения артефактов запуск остаётся `NO_GO`, пока не будет доступен полный hardened executor, исполняющий frozen 12-step plan, с consume-before-first-Docker-effect, trusted-clock checks, captured container identity, teardown proof и доказательством нулевого production contact.

## Стоп-условия

Остановиться и не продолжать, если отсутствует хотя бы одно из следующего: authenticated owner decision, независимая review-подпись, pre-existing encrypted snapshot с provenance, digest binding к target/plan, свежий одноразовый срок действия, или доказательство отсутствия production route/credentials.
