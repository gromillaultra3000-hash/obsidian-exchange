#!/usr/bin/env python3
"""Админ-CLI горячего кошелька XRP. Пароль спрашивается интерактивно (не через
аргументы — чтобы не светился в history/ps) либо из файла с правами 600
(WALLET_PASSWORD_FILE).

Зачем это есть. Резерв XRP (`/setreserve XRP N`) открывает направление клиенту,
и деньги начинают приходить. Расходной поверхности у этого резерва не было:
движок авто-выплат XRP не знает (`process_payout` → None), `/payout` честно
отвечает «отправлять вручную», а `xrp_wallet.py` вызывался только ради баланса.
Получался приём без выдачи — деньги внутрь, а выхода нет.

Команды:
  status | address | balance                   — пароль не нужен*
  create                                        — создать НОВЫЙ кошелёк
  import                                        — импорт по seed (s…)
  backup                                        — проверить шифр-бэкап паролем
  unlock                                        — проверить пароль
  preview  <адрес> <сумма> [тег]
  transfer <адрес> <сумма> [тег] [--ref ЯРЛЫК]  — ⭐ весь путь за один запуск

  --ref — только чтобы СОЗНАТЕЛЬНО отправить второй одинаковый платёж на тот же
  адрес. Без него повтор той же команды опознаётся как дубль и денег не тронет
  (это защита от повтора после неопределённого ответа сети).

  <адрес> — classic (r…) ИЛИ X-адрес (X…). У X-адреса тег ВНУТРИ, отдельно его
  указывать не нужно; если указан и не совпал — отправка отклоняется, а не
  «выбираем какой-нибудь». Именно в таком виде адрес лежит в заявке, поэтому
  копировать из панели /worker можно как есть.
  *balance требует, чтобы вольт уже был создан.

⚠️ Разлочка живёт в памяти процесса, а каждый запуск CLI — отдельный процесс,
поэтому для отправки используйте `transfer`: он проводит пароль→превью→отправку
за один запуск (превью живёт 120 с и не истечёт между шагами).

⚠️ Отправка закрыта гейтом XRP_PAYOUTS_ENABLED — как и авто-выплаты. Выключенный
гейт означает «XRP ещё не продаём»; CLI не должен быть дырой в обход него.
"""
import getpass
import json
import os
import sys
from pathlib import Path

# путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wallet import xrp_wallet as w  # noqa: E402


def _pw(prompt="Пароль кошелька: "):
    pf = os.environ.get("WALLET_PASSWORD_FILE")
    if pf:
        p = Path(pf)
        if not p.exists():
            raise SystemExit(f"Файл пароля не найден: {pf}")
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:
            raise SystemExit(f"Файл пароля {pf} доступен посторонним (права {mode:o}).\n"
                             f"Исправьте: chmod 600 {pf}")
        return p.read_text("utf-8").strip()
    if not sys.stdin.isatty():
        raise SystemExit(
            "Нет терминала — ввести пароль скрытно невозможно.\n\n"
            "Выполните команду в обычной SSH-сессии, либо через файл пароля:\n"
            "    nano /root/.wallet_pw && chmod 600 /root/.wallet_pw\n"
            "    WALLET_PASSWORD_FILE=/root/.wallet_pw \\\n"
            "        /root/bot/venv/bin/python3 /root/relay/wallet/xrp_cli.py transfer …\n"
            "    shred -u /root/.wallet_pw\n")
    return getpass.getpass(prompt)


def _tag(argv, idx=4):
    """Тег из аргументов. Пусто — не то же самое, что 0: тег 0 существует."""
    if len(argv) <= idx or argv[idx] == "":
        return None
    try:
        return int(argv[idx])
    except ValueError:
        raise SystemExit("Тег назначения — целое число от 0 до 4294967295")


def _describe(dest, tag):
    classic, tag_in_addr = w.parse_destination(dest)
    if not classic:
        raise SystemExit(f"Адрес не проходит проверку XRPL: {dest}")
    shown = tag_in_addr if tag_in_addr is not None else tag
    line = f"Получатель: {classic}"
    line += f"\nDestination tag: {shown}" if shown is not None else "\nDestination tag: нет"
    if tag_in_addr is not None and tag is not None and int(tag_in_addr) != int(tag):
        raise SystemExit(f"Тег в адресе ({tag_in_addr}) не совпадает с указанным ({tag}). "
                         f"Отправку не начинаю: один из них чужой.")
    return line


def _take_ref():
    """Вынимает `--ref ЯРЛЫК` из argv ДО разбора позиционных аргументов.

    Иначе флаг занимает место необязательного позиционного (у XRP это тег), и
    задокументированная команда падает с «Тег назначения — целое число».
    Возвращает ярлык и оставляет argv без него.
    """
    ref = ""
    out, i = [], 0
    while i < len(sys.argv):
        if sys.argv[i] == "--ref" and i + 1 < len(sys.argv):
            ref = sys.argv[i + 1]
            i += 2
            continue
        out.append(sys.argv[i])
        i += 1
    sys.argv[:] = out
    return ref


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    ref = _take_ref()
    cmd = sys.argv[1]
    try:
        if cmd == "status":
            print(json.dumps(w.status(), ensure_ascii=False, indent=2))
        elif cmd == "address":
            print(w.status().get("address") or "(кошелёк не создан)")
        elif cmd == "balance":
            print(json.dumps({"balance": w.get_balance(),
                              "spendable": w.spendable()}, ensure_ascii=False, indent=2))
        elif cmd == "create":
            print("Создание НОВОГО XRP-кошелька. Seed генерируется и сразу\n"
                  "шифруется паролем.\n"
                  "⚠️ Счёт XRPL «активируется» только после того, как на него\n"
                  "придёт минимум базового резерва — до этого отправлять нечем.")
            pw = _pw("Новый пароль вольта (мин 10 символов): ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.create_wallet(pw), ensure_ascii=False, indent=2))
            print("\n⚠️ Скопируй шифр-бэкап из /root/wallet_data/backups/ ВНЕ сервера.")
        elif cmd == "import":
            print("Импорт XRP-кошелька по seed (строка s…).")
            seed = getpass.getpass("Seed: ")
            pw = _pw("Пароль для шифрования: ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.import_wallet(seed, pw), ensure_ascii=False, indent=2))
            print("\n⚠️ Скопируй шифр-бэкап из /root/wallet_data/backups/ ВНЕ сервера.")
        elif cmd == "unlock":
            print(json.dumps(w.unlock(_pw()), ensure_ascii=False, indent=2))
            print("\nПароль верный. Разблокировка НЕ сохраняется между командами —\n"
                  "preview/transfer запросят пароль сами.")
        elif cmd == "preview" and len(sys.argv) >= 4:
            dest, amount, tag = sys.argv[2], float(sys.argv[3]), _tag(sys.argv, 4)
            print(_describe(dest, tag))
            w.unlock(_pw())
            print(json.dumps(w.preview_send(dest, amount, tag),
                             ensure_ascii=False, indent=2))
        elif cmd == "transfer" and len(sys.argv) >= 4:
            dest, amount, tag = sys.argv[2], float(sys.argv[3]), _tag(sys.argv, 4)
            if not w.payouts_enabled():
                print("Отправка XRP выключена гейтом XRP_PAYOUTS_ENABLED.\n"
                      "Это не сбой: гейт означает «XRP ещё не выдаём». Включать —\n"
                      "осознанное решение владельца, а не обход из CLI.")
                return 1
            print(_describe(dest, tag))
            w.unlock(_pw())
            prev = w.preview_send(dest, amount, tag)
            print(json.dumps(prev, ensure_ascii=False, indent=2))
            _t_shown = prev.get("destinationTag")
            _t_line = "" if _t_shown is None else f" с тегом {_t_shown}"
            print(f"\nОтправить {amount} XRP на {prev['destination']}{_t_line}?")
            if input("Введите ДА для подтверждения: ").strip().upper() not in ("ДА", "YES"):
                print("Отменено."); return 1
            # Ключ идемпотентности: повтор после сетевого таймаута не отправит
            # те же деньги второй раз. Времени в ключе НЕТ намеренно: раньше в
            # него входило `time()//600`, и повтор, попавший за границу окна,
            # получал ДРУГОЙ ключ — журнал вольта не находил прежнюю попытку и
            # платёж уходил второй раз. Ровно в том случае, ради которого ключ
            # и заводился: сеть ответила неопределённо, оператор повторяет.
            # Цена решения: две ОДИНАКОВЫЕ выплаты одному адресу подряд вторая
            # будет отклонена как дубль — это отказ, а не потеря денег, и
            # снимается явным ярлыком: transfer <адрес> <сумма> [тег] --ref X.
            import hashlib as _h
            idem = _h.sha256(
                f"XRP|{prev['destination']}|{prev.get('destinationTag')}|{amount}|"
                f"{ref}".encode()).hexdigest()[:32]
            if ref:
                print(f"Ярлык повторной выплаты: {ref} (ключ идемпотентности другой)")
            print(json.dumps(w.send(dest, amount, prev["previewId"],
                                    idempotency_key=idem, destination_tag=tag),
                             ensure_ascii=False, indent=2))
        elif cmd == "backup":
            bp = w.XRP_BACKUP_PATH
            if not bp.exists():
                print("Бэкап не найден:", bp); return 1
            pw = _pw("Пароль для проверки бэкапа: ")
            try:
                seed = w._decrypt_secret(json.loads(bp.read_text("utf-8")).get("vault", {}), pw)
                addr = w._wallet_from_seed(seed).classic_address
                print(f"✅ Бэкап валиден. Файл: {bp}\nАдрес из бэкапа: {addr}\n"
                      f"Скопируйте файл в надёжное место (он зашифрован вашим паролем).")
            except Exception:
                print("❌ Пароль не подходит к бэкапу или файл повреждён"); return 1
        else:
            print(__doc__); return 2
    except Exception as e:
        print(f"ОШИБКА: {type(e).__name__}: {e}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
