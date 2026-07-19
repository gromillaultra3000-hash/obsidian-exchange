#!/usr/bin/env python3
"""Админ-CLI горячего кошелька TRON. Пароль спрашивается интерактивно (не через
аргументы, чтобы не светился в history/ps). Отправка требует unlock + preview.

Команды:
  status | address | balance | create | import | unlock | lock
  preview <asset> <to> <amount> | send <asset> <to> <amount> <preview_id>
"""
import sys, getpass, json, os
sys.path.insert(0, "/root/relay")
from wallet import tron_wallet as w


def _pw(prompt="Пароль кошелька: "):
    return getpass.getpass(prompt)


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    cmd = sys.argv[1]
    try:
        if cmd == "status":
            print(json.dumps(w.tron_status(), ensure_ascii=False, indent=2))
        elif cmd == "address":
            print(w.tron_address() or "(кошелёк не создан)")
        elif cmd == "balance":
            print(json.dumps(w.tron_balance(), ensure_ascii=False, indent=2))
        elif cmd == "create":
            pw = _pw("Новый пароль (мин 10 символов): ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.create_tron_wallet(pw), ensure_ascii=False, indent=2))
        elif cmd == "import":
            key = getpass.getpass("Приватный ключ (hex): ")
            pw = _pw("Пароль для шифрования: ")
            print(json.dumps(w.import_tron_wallet(key, pw), ensure_ascii=False, indent=2))
        elif cmd == "unlock":
            print(json.dumps(w.unlock_tron_wallet(_pw()), ensure_ascii=False, indent=2))
        elif cmd == "lock":
            print(json.dumps(w.lock_tron_wallet(), ensure_ascii=False, indent=2))
        elif cmd == "preview" and len(sys.argv) >= 5:
            print(json.dumps(w.preview_tron_send(sys.argv[2], sys.argv[3], float(sys.argv[4])), ensure_ascii=False, indent=2))
        elif cmd == "send" and len(sys.argv) >= 6:
            idem = sys.argv[6] if len(sys.argv) >= 7 else ""
            print(json.dumps(w.send_tron_asset(sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5], idempotency_key=idem), ensure_ascii=False, indent=2))
        elif cmd == "backup":
            # проверка восстановимости: бэкап расшифровывается паролем и даёт тот же адрес
            import json as _j
            from pathlib import Path as _P
            bp = w.TRON_BACKUP_PATH
            if not _P(bp).exists():
                print("Бэкап не найден:", bp); return 1
            pw = _pw("Пароль для проверки бэкапа: ")
            try:
                key_hex = w._decrypt_secret(_j.loads(_P(bp).read_text("utf-8")), pw)
                addr = w._priv(key_hex).public_key.to_base58check_address()
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
