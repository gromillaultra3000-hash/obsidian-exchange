#!/usr/bin/env python3
"""Админ-CLI горячего кошелька EVM (ETH + ERC-20 USDT). Пароль спрашивается
интерактивно (не через аргументы — чтобы не светился в history/ps) либо из файла
с правами 600 (WALLET_PASSWORD_FILE).

Команды:
  status | address | balance                       — пароль не нужен*
  create                                            — создать НОВЫЙ кошелёк (свой ключ)
  import                                            — импорт по приватному ключу (hex)
  backup                                            — проверить шифр-бэкап паролем
  unlock                                            — проверить пароль
  preview  <ASSET> <to> <amount>
  transfer <ASSET> <to> <amount> [--ref ЯРЛЫК]      — ⭐ весь путь (пароль→превью→подтверждение→отправка)

  --ref — только чтобы СОЗНАТЕЛЬНО отправить второй одинаковый платёж на тот же
  адрес: без него повтор той же команды опознаётся как дубль и денег не тронет.

  ASSET = ETH | USDT
  *balance требует, чтобы вольт уже был создан.

⚠️ Разлочка живёт в памяти процесса, а каждый запуск CLI — отдельный процесс,
поэтому для отправки используйте `transfer`: он проводит пароль→превью→отправку
за один запуск (превью живёт 120 с и не истечёт между шагами).
"""
import getpass
import json
import os
import sys
from pathlib import Path

# путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wallet import evm_wallet as w  # noqa: E402


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
            "        /root/bot/venv/bin/python3 /root/relay/wallet/evm_cli.py import\n"
            "    shred -u /root/.wallet_pw\n")
    return getpass.getpass(prompt)


def _asset(argv, idx=2):
    if len(argv) <= idx:
        raise SystemExit("Укажите актив: ETH | USDT")
    a = argv[idx].upper()
    if a != "ETH" and a not in w.ERC20_TOKENS:
        raise SystemExit("Актив должен быть ETH или USDT")
    return a


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
            print(w.address() or "(кошелёк не создан)")
        elif cmd == "balance":
            print(json.dumps(w.balance(), ensure_ascii=False, indent=2))
        elif cmd == "create":
            print("Создание НОВОГО EVM-кошелька (ETH + ERC-20). Приватный ключ\n"
                  "генерируется и сразу шифруется паролем.")
            pw = _pw("Новый пароль вольта (мин 10 символов): ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.create_wallet(pw), ensure_ascii=False, indent=2))
            print("\n⚠️ Скопируй шифр-бэкап из /root/wallet_data/backups/ ВНЕ сервера.")
        elif cmd == "import":
            print("Импорт EVM-кошелька по приватному ключу (hex, 64 символа).")
            xprv = getpass.getpass("Приватный ключ (0x…): ")
            pw = _pw("Пароль для шифрования: ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.import_wallet(xprv, pw), ensure_ascii=False, indent=2))
            print("\n⚠️ Скопируй шифр-бэкап из /root/wallet_data/backups/ ВНЕ сервера.")
        elif cmd == "unlock":
            print(json.dumps(w.unlock(_pw()), ensure_ascii=False, indent=2))
            print("\nПароль верный. Разблокировка НЕ сохраняется между командами —\n"
                  "preview/transfer запросят пароль сами.")
        elif cmd == "preview" and len(sys.argv) >= 5:
            asset = _asset(sys.argv)
            w.unlock(_pw())
            print(json.dumps(w.preview_send(asset, sys.argv[3], float(sys.argv[4])),
                             ensure_ascii=False, indent=2))
        elif cmd == "transfer" and len(sys.argv) >= 5:
            asset = _asset(sys.argv)
            to, amount = sys.argv[3], float(sys.argv[4])
            w.unlock(_pw())
            prev = w.preview_send(asset, to, amount)
            print(json.dumps(prev, ensure_ascii=False, indent=2))
            print(f"\nОтправить {amount} {asset} на {to}?")
            if input("Введите ДА для подтверждения: ").strip().upper() not in ("ДА", "YES"):
                print("Отменено."); return 1
            # Времени в ключе НЕТ намеренно: раньше в него входило
            # `time()//600`, и повтор после неопределённого ответа сети, попавший
            # за границу окна, получал ДРУГОЙ ключ — журнал вольта не находил
            # прежнюю попытку и деньги уходили второй раз. Ровно тот случай,
            # ради которого ключ и заводился. Сознательный второй одинаковый
            # платёж на тот же адрес — через явный ярлык --ref.
            import hashlib as _h
            idem = _h.sha256(f"{asset}|{to}|{amount}|{ref}".encode()).hexdigest()[:32]
            if ref:
                print(f"Ярлык повторной выплаты: {ref} (ключ идемпотентности другой)")
            print(json.dumps(w.send(asset, to, amount, prev["previewId"], idempotency_key=idem),
                             ensure_ascii=False, indent=2))
        elif cmd == "backup":
            bp = w.EVM_BACKUP_PATH
            if not bp.exists():
                print("Бэкап не найден:", bp); return 1
            pw = _pw("Пароль для проверки бэкапа: ")
            try:
                key_hex = w._decrypt_secret(json.loads(bp.read_text("utf-8")), pw)
                addr = w._address_of(key_hex)
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
