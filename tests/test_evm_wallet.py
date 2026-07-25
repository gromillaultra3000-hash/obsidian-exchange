#!/usr/bin/env python3
"""Offline-тесты secure-контура EVM-кошелька (ETH + ERC-20 USDT).

Не ходят в сеть (RPC не дёргаются): проверяют шифр-вольт, разлочку, lockout,
криптопроверку бэкапа, валидацию адреса, потолок отправки, кодирование ERC-20
transfer и идемпотентный журнал.

⚠️ Изоляция: WALLET_DATA_DIR указывает на TEMP до импорта модуля — тесты НЕ
трогают боевой /root/wallet_data (урок BTC-сессии: тесты кошелька работают в
изолированном каталоге).

Запуск: /root/bot/venv/bin/python3 tests/test_evm_wallet.py
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="evm_wallet_test_")
os.environ["WALLET_DATA_DIR"] = _TMP
os.environ["EVM_CHAIN_ID"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from wallet import evm_wallet as E  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


PW = "test-password-123"

# Известный тест-вектор (широко известный ключ 0x00..01 из документации eth).
KNOWN_KEY = "0000000000000000000000000000000000000000000000000000000000000001"
KNOWN_ADDR = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"

# ── шифрование round-trip ─────────────────────────────────────────────────────
enc = E._encrypt_secret(KNOWN_KEY, PW)
check("шифр round-trip: расшифровка тем же паролем даёт исходный ключ",
      E._decrypt_secret(enc, PW) == KNOWN_KEY)
try:
    E._decrypt_secret(enc, "wrong")
    check("шифр: неверный пароль → отказ", False)
except Exception:
    check("шифр: неверный пароль → отказ", True)

# ── импорт известного ключа → известный адрес ─────────────────────────────────
res = E.import_wallet(KNOWN_KEY, PW)
check("импорт: адрес совпал с тест-вектором", res["address"] == KNOWN_ADDR)
check("импорт: backupConfirmed (криптопроверка бэкапа прошла)", res["backupConfirmed"] is True)
check("статус: configured + unlocked после импорта",
      E.status()["configured"] and E.status()["unlocked"])
check("адрес читается из меты", E.address() == KNOWN_ADDR)

# ── вольт/бэкап на диске под 600 и вне git ────────────────────────────────────
import stat as _stat
mode = _stat.S_IMODE(os.stat(E.EVM_VAULT_PATH).st_mode)
check("вольт на диске с правами 600", mode == 0o600)
check("в вольте нет открытого приватного ключа",
      KNOWN_KEY not in E.EVM_VAULT_PATH.read_text("utf-8"))

# ── повторный импорт без overwrite → отказ ────────────────────────────────────
try:
    E.import_wallet(KNOWN_KEY, PW)
    check("повторный импорт без overwrite → отказ", False)
except FileExistsError:
    check("повторный импорт без overwrite → отказ", True)

# ── lock / unlock / неверный пароль / lockout ─────────────────────────────────
E.lock()
check("после lock — signer заблокирован", not E.status()["unlocked"])
check("unlock верным паролем", E.unlock(PW)["unlocked"] is True)
E.lock()
bad = 0
for _ in range(5):
    try:
        E.unlock("nope")
    except ValueError:
        bad += 1
    except PermissionError:
        bad += 1
check("5 неверных паролей отклонены", bad == 5)
try:
    E.unlock("nope")
    check("после 5 промахов — временный lockout", False)
except PermissionError:
    check("после 5 промахов — временный lockout", True)
except ValueError:
    # если счётчик сбросился на 6-й — это тоже отказ, но lockout ожидаем
    check("после 5 промахов — временный lockout", False)

# сбрасываем lockout для дальнейших проверок (внутреннее состояние)
E._LOCKOUT_UNTIL = 0.0
E._FAILED_ATTEMPTS = 0
E.unlock(PW)

# ── валидация адреса ──────────────────────────────────────────────────────────
check("валидный адрес принят", E._is_valid_address(KNOWN_ADDR))
check("мусорный адрес отклонён", not E._is_valid_address("0x1234"))
check("не-hex адрес отклонён", not E._is_valid_address("0x" + "z" * 40))

# ── потолок отправки (fail-closed, без сети) ──────────────────────────────────
try:
    E.preview_send("ETH", KNOWN_ADDR, E.MAX_SEND["ETH"] + 1)
    check("сумма выше MAX_SEND → отказ (до сети)", False)
except ValueError as e:
    check("сумма выше MAX_SEND → отказ (до сети)", "amount_exceeds_max_send" in str(e))

# preview без разлочки → отказ
E.lock()
try:
    E.preview_send("ETH", KNOWN_ADDR, 0.001)
    check("preview без разлочки → отказ", False)
except PermissionError:
    check("preview без разлочки → отказ", True)
E.unlock(PW)

# неподдерживаемый актив → отказ
try:
    E.preview_send("DOGE", KNOWN_ADDR, 1)
    check("неподдерживаемый актив → отказ", False)
except ValueError as e:
    check("неподдерживаемый актив → отказ", "asset_not_supported" in str(e))

# ── кодирование ERC-20 transfer(address,uint256) ──────────────────────────────
data = E._erc20_transfer_data(KNOWN_ADDR, 1_000_000)  # 1 USDT (6 знаков)
check("ERC-20 transfer: селектор a9059cbb", data.startswith("0xa9059cbb"))
check("ERC-20 transfer: длина 4+32+32 байта",
      len(data) == 2 + 8 + 64 + 64)
check("ERC-20 transfer: адрес получателя в data (padded)",
      KNOWN_ADDR.lower()[2:] in data.lower())
check("ERC-20 transfer: сумма 0xf4240 (1e6) в хвосте",
      data.endswith(format(1_000_000, "x").rjust(64, "0")))

# ── идемпотентный журнал ──────────────────────────────────────────────────────
sends = E._load_sends()
sends["payout_777"] = {"txHash": "0xabc", "status": "CONFIRMED", "asset": "USDT", "amount": 5.0}
E._save_sends(sends)
check("идемпотентность: журнал сохраняется/читается",
      E._load_sends().get("payout_777", {}).get("txHash") == "0xabc")

# отправка с уже завершённым ключом возвращает тот же tx без повторной подписи
r = E.send("USDT", KNOWN_ADDR, 5.0, preview_id="whatever", idempotency_key="payout_777")
check("идемпотентность: повтор с тем же ключом → тот же txHash, idempotent=True",
      r.get("txHash") == "0xabc" and r.get("idempotent") is True)

# ── битый EIP-55 checksum отклоняется (Codex: is_address его пропускал) ─────────
bad_mixed = KNOWN_ADDR[:10] + ("A" if KNOWN_ADDR[10] != "A" else "b") + KNOWN_ADDR[11:]
check("битый mixed-case checksum отклонён", not E._is_valid_address(bad_mixed))
check("all-lower адрес принят", E._is_valid_address(KNOWN_ADDR.lower()))
check("all-upper адрес принят", E._is_valid_address("0x" + KNOWN_ADDR[2:].upper()))

# ── claim 'signing' блокирует повторную подпись того же ключа ──────────────────
E._save_sends({**E._load_sends(),
               "busy_key": {"status": "signing", "to": KNOWN_ADDR, "amount": 1.0}})
try:
    E.send("ETH", KNOWN_ADDR, 1.0, preview_id="x", idempotency_key="busy_key")
    check("claim 'signing' → send_in_progress (нет второй подписи)", False)
except PermissionError as e:
    check("claim 'signing' → send_in_progress (нет второй подписи)",
          "send_in_progress" in str(e))

# ── FAILED-запись при реконсиляции бросает (не «тихий успех») ──────────────────
E._save_sends({**E._load_sends(),
               "failed_key": {"status": "FAILED", "txHash": "0xdead", "to": KNOWN_ADDR, "amount": 1.0}})
try:
    E.send("ETH", KNOWN_ADDR, 1.0, preview_id="x", idempotency_key="failed_key")
    check("FAILED-запись → повтор бросает", False)
except RuntimeError as e:
    check("FAILED-запись → повтор бросает", "evm_transaction_failed" in str(e))

# ── потолок комиссии ──────────────────────────────────────────────────────────
try:
    E._check_fee_cap(int(E.MAX_FEE_ETH * 1e18) + 1)
    check("комиссия выше потолка → отказ", False)
except ValueError as e:
    check("комиссия выше потолка → отказ", "evm_fee_exceeds_cap" in str(e))

# ── idempotency_key обязателен (без него нет защиты от двойной выплаты) ─────────
try:
    E.send("ETH", KNOWN_ADDR, 0.001, preview_id="x", idempotency_key="")
    check("send без idempotency_key → отказ", False)
except ValueError as e:
    check("send без idempotency_key → отказ", "idempotency_key_required" in str(e))

# ── _load_sends fail-closed: битый/пустой журнал не читается как пустой ─────────
E.EVM_SENDS_PATH.write_text("{ это не JSON ", encoding="utf-8")
try:
    E._load_sends()
    check("битый журнал отправок → отказ (не пустой)", False)
except RuntimeError as e:
    check("битый журнал отправок → отказ (не пустой)", "corrupt" in str(e))
# существующий, но ПУСТОЙ файл = обрезка → тоже отказ (защита от повторной выплаты)
E.EVM_SENDS_PATH.write_text("", encoding="utf-8")
try:
    E._load_sends()
    check("пустой (обрезанный) журнал → отказ", False)
except RuntimeError as e:
    check("пустой (обрезанный) журнал → отказ", "corrupt" in str(e))
# отсутствие файла = легитимно пусто
E.EVM_SENDS_PATH.unlink()
check("отсутствующий журнал → {} (легитимно)", E._load_sends() == {})
E._save_sends({})  # восстановим валидный для дальнейших проверок

# ── межпроцессный flock берётся и отпускается без ошибок ───────────────────────
try:
    with E._proc_lock():
        pass
    with E._proc_lock():
        pass
    check("_proc_lock: захват/освобождение работает", True)
except Exception as _e:
    check("_proc_lock: захват/освобождение работает", False)

# ── hex-хелперы ───────────────────────────────────────────────────────────────
check("_to_int('0x10')==16", E._to_int("0x10") == 16)
check("_to_int(None)==0", E._to_int(None) == 0)
check("_hex(255)=='0xff'", E._hex(255) == "0xff")

# уборка
import shutil  # noqa: E402
shutil.rmtree(_TMP, ignore_errors=True)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
