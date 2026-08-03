#!/usr/bin/env python3
"""Тесты подключения кошелька клиента (core.tonconnect + wallet.ton_wallet).

Проверяется главное свойство: положительный вердикт достижим ровно одним путём —
подпись сошлась с ключом, взятым ИЗ БЛОКЧЕЙНА. Отдельно проверяется атака,
которую эта интеграция допускает чаще всего: подписать своим ключом и приложить
свой же ключ в том же сообщении.

Сеть не дёргаем: цепной источник ключа — подставная функция, toncenter —
подменённый _post_json.

Запуск: /root/bot/venv/bin/python3 tests/test_tonconnect.py
"""
import base64
import hashlib
import os
import sys
import time

os.environ.setdefault("PUBLIC_RELAY", "https://obsidian-exchange.org")
os.environ["RELAY_SECRET"] = "test-secret-for-tonconnect"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from core import tonconnect as TC          # noqa: E402
from core.address import parse_ton_address, ton_friendly_address  # noqa: E402
from wallet import ton_wallet as TW        # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# Настоящий адрес основной сети (контрольная сумма сходится).
FRIENDLY = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI"
WC, HASH = parse_ton_address(FRIENDLY)
RAW = f"{WC}:{HASH.hex()}"
DOMAIN = "obsidian-exchange.org"
UID = 777000123


# ── дружественная форма адреса ────────────────────────────────────────────────
check("сырая форма → дружественная (та же, что показывает кошелёк)",
      ton_friendly_address(RAW) == FRIENDLY)
check("дружественная форма не меняется при повторном приведении",
      ton_friendly_address(FRIENDLY) == FRIENDLY)
check("bounceable-форма начинается с EQ и разбирается в тот же счёт",
      ton_friendly_address(RAW, bounceable=True).startswith("EQ")
      and parse_ton_address(ton_friendly_address(RAW, bounceable=True))[1] == HASH)
check("мусор → пустая строка, а не выдуманный адрес", ton_friendly_address("не адрес") == "")


# ── раскладка подписываемых байтов ────────────────────────────────────────────
# Эталон собран здесь независимо, по буквам спецификации, а не вызовом того же
# кода: ошибка в порядке байтов не падает, она просто даёт другую подпись.
ts = 1783900000
payload = "деньги-любят-счёт"
expected = (b"ton-proof-item-v2/"
            + WC.to_bytes(4, "big", signed=True)
            + HASH
            + len(DOMAIN.encode()).to_bytes(4, "little")
            + DOMAIN.encode()
            + ts.to_bytes(8, "little")
            + payload.encode())
msg = TC.proof_message(RAW, DOMAIN, ts, payload)
check("сообщение собрано ровно по спецификации", msg == expected)
check("дружественная и сырая форма дают одинаковые байты",
      TC.proof_message(FRIENDLY, DOMAIN, ts, payload) == expected)
check("порядок байтов workchain — big-endian (0 и -1 различимы)",
      TC.proof_message("-1:" + HASH.hex(), DOMAIN, ts, payload)[18:22] == b"\xff\xff\xff\xff")
check("нечитаемый адрес → None, а не сообщение из мусора",
      TC.proof_message("0:xx", DOMAIN, ts, payload) is None)

d = TC.proof_digest(expected)
check("digest = sha256(0xffff ++ ton-connect ++ sha256(message))",
      d == hashlib.sha256(b"\xff\xff" + b"ton-connect" + hashlib.sha256(expected).digest()).digest())


# ── проверочный код ───────────────────────────────────────────────────────────
p = TC.make_payload(UID)
check("код выдан и подписан", bool(p) and len(p.split(".")) == 4)
check("свой свежий код принят", TC.check_payload(p, UID) is None)
check("код другого клиента отвергнут", TC.check_payload(p, UID + 1) == "payload_alien")
check("подделанный код отвергнут",
      TC.check_payload(p[:-4] + "0000", UID) == "bad_payload")
check("чужой формат отвергнут", TC.check_payload("что-то.левое", UID) == "bad_payload")
check("протухший код отвергнут",
      TC.check_payload(TC.make_payload(UID, now=time.time() - TC.PAYLOAD_TTL_SEC - 5), UID)
      == "payload_expired")
check("код из будущего отвергнут",
      TC.check_payload(TC.make_payload(UID, now=time.time() + 600), UID) == "bad_payload")

_saved_secret = os.environ.pop("RELAY_SECRET")
check("без RELAY_SECRET код не выдаётся вовсе", TC.make_payload(UID) is None)
check("без RELAY_SECRET любой код отвергнут", TC.check_payload(p, UID) == "not_configured")
os.environ["RELAY_SECRET"] = _saved_secret


# ── подпись владения ──────────────────────────────────────────────────────────
key = Ed25519PrivateKey.generate()
PUB = key.public_key().public_bytes_raw()
alien = Ed25519PrivateKey.generate()
ALIEN_PUB = alien.public_key().public_bytes_raw()


def make_proof(*, signer=key, address=RAW, domain=DOMAIN, timestamp=None,
               payload=None, subject=UID):
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    payload = TC.make_payload(subject) if payload is None else payload
    m = TC.proof_message(address, domain, timestamp, payload)
    sig = signer.sign(TC.proof_digest(m))
    return {"timestamp": timestamp,
            "domain": {"lengthBytes": len(domain.encode()), "value": domain},
            "payload": payload,
            "signature": base64.b64encode(sig).decode()}


def verify(account=None, proof=None, chain_key=PUB, subject=UID):
    account = {"address": RAW, "chain": TC.CHAIN_MAINNET} if account is None else account
    proof = make_proof() if proof is None else proof
    return TC.verify_proof(account, proof, subject=subject,
                           public_key_of=lambda _a: chain_key)


v = verify()
check("честная подпись подтверждает владение", v["verified"] and v["reason"] == "ok")
check("в ответе дружественный адрес счёта, а не сырой", v["address"] == FRIENDLY)

# Главная ловушка: клиент подписывает СВОИМ ключом и прикладывает его же.
v = TC.verify_proof({"address": RAW, "chain": TC.CHAIN_MAINNET,
                     "publicKey": ALIEN_PUB.hex()},
                    make_proof(signer=alien), subject=UID,
                    public_key_of=lambda _a: PUB)
check("подпись чужим ключом со СВОИМ ключом в ответе отвергнута",
      not v["verified"] and v["reason"] == "pubkey_mismatch")

# И тот же случай без подсказки publicKey — ключ всё равно цепной.
v = TC.verify_proof({"address": RAW}, make_proof(signer=alien), subject=UID,
                    public_key_of=lambda _a: PUB)
check("подпись чужим ключом без publicKey отвергнута",
      not v["verified"] and v["reason"] == "bad_signature")

check("совпадающий publicKey не мешает", verify(
    account={"address": RAW, "publicKey": PUB.hex()})["verified"])

v = verify(chain_key=None)
check("нет ключа в сети → нет подтверждения (не «сойдёт»)",
      not v["verified"] and v["reason"] == "pubkey_unavailable")
check("причина объясняет клиенту, что делать",
      "вручную" in v["message"])

v = verify(proof=make_proof(domain="phishing-obsidian.org"))
check("подпись для чужого домена отвергнута",
      not v["verified"] and v["reason"] == "foreign_domain")

bad = make_proof()
bad["domain"] = {"value": DOMAIN, "lengthBytes": len(DOMAIN) + 3}
check("объявленная длина домена не сходится → отказ",
      TC.verify_proof({"address": RAW}, bad, subject=UID,
                      public_key_of=lambda _a: PUB)["reason"] == "bad_domain_length")

check("подпись старше окна отвергнута",
      verify(proof=make_proof(timestamp=time.time() - TC.PROOF_TTL_SEC - 30))["reason"]
      == "proof_expired")
check("подпись из будущего отвергнута",
      verify(proof=make_proof(timestamp=time.time() + 3600))["reason"] == "proof_from_future")

check("код, выданный другому клиенту, не проходит",
      verify(proof=make_proof(subject=UID + 1))["reason"] == "payload_alien")

broken = make_proof()
broken["signature"] = base64.b64encode(b"\x00" * 64).decode()
check("испорченная подпись отвергнута",
      not verify(proof=broken)["verified"])
short = make_proof()
short["signature"] = base64.b64encode(b"\x01" * 10).decode()
check("подпись не той длины отвергнута", verify(proof=short)["reason"] == "bad_signature")
notb64 = make_proof()
notb64["signature"] = "не base64!!"
check("не-base64 в подписи не роняет сервер", verify(proof=notb64)["reason"] == "bad_signature")

check("кошелёк тестовой сети отвергнут",
      verify(account={"address": RAW, "chain": "-3"})["reason"] == "foreign_chain")
check("нечитаемый адрес отвергнут",
      verify(account={"address": "0:zz"})["reason"] == "bad_address")
check("пустой запрос не роняет сервер",
      TC.verify_proof(None, None, subject=UID,
                      public_key_of=lambda _a: PUB)["reason"] == "bad_request")
# Кривой ответ кошелька (а то и просто чужой POST) обязан давать отказ, а не
# исключение: 500 на публичном эндпоинте — это «у нас сломалось» вместо
# «подпись не принята», и по нему же удобно щупать сервер.
for _name, _mangle in (
        ("domain строкой вместо объекта", lambda p: p.update({"domain": "obsidian"})),
        ("domain списком", lambda p: p.update({"domain": ["obsidian"]})),
        ("lengthBytes не число", lambda p: p["domain"].update({"lengthBytes": "много"})),
        ("timestamp строкой", lambda p: p.update({"timestamp": "вчера"})),
        ("timestamp списком", lambda p: p.update({"timestamp": [1]})),
        ("payload объектом", lambda p: p.update({"payload": {"a": 1}})),
        ("signature объектом", lambda p: p.update({"signature": {"a": 1}})),
        ("нет ни одного поля", lambda p: p.clear()),
):
    _p = make_proof()
    _mangle(_p)
    try:
        _v = verify(proof=_p)
        _ok = _v["verified"] is False and bool(_v["message"])
    except Exception as e:
        _ok = False
        print("   исключение:", type(e).__name__, e)
    check(f"кривой ответ кошелька → отказ, а не сбой: {_name}", _ok)

check("нечитаемый publicKey в ответе → отказ, а не сбой",
      verify(account={"address": RAW, "publicKey": "не-hex"})["verified"] is False)

check("подпись под ДРУГИМ адресом не подходит этому счёту",
      not TC.verify_proof(
          {"address": RAW},
          make_proof(address="0:" + "11" * 32),
          subject=UID, public_key_of=lambda _a: PUB)["verified"])

# Каждый отказ обязан быть объяснён словами: молчаливое «false» на поверхности
# превращается в «ничего не произошло, кнопка не работает».
check("у каждой причины есть человеческий текст",
      all(TC.reason_text(c) and TC.reason_text(c) != "Не удалось подтвердить кошелёк"
          for c in TC.REASON_TEXT))


# ── манифест ──────────────────────────────────────────────────────────────────
m = TC.manifest()
check("манифест годен для кошелька", TC.manifest_problems(m) == [])
check("обязательные поля на месте", all(m.get(k) for k in ("url", "name", "iconUrl")))
check("url без завершающего слэша (иначе кошелёк видит другое приложение)",
      not m["url"].endswith("/"))
check("иконка лежит на нашем домене и это PNG",
      m["iconUrl"].startswith(m["url"]) and m["iconUrl"].endswith(".png"))
_icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "relay-fastapi", "static", "img", "tonconnect-icon.png")
check("файл иконки существует (кошелёк тянет его сам)", os.path.isfile(_icon))
check("слэш в конце url замечен",
      "url без завершающего слэша" in TC.manifest_problems(
          {**m, "url": m["url"] + "/"}))
check("http вместо https замечен",
      any("https" in p for p in TC.manifest_problems(
          {**m, "url": "http://obsidian-exchange.org"})))
check("иконка не-PNG замечена",
      any("PNG" in p for p in TC.manifest_problems({**m, "iconUrl": m["url"] + "/i.svg"})))
check("пустое имя замечено", "name пуст" in TC.manifest_problems({**m, "name": " "}))

check("наш домен в списке разрешённых", DOMAIN in TC.allowed_domains())
os.environ["TONCONNECT_DOMAINS"] = "*, second.example"
check("звёздочка не превращается в «любой домен»", "*" not in TC.allowed_domains())
check("дополнительный домен из настройки учтён", "second.example" in TC.allowed_domains())
os.environ.pop("TONCONNECT_DOMAINS")


# ── ключ из блокчейна (toncenter) ─────────────────────────────────────────────
_saved_post = TW._post_json
calls = []


def fake_post(url, body, timeout=15):
    calls.append((url, body))
    return fake_post.reply


try:
    TW._post_json = fake_post
    fake_post.reply = {"ok": True, "result": {"exit_code": 0,
                                              "stack": [["num", "0x" + PUB.hex()]]}}
    got = TW.public_key(RAW)
    check("ключ счёта прочитан из ответа сети", got == PUB)
    check("спрошен именно get_public_key у нужного адреса",
          calls and calls[-1][1]["method"] == "get_public_key"
          and calls[-1][1]["address"] == RAW)
    check("ключ берётся у того же узла, что и баланс",
          calls[-1][0].startswith(TW.api_url("").rstrip("/")))

    fake_post.reply = {"ok": True, "result": {"exit_code": 11, "stack": []}}
    st = TW.public_key_state(RAW)
    check("не активированный кошелёк — отдельный статус, а не сбой",
          st["key"] is None and st["status"] == "NOT_DEPLOYED")

    fake_post.reply = {"ok": False, "error": "Failed to parse ton_addr"}
    st = TW.public_key_state(RAW)
    check("причину отказа toncenter видно словами",
          st["key"] is None and "parse" in st["reason"])

    fake_post.reply = {"ok": True, "result": {"exit_code": 0, "stack": [["num", "0x0"]]}}
    check("нулевой ключ не считается ключом", TW.public_key(RAW) is None)

    fake_post.reply = {"ok": True, "result": {"exit_code": 0,
                                              "stack": [["num", "0x" + "ff" * 40]]}}
    check("ключ длиннее 256 бит отвергнут", TW.public_key(RAW) is None)

    fake_post.reply = {"ok": True, "result": {"exit_code": 0, "stack": []}}
    check("пустой стек не роняет вызов", TW.public_key(RAW) is None)

    def boom(*_a, **_k):
        raise OSError("сеть недоступна")
    TW._post_json = boom
    st = TW.public_key_state(RAW)
    check("недоступная сеть → «не знаем», а не ключ",
          st["key"] is None and st["status"] == "ERROR")
finally:
    TW._post_json = _saved_post

check("отправлять TON по-прежнему нельзя",
      isinstance(getattr(TW, "send", None), type(lambda: None)))

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
