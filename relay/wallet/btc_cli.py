#!/usr/bin/env python3
"""Админ-CLI горячего кошелька BTC/LTC (secure-контур). Пароль спрашивается
интерактивно (не через аргументы — чтобы не светился в history/ps). Отправка
требует unlock + preview в одном процессе (см. `transfer`).

Команды (COIN = btc | ltc):
  status  COIN | address COIN | balance COIN | backup COIN   — пароль не нужен*
  import  COIN                 — зашифровать сид ЛЕГАСИ-кошелька в вольт (деньги не двигаются)
  import-xprv COIN             — импорт по внешнему мастер-ключу
  unlock  COIN                 — проверить пароль
  preview COIN <to> <amount>
  transfer COIN <to> <amount>  — ⭐ весь путь (пароль→превью→подтверждение→отправка)

  *balance/backup требуют, чтобы вольт уже был создан (import).

⚠️ Разлочка живёт в памяти процесса, а каждый запуск CLI — отдельный процесс,
поэтому используйте `transfer`: он проводит пароль→превью→отправку за один запуск
(превью живёт 120 с и не истечёт между шагами).
"""
import getpass
import json
import os
import sys
from pathlib import Path

# путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wallet import btc_wallet as w  # noqa: E402


def _pw(prompt="Пароль кошелька: "):
    """Пароль только из настоящего терминала или из файла с правами 600."""
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
            "        /root/bot/venv/bin/python3 /root/relay/wallet/btc_cli.py import btc\n"
            "    shred -u /root/.wallet_pw\n")
    return getpass.getpass(prompt)


def _coin(argv, idx=2):
    if len(argv) <= idx:
        raise SystemExit("Укажите монету: btc | ltc")
    c = argv[idx].upper()
    if c not in ("BTC", "LTC"):
        raise SystemExit("Монета должна быть btc или ltc")
    return c


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    cmd = sys.argv[1]
    try:
        if cmd == "status":
            print(json.dumps(w.status(_coin(sys.argv)), ensure_ascii=False, indent=2))
        elif cmd == "address":
            print(w.address(_coin(sys.argv)) or "(кошелёк не создан)")
        elif cmd == "balance":
            print(json.dumps(w.balance(_coin(sys.argv)), ensure_ascii=False, indent=2))
        elif cmd == "import":
            coin = _coin(sys.argv)
            print(f"Импорт сида ЛЕГАСИ-кошелька {coin} в шифрованный вольт.\n"
                  f"Средства НЕ двигаются, адреса пополнения НЕ меняются.")
            pw = _pw("Новый пароль вольта (мин 10 символов): ")
            if pw != _pw("Повторите пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.import_from_legacy(coin, pw), ensure_ascii=False, indent=2))
        elif cmd == "reimport":
            coin = _coin(sys.argv)
            print(f"РОТАЦИЯ пароля вольта {coin}: сид берётся заново из легаси-кошелька,\n"
                  f"вольт/бэкап пере-шифровываются НОВЫМ паролем. Средства не двигаются.")
            pw = _pw("НОВЫЙ пароль вольта (мин 10 символов): ")
            if pw != _pw("Повторите новый пароль: "):
                print("Пароли не совпадают"); return 1
            print(json.dumps(w.import_from_legacy(coin, pw, overwrite=True),
                             ensure_ascii=False, indent=2))
            print("\n✅ Пароль сменён. Старый пароль больше не подходит к новому вольту.\n"
                  "⚠️ Скопируй НОВЫЙ бэкап из /root/wallet_data/backups/ и уничтожь старые копии\n"
                  "   (они расшифровываются старым, засвеченным паролем).")
        elif cmd == "import-xprv":
            coin = _coin(sys.argv)
            xprv = getpass.getpass("Мастер-ключ (zprv/xprv/Mtpv…): ")
            pw = _pw("Пароль для шифрования: ")
            print(json.dumps(w.import_wallet(coin, xprv, pw), ensure_ascii=False, indent=2))
        elif cmd == "unlock":
            coin = _coin(sys.argv)
            print(json.dumps(w.unlock(coin, _pw()), ensure_ascii=False, indent=2))
            print("\nПароль верный. Отдельная разблокировка НЕ сохраняется между\n"
                  "командами — preview/transfer запросят пароль сами.")
        elif cmd == "preview" and len(sys.argv) >= 5:
            coin = _coin(sys.argv)
            w.unlock(coin, _pw())
            print(json.dumps(w.preview_send(coin, sys.argv[3], float(sys.argv[4])),
                             ensure_ascii=False, indent=2))
        elif cmd == "transfer" and len(sys.argv) >= 5:
            coin = _coin(sys.argv)
            to, amount = sys.argv[3], float(sys.argv[4])
            w.unlock(coin, _pw())
            prev = w.preview_send(coin, to, amount)
            print(json.dumps(prev, ensure_ascii=False, indent=2))
            print(f"\nОтправить {amount} {coin} на {to}?")
            if input("Введите ДА для подтверждения: ").strip().upper() not in ("ДА", "YES"):
                print("Отменено."); return 1
            import hashlib as _h, time as _t
            idem = _h.sha256(f"{coin}|{to}|{amount}|{int(_t.time()//600)}".encode()).hexdigest()[:32]
            print(json.dumps(w.send(coin, to, amount, prev["previewId"], idempotency_key=idem),
                             ensure_ascii=False, indent=2))
        elif cmd == "restore-legacy":
            coin = _coin(sys.argv)
            print(f"Восстановление легаси-кошелька {coin} из сида вольта "
                  f"(средства не двигаются).")
            pw = _pw("Пароль вольта: ")
            res = w.restore_legacy(coin, pw)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            if res.get("restored") and res.get("xpubMatch"):
                print("\n✅ Легаси-кошелёк восстановлен, xpub совпал. Теперь можно reimport.")
            elif res.get("alreadyPresent"):
                print("\nℹ️ Легаси-кошелёк уже на месте.")
        elif cmd == "harden":
            coin = _coin(sys.argv)
            print(f"ФАЗА 3 для {coin}: убрать приватный ключ из bitcoinlib.sqlite\n"
                  f"(легаси-кошелёк → watch-only). Единственная копия сида останется\n"
                  f"в шифр-вольте. ПЕРЕД этим убедись: (1) пароль РОТИРОВАН после утечки,\n"
                  f"(2) шифр-бэкап скопирован ВНЕ сервера.\n"
                  f"Проверки идут ДО удаления — при несходстве легаси не тронут.")
            if input("Продолжить? Введите ДА: ").strip().upper() not in ("ДА", "YES"):
                print("Отменено."); return 1
            pw = _pw("Пароль вольта (для проверки перед удалением): ")
            res = w.to_watch_only(coin, pw)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            if res.get("watchOnly") and not res.get("privateKeyPresent") and res.get("addressesMatch"):
                print("\n✅ Готово: приватный ключ удалён из bitcoinlib.sqlite, адреса сходятся,\n"
                      "   баланс читается (watch-only). Отправка идёт через вольт.")
            elif res.get("alreadyWatchOnly"):
                print("\nℹ️ Уже watch-only — приватного ключа в bitcoinlib.sqlite нет.")
            else:
                print("\n⚠️ Проверь вывод: что-то не сошлось.")
        elif cmd == "backup":
            coin = _coin(sys.argv)
            bp = w._backup_path(coin)
            if not bp.exists():
                print("Бэкап не найден:", bp); return 1
            pw = _pw("Пароль для проверки бэкапа: ")
            try:
                zprv = w._decrypt_secret(json.loads(bp.read_text("utf-8")), pw, w._coin(coin)["aad"])
                wallet_obj, cleanup = w._ephemeral_wallet(coin, zprv)
                try:
                    addr = wallet_obj.addresslist()[0]
                finally:
                    cleanup()
                print(f"✅ Бэкап валиден. Файл: {bp}\nПервый адрес из бэкапа: {addr}\n"
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
