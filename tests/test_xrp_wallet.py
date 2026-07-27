#!/usr/bin/env python3
"""Офлайн-тесты secure-кошелька XRP (relay/wallet/xrp_wallet.py).

Сеть НЕ дёргается: проверяем вольт, гейты, разбор адресов и двухшаговую
отправку до момента подписи. Ловит: (1) гейт выплат по умолчанию ВЫКЛ;
(2) вольт шифруется и не расшифровывается чужим паролем/чужим доменом AAD;
(3) lockout после серии неверных паролей; (4) destination tag не теряется
(на XRPL перевод без тега на биржу = потеря средств для получателя);
(5) резерв аккаунта не даёт отправить весь баланс.

⚠️ Запускать ТОЛЬКО с изолированным WALLET_DATA_DIR (тест выставляет сам) —
иначе тронет боевые вольты.

Запуск: /root/bot/venv/bin/python3 tests/test_xrp_wallet.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="xrp_wallet_test_")
os.environ["WALLET_DATA_DIR"] = _TMP          # ДО импорта модуля
os.environ.pop("XRP_PAYOUTS_ENABLED", None)
sys.path.insert(0, os.path.join(ROOT, "relay"))

from wallet import xrp_wallet as X  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


if not X.library_available():
    print("⏭  xrpl-py недоступен — запустите в venv бота: "
          "/root/bot/venv/bin/python3 tests/test_xrp_wallet.py")
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(0)

check("изолированный каталог (боевые вольты не тронуты)", str(X.DATA) == _TMP)

# ── гейт ────────────────────────────────────────────────────────────────────
check("гейт выплат по умолчанию ВЫКЛ", X.payouts_enabled() is False)
for v in ("1", "true", "YES", "on"):
    os.environ["XRP_PAYOUTS_ENABLED"] = v
    check(f"гейт включается значением {v!r}", X.payouts_enabled() is True)
os.environ.pop("XRP_PAYOUTS_ENABLED", None)

# ── статус до создания ──────────────────────────────────────────────────────
st = X.status()
check("до создания вольта configured=False", st["configured"] is False)
check("до создания вольта unlocked=False", st["unlocked"] is False)

# ── создание вольта и разлочка ──────────────────────────────────────────────
PW = "test-password-обсидиан-1"
info = X.create_wallet(PW)
check("вольт создан, адрес выдан", bool(info.get("address", "").startswith("r")))
check("шифр-бэкап записан", os.path.exists(info["backup"]))
check("после создания configured=True", X.status()["configured"] is True)

check("разлочка верным паролем", X.unlock(PW)["unlocked"] is True)
check("адрес после разлочки совпадает", X.status()["address"] == info["address"])
check("lock() запирает", X.lock()["unlocked"] is False)

try:
    X.unlock("неверный-пароль")
    check("неверный пароль отвергнут", False)
except ValueError:
    check("неверный пароль отвергнут", True)

# lockout после серии неудач
for _ in range(X._LOCKOUT_AFTER):
    try:
        X.unlock("опять-неверный")
    except Exception:
        pass
try:
    X.unlock(PW)
    check("после серии неудач включается lockout", False)
except RuntimeError as e:
    check("после серии неудач включается lockout", "locked_out" in str(e))
# Счётчик должен пережить «перезапуск процесса» — он на диске, не в памяти
check("lockout сохранён на диске (переживает перезапуск)",
      os.path.exists(X.XRP_LOCKOUT_PATH) and X._lockout_state().get("until", 0) > 0)
X._lockout_save(0, 0.0)   # снимаем для остальных проверок

# ── изоляция домена шифрования ──────────────────────────────────────────────
vault = X._read_json(X.XRP_VAULT_PATH, {})
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    key = X._derive(PW, base64.b64decode(vault["salt"]))
    AESGCM(key).decrypt(base64.b64decode(vault["nonce"]),
                        base64.b64decode(vault["ciphertext"]), b"OBSIDIAN-EVM-V1")
    check("ключ XRP не расшифровывается под доменом EVM", False)
except Exception:
    check("ключ XRP не расшифровывается под доменом EVM", True)

# ── разбор адресов и destination tag ────────────────────────────────────────
X.unlock(PW)
addr = X.status()["address"]
check("classic-адрес принят", X.is_valid_address(addr))
check("адрес с опечаткой отвергнут", not X.is_valid_address(addr[:-1] + ("x" if addr[-1] != "x" else "y")))
check("пустой адрес отвергнут", not X.is_valid_address(""))
check("None не роняет", not X.is_valid_address(None))
check("BTC-адрес не проходит как XRP",
      not X.is_valid_address("1BoatSLRHtKNngkdXEeobR76b53LETtpyT"))

# X-адрес несёт тег внутри — он обязан извлечься
from xrpl.core import addresscodec  # noqa: E402
xaddr = addresscodec.classic_address_to_xaddress(addr, 12345, False)
classic, tag = X.parse_destination(xaddr)
check("X-адрес разбирается в classic + tag", classic == addr and tag == 12345)

# ── двухшаговая отправка ────────────────────────────────────────────────────
try:
    X.preview_send(addr, 1.0)
    check("preview без средств отклоняется (резерв аккаунта)", False)
except ValueError as e:
    check("preview без средств отклоняется (резерв аккаунта)",
          "insufficient_spendable" in str(e))

try:
    X.preview_send(addr, X.MAX_SEND_XRP + 1)
    check("сумма выше потолка отклоняется", False)
except ValueError as e:
    check("сумма выше потолка отклоняется", "amount_exceeds_max_send" in str(e))

try:
    X.preview_send("не-адрес", 1.0)
    check("preview на битый адрес отклоняется", False)
except ValueError as e:
    check("preview на битый адрес отклоняется", "invalid_destination" in str(e))

try:
    X.preview_send(addr, -1)
    check("отрицательная сумма отклоняется", False)
except ValueError:
    check("отрицательная сумма отклоняется", True)

# ── destination tag: 0 — валидное значение и НЕ равно «тега нет» ────────────
check("тег 0 отличается от отсутствия тега", not X._same_tag(0, None))
check("тег 0 равен тегу 0", X._same_tag(0, 0))
check("None равен None", X._same_tag(None, None))
check("_norm_tag(0) сохраняет ноль", X._norm_tag(0) == 0)
check("_norm_tag(None) → None", X._norm_tag(None) is None)
for bad in (1.9, "12", -1, 2**32, True):
    try:
        X._norm_tag(bad)
        check(f"тег {bad!r} отвергнут", False)
    except ValueError:
        check(f"тег {bad!r} отвергнут", True)
check("_norm_tag принимает верхнюю границу", X._norm_tag(0xFFFFFFFF) == 0xFFFFFFFF)

# ── идемпотентность и гейт ──────────────────────────────────────────────────
# send без ключа идемпотентности запрещён (иначе повтор после таймаута = вторая выплата)
try:
    X.send(addr, 1.0, "любой-preview-id")
    check("send без ключа идемпотентности запрещён", False)
except ValueError as e:
    check("send без ключа идемпотентности запрещён", "idempotency_key_required" in str(e))

# send без гейта не должен даже пытаться
try:
    X.send(addr, 1.0, "любой-preview-id", idempotency_key="k1")
    check("send при выключенном гейте запрещён", False)
except RuntimeError as e:
    check("send при выключенном гейте запрещён", "xrp_payouts_disabled" in str(e))

# при включённом гейте, но с несуществующим preview — тоже отказ
os.environ["XRP_PAYOUTS_ENABLED"] = "1"
try:
    X.send(addr, 1.0, "несуществующий", idempotency_key="k2")
    check("send с неизвестным preview запрещён", False)
except ValueError as e:
    check("send с неизвестным preview запрещён", "preview_not_found" in str(e))

# незавершённая отправка (in_flight) блокирует повтор — деньги могли уйти
X._atomic_write(X.XRP_SENDS_PATH, __import__("json").dumps(
    {"k-inflight": {"state": "in_flight", "account": addr, "claimedAt": "…"}}))
try:
    X.send(addr, 1.0, "любой", idempotency_key="k-inflight")
    check("повтор после незавершённой отправки ЗАПРЕЩЁН", False)
except RuntimeError as e:
    check("повтор после незавершённой отправки ЗАПРЕЩЁН", "send_result_unknown" in str(e))

# уже отправленное возвращается, а не отправляется снова
X._atomic_write(X.XRP_SENDS_PATH, __import__("json").dumps(
    {"k-done": {"state": "sent", "txHash": "ABC", "amountXrp": 1.0}}))
check("повтор по ключу возвращает прежний результат",
      X.send(addr, 1.0, "любой", idempotency_key="k-done").get("txHash") == "ABC")

# повреждённый журнал отправок → ОТКАЗ, а не «платежей не было»
X.XRP_SENDS_PATH.write_text("{это не json", encoding="utf-8")
try:
    X.send(addr, 1.0, "любой", idempotency_key="k3")
    check("повреждённый журнал запрещает отправку (fail-closed)", False)
except RuntimeError as e:
    check("повреждённый журнал запрещает отправку (fail-closed)", "journal_unreadable" in str(e))
X.XRP_SENDS_PATH.unlink()

# заперт → отправка невозможна даже с гейтом и корректным ключом
X.lock()
try:
    X.send(addr, 1.0, "любой", idempotency_key="k4")
    check("send при запертом кошельке запрещён", False)
except RuntimeError as e:
    check("send при запертом кошельке запрещён", "wallet_locked" in str(e))
os.environ.pop("XRP_PAYOUTS_ENABLED", None)

# ── резерв ──────────────────────────────────────────────────────────────────
check("резерв аккаунта положительный", X.BASE_RESERVE_XRP > 0)
check("spendable не уходит в минус на пустом счёте", X.spendable(addr) == 0.0)

shutil.rmtree(_TMP, ignore_errors=True)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
