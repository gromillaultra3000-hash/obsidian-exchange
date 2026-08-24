# E4 — ключ подписи владельца

Статус маршрута: `E4 / owner-gated fresh rehearsal`.

Эта инструкция создаёт только отдельный ключ подписи владельца. Она не
подписывает решение, не запускает Docker и не даёт разрешение на rehearsal.

## Что уже готово

- Шифрование snapshot выполнено отдельным ключом `owner-ssh`.
- Зашифрованный файл находится в
  `/root/E4-owner-handoff/obsidian_exchange-cutover-20260810.dump.age`.
- Приватный encryption key остаётся на телефоне.

## 1. Проверить старые ключи

Выполнить в Termux на Android:

```bash
ls -l ~/e4-key
```

Не удалять и не заменять `owner-ssh` или `owner-ssh.pub`.

## 2. Создать отдельную пару signing keys

```bash
ssh-keygen -t ed25519 -C "e4-owner-signing" -f ~/e4-key/owner-signing
```

На запрос `Enter passphrase` задать новый пароль. Пароль не отправлять в
чат, на сервер или в репозиторий.

Если Termux спросит, перезаписывать ли существующий файл, выбрать `n` и
остановиться: существующий ключ нельзя заменять без отдельного решения.

## 3. Передать только public key

```bash
cat ~/e4-key/owner-signing.pub
```

Передать можно только одну строку, начинающуюся с `ssh-ed25519 AAAA...`.
Файл `~/e4-key/owner-signing` и пароль являются секретом и не передаются.

## 4. Что пока не делать

- Не использовать `owner-ssh` для подписи: он предназначен для encryption.
- Не выполнять `ssh-keygen -Y sign` для случайного текста.
- Не подписывать текущий шаблон напрямую: owner decision должен быть связан
  с точным target, target fingerprint, snapshot digest, key reference,
  сроком действия и frozen E4 plan.
- Не создавать второй reviewer key самостоятельно: reviewer должен быть
  независимым человеком или отдельной доверенной стороной.

После получения public owner signing key будет подготовлен точный canonical
payload. Затем владелец подпишет именно этот payload через namespace
`e4-owner@obsidian-exchange.local`. Отдельный reviewer подпишет собственный
review envelope через другой ключ и namespace.

## Стоп-условия

Если потерян private key, неизвестен пароль, обнаружен непонятный файл или
Termux предлагает перезаписать ключ, остановиться. Не присылать содержимое
private key для диагностики.
