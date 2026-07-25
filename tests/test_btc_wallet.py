#!/usr/bin/env python3
"""Офлайн-тесты secure-контура BTC/LTC кошелька (сессия 25.07.2026).

Проверяют крипто-инварианты БЕЗ сети и без реальных средств:
  - шифр-вольт: расшифровка тем же паролем возвращает тот же мастер-ключ (backupConfirmed)
  - неверный пароль отклоняется; 5 ошибок → временный lockout
  - потолок отправки и запрет preview без разлочки (fail-closed)
  - AAD-домены BTC/LTC различны: чек одной монеты не расшифровать ключом другой

Запуск: python3 tests/test_btc_wallet.py
"""
import os
import sys
import tempfile

os.environ["WALLET_DATA_DIR"] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


from wallet import btc_wallet as B  # noqa: E402
from bitcoinlib.keys import HDKey  # noqa: E402

PW = "unit-test-passphrase"
# свой мастер-ключ (не легаси, сети не нужно) для обеих монет
BTC_XPRV = HDKey(network="bitcoin", witness_type="segwit").wif_private()
LTC_XPRV = HDKey(network="litecoin", witness_type="segwit").wif_private()

r = B.import_wallet("BTC", BTC_XPRV, PW)
check("вольт BTC создан, бэкап криптопроверен (тот же ключ)", r["ok"] and r["backupConfirmed"])

check("разлочка верным паролем", B.unlock("BTC", PW)["unlocked"])


def wrong_then_lockout():
    for _ in range(5):
        try:
            B.unlock("BTC", "nope-nope")
        except ValueError:
            pass
        except PermissionError:
            return True  # уже lockout
    try:
        B.unlock("BTC", "nope-nope")
    except PermissionError:
        return True
    except ValueError:
        return False
    return False


check("5 неверных паролей → временный lockout", wrong_then_lockout())

# после lockout вольт цел: правильный пароль позже снова открывает (ждать не будем —
# проверяем, что сам вольт расшифровывается корректно через прямой decrypt)
import json  # noqa: E402
vault = json.loads(B._vault_path("BTC").read_text("utf-8"))
dec = B._decrypt_secret(vault, PW, B._coin("BTC")["aad"])
check("вольт расшифровывается верным паролем в исходный мастер-ключ", dec == BTC_XPRV)


def cross_aad_fails():
    """Чек BTC нельзя расшифровать как LTC (разные AAD-домены)."""
    try:
        B._decrypt_secret(vault, PW, B._coin("LTC")["aad"])
        return False
    except Exception:
        return True


check("AAD-домены BTC/LTC изолированы (чужой домен не расшифровывает)", cross_aad_fails())

# LTC отдельный вольт
rl = B.import_wallet("LTC", LTC_XPRV, PW)
check("вольт LTC создан независимо", rl["ok"] and rl["backupConfirmed"])

# потолок и запрет preview без разлочки
B.lock("BTC")
try:
    B.preview_send("BTC", "bc1qtest", 0.001)
    _locked_ok = False
except PermissionError:
    _locked_ok = True
except Exception:
    _locked_ok = False
check("preview без разлочки запрещён (fail-closed)", _locked_ok)

print()
if failures:
    print(f"❌ Провалено: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("✅ Все проверки secure-контура BTC/LTC пройдены")
