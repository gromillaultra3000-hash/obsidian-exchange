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
  transfer <ASSET> <to> <amount>                    — ⭐ весь путь (пароль→превью→подтверждение→отправка)

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

sys.path.insert(0, "/root/relay")
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


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
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
            import hashlib as _h, time as _t
            idem = _h.sha256(f"{asset}|{to}|{amount}|{int(_t.time()//600)}".encode()).hexdigest()[:32]
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
