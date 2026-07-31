#!/usr/bin/env python3
"""Ссылка на транзакцию: показываем только настоящую или не показываем вовсе.

Кнопка «🔍 Транзакция в блокчейне» — единственное доказательство выдачи, которое
клиент может проверить сам. Сломанная ссылка выглядит как доказательство и им не
является, поэтому цена ошибки здесь выше обычной опечатки в интерфейсе.

Главная проверка внизу: у КАЖДОЙ валюты реестра есть свой обозреватель. Она
падает, когда в проект добавляют монету и забывают про последний шаг — ровно так
XRP и ETH оказались с пустой кнопкой, пока карта ссылок жила в четырёх копиях.

Запуск: /root/bot/venv/bin/python3 tests/test_txid.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import txid as T      # noqa: E402
from core import assets as A    # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def starts(url, prefix):
    """Проверка префикса, устойчивая к None. Голое url.startswith роняло весь
    набор на первой же забытой монете — а падение до конца прогона скрывает
    остальные проверки, включая ту, что объясняет причину."""
    return isinstance(url, str) and url.startswith(prefix)


HEX = "a" * 64
XRPL_HASH = "5F9B1A2C3D4E5F60718293A4B5C6D7E8F90A1B2C3D4E5F60718293A4B5C6D7E8"

# ── is_txid: настоящий хеш и всё остальное ──────────────────────────────────
check("64 hex — txid", T.is_txid(HEX))
check("0x + 64 hex — txid (EVM)", T.is_txid("0x" + HEX))
check("XRPL-хеш в верхнем регистре — txid", T.is_txid(XRPL_HASH))
check("ссылка на оплату — НЕ txid", T.is_txid("https://pay.platega.io?id=42") is False)
check("пометка 'manual' — НЕ txid", T.is_txid("manual") is False)
check("пустая строка — НЕ txid", T.is_txid("") is False)
check("None — НЕ txid", T.is_txid(None) is False)
check("короткий хеш — НЕ txid", T.is_txid("a" * 63) is False)
check("не строка — НЕ txid без исключения", T.is_txid(12345) is False)

# ── Форма хеша — свойство сети ──────────────────────────────────────────────
# У TON один и тот же хеш ходит в hex64 и в base64 (44 символа): так его отдаёт
# toncenter и так его показывает кошелёк. TON выдаётся ВРУЧНУЮ — владелец
# копирует хеш из кошелька, и hex-only проверка отвергла бы настоящую выплату,
# оставив клиента без ссылки-доказательства.
import base64 as _b64  # noqa: E402

TON_RAW = bytes(range(32))
TON_B64 = _b64.b64encode(TON_RAW).decode()          # 44 символа, с '='
TON_B64URL = _b64.urlsafe_b64encode(TON_RAW).decode().rstrip("=")
check("base64-хеш TON — txid", T.is_txid(TON_B64, "TON"))
check("base64url без выравнивания — тоже txid", T.is_txid(TON_B64URL, "TON"))
check("hex-хеш TON — по-прежнему txid", T.is_txid(HEX, "TON"))
check("base64-хеш приводится к hex", T.normalize_txid(TON_B64, "TON") == TON_RAW.hex())
check("обе формы дают ОДИН результат",
      T.normalize_txid(TON_B64, "TON") == T.normalize_txid(TON_B64URL, "TON"))
check("ссылка TON строится от hex-формы",
      T.explorer_url("TON", TON_B64) == f"https://tonviewer.com/transaction/{TON_RAW.hex()}")
# Послабление не должно расползтись: у BTC 44-символьная строка — не хеш, а
# что угодно, и признать её доказательством отправки нельзя.
check("base64 у BTC — НЕ txid", T.is_txid(TON_B64, "BTC") is False)
check("base64 без валюты — НЕ txid", T.is_txid(TON_B64) is False)
check("ссылка BTC по base64 не строится", T.explorer_url("BTC", TON_B64) is None)
check("base64 неверной длины — НЕ txid",
      T.is_txid(_b64.b64encode(b"x" * 20).decode(), "TON") is False)
check("мусор, похожий на base64 — НЕ txid", T.is_txid("не хеш совсем", "TON") is False)

# Сверка и показ клиенту обязаны сходиться в одном приведении: если у сверки
# своя копия правила, она признает выплату, ссылку на которую бот не покажет.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from core import payout_discovery as _pd  # noqa: E402
check("сверка приводит хеш тем же правилом, что и показ",
      _pd._ton_hash_hex(TON_B64) == T.normalize_txid(TON_B64, "TON") != "")

# ── explorer_url: валюта И сеть ─────────────────────────────────────────────
check("BTC → mempool.space", T.explorer_url("BTC", HEX) == f"https://mempool.space/tx/{HEX}")
check("LTC → blockchair", starts(T.explorer_url("LTC", HEX), "https://blockchair.com/litecoin/"))
check("USDT без сети → tronscan (каноническая сеть)",
      starts(T.explorer_url("USDT", HEX), "https://tronscan.org/"))
check("USDT/TRC20 → tronscan", starts(T.explorer_url("USDT", HEX, "TRC20"), "https://tronscan.org/"))
check("USDT/ERC20 → etherscan, а НЕ tronscan",
      starts(T.explorer_url("USDT", HEX, "ERC20"), "https://etherscan.io/"))
check("USDT/ERC-20 с дефисом → etherscan",
      starts(T.explorer_url("USDT", HEX, "ERC-20"), "https://etherscan.io/"))
check("ETH → etherscan", starts(T.explorer_url("ETH", "0x" + HEX), "https://etherscan.io/"))
check("XRP → обозреватель XRPL", T.explorer_url("XRP", XRPL_HASH, "XRPL") == f"https://xrpscan.com/tx/{XRPL_HASH}")
check("XRP без сети тоже ведёт в XRPL", starts(T.explorer_url("XRP", XRPL_HASH), "https://xrpscan.com/"))
check("неизвестная валюта → None, а не склейка", T.explorer_url("DOGE", HEX) is None)
check("не-txid → None даже у известной валюты", T.explorer_url("BTC", "manual") is None)
check("ссылка вместо хеша → None", T.explorer_url("BTC", "https://pay.example/x") is None)

# ── карта наружу не отдаётся ────────────────────────────────────────────────
# Ссылку считает сервер и отдаёт готовой (tx_url). Карта «валюта → префикс» без
# сети — та же мина, что и раньше: USDT-ERC20 по ней уедет в tronscan.
check("модуль не отдаёт карту наружу", not hasattr(T, "explorer_map"))
check("список известных валют доступен для проверок", "XRP" in T.known_currencies())

# ── Главное: ни одна валюта реестра не осталась без обозревателя ────────────
# Реестр валют и карта ссылок — разные файлы. Пока их связывает только этот
# тест, монету можно завести, довести до заявки и выплаты, а на последнем шаге
# показать клиенту пустоту вместо доказательства.
for cur in sorted(A.CURRENCY_NETWORKS):
    for net in A.CURRENCY_NETWORKS[cur]:
        url = T.explorer_url(cur, HEX, net)
        check(f"{cur}/{net}: есть обозреватель", bool(url))

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
