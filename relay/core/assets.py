"""Единый источник правды по валютам, сетям и валидации адресов (мультичейн).

Зачем. Логика «какие валюты обмениваем», «в каких сетях» и «валиден ли адрес»
исторически дублировалась в трёх местах (bot/main_bot.py, relay/utils/exchange_calc.py,
relay-fastapi/main.py) и расходилась. Для Фазы C (ETH + выбор сети USDT) правила
должны быть в ОДНОМ месте, иначе легко отправить не в ту сеть или принять адрес
чужой сети. Модуль чистый: без БД, без сети, без зависимостей — импортируется всеми.

Фейл-клоуз: неизвестная валюта/сеть → отказ (None/False), а не «как-нибудь».
"""
from __future__ import annotations
import os
import re

# ── Канонические коды сетей ──
NET_MAINNET = "MAINNET"   # BTC/LTC
NET_TRC20 = "TRC20"       # USDT на TRON
NET_ERC20 = "ERC20"       # ETH mainnet и USDT на Ethereum
NET_XRPL = "XRPL"         # XRP Ledger — своя сеть, не MAINNET (тот код занят BTC/LTC)
NET_TON = "TON"           # The Open Network — своя цепь, не EVM и не TRON
NET_MONERO = "MONERO"     # Monero — своя цепь; код MAINNET занят BTC/LTC

# Валюта → допустимые сети (первая = сеть по умолчанию)
CURRENCY_NETWORKS = {
    "BTC": [NET_MAINNET],
    "LTC": [NET_MAINNET],
    "USDT": [NET_TRC20, NET_ERC20],
    "ETH": [NET_ERC20],   # для ETH «ERC20» = Ethereum mainnet (единый EVM-контур)
    "XRP": [NET_XRPL],
    "TON": [NET_TON],
    "XMR": [NET_MONERO],
}

# Валюты, где адрес может сопровождаться тегом/мемо. Пропуск тега при переводе
# на биржу = деньги зачислены «в никуда» и не возвращаются, поэтому это свойство
# валюты, а не деталь интерфейса.
# У TON это не число, а текстовый комментарий — но роль та же: на бирже он и
# есть «кому именно», и перевод без него зачисляется в общий котёл.
TAGGED_CURRENCIES = {"XRP": "destination tag", "TON": "memo (комментарий)"}

# Какого ВИДА значение ждать в поле тега. У XRP это число, у TON — текст, и
# интерфейс обязан спрашивать по-разному: клавиатура, подсказка, текст отказа.
# Пока вид считался числом «по умолчанию», поле memo у TON отвергало правильное
# значение сообщением «должен быть целым числом» — заявку было не создать.
TAG_KINDS = {"XRP": "number", "TON": "text"}

# Чем клиент отделяет тег от адреса, когда пишет их одной строкой. Общего
# разделителя тут быть не может: сырой адрес TON — это `workchain:hex64`, и
# двоеточие в нём СВОЁ. Разрезав по нему, мы получили бы «адрес 0» и «тег
# из hex» — то есть отказ на совершенно правильном адресе.
TAG_SEPARATORS = {"XRP": ":", "TON": "#"}

# Монеты, чей кошелёк умеет подключиться к нам сам и доказать владение адресом
# подписью (TON Connect). Признак живёт здесь, а не в JS: список монет во фронте
# отстал бы от реестра на следующей же сети, а цена расхождения — кнопка
# «Подключить кошелёк» у монеты, для которой она ничего не подключает.
# Ручной ввод адреса остаётся у ВСЕХ монет, включая эти.
WALLET_CONNECT_CURRENCIES = {"TON"}

# Монеты, где владение адресом доказывается ПОДПИСЬЮ СООБЩЕНИЯ: клиент
# подписывает наш текст в своём кошельке и присылает подпись (core.sig_proof).
# Механизм другой, чем у TON Connect (там кошелёк отвечает нам сам), а роль та
# же — единственный способ добавить адрес по просьбе клиента, не превращая
# сервис в пробник чужих кошельков. Список здесь по той же причине, что и выше:
# поверхность, знающая его из своего кода, отстанет от сервера.
SIGNED_MESSAGE_CURRENCIES = {"BTC", "LTC", "ETH", "USDT"}

# Синонимы входных значений сети → канон (или None = недопустимо)
_NET_ALIASES = {
    "TRON": NET_TRC20, "TRC-20": NET_TRC20, "TRC20": NET_TRC20,
    "ERC-20": NET_ERC20, "ERC20": NET_ERC20,
    "ETH": NET_ERC20, "ETHEREUM": NET_ERC20, "ETHEREUM-MAINNET": NET_ERC20, "EVM": NET_ERC20,
    "MAIN": NET_MAINNET, "MAINNET": NET_MAINNET,
    "XRPL": NET_XRPL, "XRP": NET_XRPL, "RIPPLE": NET_XRPL,
    "TON": NET_TON, "TONCOIN": NET_TON, "THE OPEN NETWORK": NET_TON,
    "XMR": NET_MONERO, "MONERO": NET_MONERO,
    "BEP20": None, "BSC": None, "POLYGON": None, "MATIC": None,
}

# Регулярки — только ДЕШЁВЫЙ ПРЕДФИЛЬТР «похоже на адрес этой валюты».
# Авторитетный вердикт даёт контрольная сумма (core.address), поэтому фильтр
# намеренно широкий: узкие рамки отсекали валидные адреса ДО проверки суммы —
# bech32 в верхнем регистре (BC1…, разрешён BIP-173) и witness-программы
# нестандартной длины (2..40 байт по BIP-350).
_ADDR_RE = {
    "BTC": [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^(?:bc1|BC1)[a-zA-Z0-9]{6,87}$'],
    "LTC": [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^(?:ltc1|LTC1)[a-zA-Z0-9]{6,87}$'],
    NET_TRC20: [r'^T[A-Za-z1-9]{33}$'],
    NET_ERC20: [r'^0x[a-fA-F0-9]{40}$'],
    # XRPL: classic (r…) и X-адрес (X…, несёт destination tag внутри себя).
    # Алфавит у XRPL свой — ни '0', ни 'l', ни 'I', ни 'O'.
    NET_XRPL: [r'^r[rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz]{24,34}$',
               r'^X[rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz]{40,50}$'],
    # TON: «дружественная» форма (48 символов base64url) и «сырая» (workchain:hex64).
    NET_TON: [r'^[A-Za-z0-9+/_-]{48}$', r'^-?\d+:[0-9a-fA-F]{64}$'],
    # Monero: обычный адрес и субадрес — 95 символов («4…» / «8…»),
    # integrated — 106 («4…», внутри уже лежит payment id). Алфавит base58
    # биткойновый, но разбор блочный — вердикт даёт core.address.
    #
    # Второй символ здесь НЕ ограничен, хотя по нему видно тип адреса. Первые
    # два символа кодируют не один префиксный байт, а весь первый блок из
    # восьми байтов — то есть префикс ВМЕСТЕ с началом ключа траты. У
    # integrated-адресов второй символ пробегает B…M, у субадресов 2…C, и
    # попытка перечислить их «по виду» отвергала верные адреса ДО подсчёта
    # контрольной суммы: клиент с исправным кошельком получал «неверный
    # формат». Нашёл codex. Тип и сумму решает core.address.is_valid_xmr.
    NET_MONERO: [r'^[48][1-9A-HJ-NP-Za-km-z]{94}$',
                 r'^4[1-9A-HJ-NP-Za-km-z]{105}$'],
}


def multichain_ui_enabled() -> bool:
    """Фиче-флаг мультичейн-UI (ETH как монета + выбор сети USDT в интерфейсах).
    По умолчанию ВЫКЛ: бэкенд готов, но поверхности не предлагают ETH/выбор сети,
    пока флаг не включён. Авто-выплата EVM гейтится ОТДЕЛЬНО (EVM_PAYOUTS_ENABLED)."""
    return os.getenv("MULTICHAIN_UI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def normalize_currency(currency) -> str:
    """Фейл-клоуз и на нестроковый вход (int/list/None) — .strip() на них упал бы
    исключением, что для вызывающего кода часто оборачивалось бы в try/except
    и МОЛЧА пропускало бы валидацию. Не-строка → "" → не найдена ни в одной таблице."""
    if not isinstance(currency, str):
        return ""
    return currency.strip().upper()


def is_supported_currency(currency) -> bool:
    return normalize_currency(currency) in CURRENCY_NETWORKS


def networks_for(currency):
    """Список допустимых сетей валюты (канон) или []. Первая — по умолчанию."""
    return list(CURRENCY_NETWORKS.get(normalize_currency(currency), []))


def chain_of(currency, network=None):
    """Цепь, в которой живёт адрес этой (монеты, сети), или None.

    Ключ подключённого кошелька — ЦЕПЬ, а не монета, и это не придирка к
    словам: один и тот же `T…`-адрес держит и USDT, и TRX, а один `0x…` — и
    ETH, и USDT-ERC20. Храни мы связь по монете, доказанный TRC-20-адрес
    затирался бы ERC-20-адресом того же клиента (в таблице связей ключ —
    пара «клиент + цепь»), и баланс показывался бы не тот.

    У BTC/LTC цепь совпадает с кодом монеты — так эти связи и лежат с самого
    начала, поэтому имена здесь именно такие: ничего мигрировать не нужно.
    """
    net = normalize_network(currency, network)
    if not net:
        return None
    if net == NET_MAINNET:
        return normalize_currency(currency)     # BTC / LTC — цепь своя у каждой
    return {NET_TRC20: "TRON", NET_ERC20: "ETH", NET_XRPL: "XRP",
            NET_TON: "TON", NET_MONERO: "XMR"}.get(net)


def pairs_on_chain(chain):
    """Все пары (монета, сеть), которыми мы торгуем в этой цепи.

    Обратная сторона `chain_of`, и намеренно СПИСОК: доказав один `0x…`-адрес,
    клиент доказал его и для ETH, и для USDT-ERC20 — это буквально один счёт.
    Возвращать одну «главную» монету значило бы прятать подтверждённый адрес
    там, где он полностью годен.
    """
    want = str(chain or "").strip().upper()
    if not want:
        return []
    return [(c, n) for c, nets in CURRENCY_NETWORKS.items() for n in nets
            if chain_of(c, n) == want]


def default_network(currency):
    nets = networks_for(currency)
    return nets[0] if nets else None


def normalize_network(currency, network):
    """Каноническая сеть для (currency, network). Пусто → сеть по умолчанию валюты.
    Возвращает канон-код или None, если сеть недопустима для этой валюты (fail-closed).
    Значения нормализуются (strip/upper/синонимы), чтобы ' trc-20 ' не обошло защиту."""
    c = normalize_currency(currency)
    if c not in CURRENCY_NETWORKS:
        return None
    if network is not None and not isinstance(network, str):
        return None  # фейл-клоуз: нестроковый network не приводим молча
    raw = (network or "").strip().upper()
    if not raw:
        return CURRENCY_NETWORKS[c][0]
    canon = _NET_ALIASES.get(raw, raw)
    if canon is None:
        return None
    return canon if canon in CURRENCY_NETWORKS[c] else None


def validate_address(currency, address, network=None) -> bool:
    """True только если адрес соответствует валюте, сети И контрольной сумме.

    Двухступенчато: сначала форма (быстрая регулярка — отсеивает явный мусор),
    затем контрольная сумма (core.address). Одной формы мало: опечатка в одном
    символе сохраняет и длину, и алфавит, но делает адрес несуществующим —
    крипта уходит безвозвратно. На реальных данных проверка нашла заявку с
    испорченным TRON-адресом, которую старая регулярка пропустила.

    network=None → сеть по умолчанию (обратная совместимость: USDT→TRC20).
    Не в ту сеть (напр. 0x-адрес для USDT-TRC20) → False.
    """
    c = normalize_currency(currency)
    if address is not None and not isinstance(address, str):
        return False  # фейл-клоуз: нестроковый адрес не приводим молча
    addr = (address or "").strip()
    if not addr:
        return False
    net = normalize_network(c, network)
    if net is None:
        return False
    if c in ("BTC", "LTC"):
        pats = _ADDR_RE[c]
    elif c == "ETH":
        pats = _ADDR_RE[NET_ERC20]
    elif c == "USDT":
        pats = _ADDR_RE[NET_ERC20] if net == NET_ERC20 else _ADDR_RE[NET_TRC20]
    elif c == "XRP":
        pats = _ADDR_RE[NET_XRPL]
    elif c == "TON":
        pats = _ADDR_RE[NET_TON]
    elif c == "XMR":
        pats = _ADDR_RE[NET_MONERO]
    else:
        return False
    if not any(re.match(p, addr) for p in pats):
        return False
    return _checksum_ok(c, addr, net)


def _checksum_ok(currency, addr, net) -> bool:
    """Контрольная сумма адреса. Сбой импорта/разбора → False (фейл-клоуз):
    лучше попросить клиента ввести адрес заново, чем отправить в пустоту."""
    try:
        from core import address as _addr
    except Exception:
        try:
            import address as _addr  # запуск из каталога core
        except Exception:
            return False
    try:
        if currency == "BTC":
            return _addr.is_valid_btc(addr)
        if currency == "LTC":
            return _addr.is_valid_ltc(addr)
        if currency == "ETH":
            return _addr.is_valid_evm_address(addr)
        if currency == "USDT":
            return (_addr.is_valid_evm_address(addr) if net == NET_ERC20
                    else _addr.is_valid_tron(addr))
        if currency == "XRP":
            return _addr.is_valid_xrp(addr)
        if currency == "TON":
            return _addr.is_valid_ton(addr)
        if currency == "XMR":
            return _addr.is_valid_xmr(addr)
    except Exception:
        return False
    return False


def network_label(currency, network=None) -> str:
    """Человекочитаемая метка сети для UI, напр. 'TRC-20', 'ERC-20', 'Mainnet'."""
    net = normalize_network(currency, network)
    return {NET_MONERO: "Monero",
            NET_TRC20: "TRC-20", NET_ERC20: "ERC-20", NET_MAINNET: "Mainnet",
            NET_XRPL: "XRP Ledger", NET_TON: "TON"}.get(net, "")


def tag_name(currency):
    """Как называется тег у этой валюты ('destination tag') или None."""
    return TAGGED_CURRENCIES.get(normalize_currency(currency))


def tag_kind(currency):
    """'number' | 'text' | None — какого вида значение ждать в поле тега."""
    return TAG_KINDS.get(normalize_currency(currency))


def tag_separator(currency):
    """Чем клиент отделяет тег от адреса в одной строке, или None."""
    return TAG_SEPARATORS.get(normalize_currency(currency))


def supports_wallet_connect(currency) -> bool:
    """Умеет ли кошелёк этой монеты подключиться и подписать владение адресом."""
    return normalize_currency(currency) in WALLET_CONNECT_CURRENCIES


def tag_error_text(currency, code):
    """Текст отказа по тегу — один на бот, сайт и Mini App.

    Три копии этой фразы разошлись бы, и клиент читал бы на одной поверхности
    «нужно число», а на другой «нужен текст» про одну и ту же монету.
    """
    label = (tag_name(currency) or "тег")
    if code == "not_tagged":
        return "Для этой валюты тег не используется."
    if code == "bad_number":
        return (f"{label.capitalize()} — целое число без пробелов и знаков, "
                f"от 0 до 4294967295 (например 12345).")
    if code == "bad_text":
        return (f"{label.capitalize()} — короткий текст без переводов строки, "
                f"не длиннее 127 символов. Скопируйте его из кошелька целиком.")
    return f"{label.capitalize()} не принят."


def address_carries_tag(currency, address) -> bool:
    """True, если тег зашит в САМ адрес (X-адрес XRPL, 'адрес#memo' у TON).

    Тогда спрашивать тег у клиента не надо — и, главное, нельзя позволить
    задать другой: адрес уже несёт свой.

    Проверка идёт через разборщик ПО ВАЛЮТЕ. Жёсткая привязка к XRP здесь
    означала бы, что у любой следующей монеты с тегом клиента переспросят
    тег поверх уже указанного, а расхождение двух значений вскроется только
    на выдаче.
    """
    cur = normalize_currency(currency)
    if cur not in TAGGED_CURRENCIES:
        return False
    try:
        from core import address as _addr
    except Exception:
        try:
            import address as _addr
        except Exception:
            return False
    try:
        clean, tag = _addr.parse_destination((address or "").strip(), cur)
        return clean is not None and tag is not None
    except Exception:
        return False


def canonical_address(currency, address, tag=None, network=None):
    """Адрес в том виде, в котором его следует ХРАНИТЬ в заявке, или None.

    Для валют с тегом склеивает адрес и тег в одну неразделимую строку
    (см. core.address.canonical_xrp_destination — почему не отдельная колонка).
    Для остальных валют — обычная валидация: тег там взяться не должен.

    `network` обязателен там, где у валюты сетей больше одной: USDT-ERC20
    задаётся 0x-адресом, который в сети по умолчанию (TRC20) невалиден. Без
    этого параметра проверка сравнивала бы адрес не с той сетью и отвергала
    исправную заявку — сеть должна быть ТА ЖЕ, что уйдёт в заявку.
    """
    c = normalize_currency(currency)
    if c not in CURRENCY_NETWORKS:
        return None
    if normalize_network(c, network) is None:
        return None              # сеть не из списка валюты — отказ, а не «по умолчанию»
    if c not in TAGGED_CURRENCIES:
        if tag is not None:
            return None          # тег у валюты без тегов — отказ, а не «проигнорируем»
        addr = address.strip() if isinstance(address, str) else ""
        return addr if validate_address(c, addr, network) else None
    try:
        from core import address as _addr
    except Exception:
        try:
            import address as _addr
        except Exception:
            return None
    try:
        # Диспетчер по валюте, а НЕ разборщик конкретной монеты: список
        # TAGGED_CURRENCIES общий, и частный вызов отсюда означал бы, что
        # каждая новая монета с тегом молча разбирается правилами чужой.
        return _addr.canonical_destination(address, tag, c)
    except Exception:
        return None


def validate_destination(currency, value, network=None) -> bool:
    """Годится ли СТРОКА НАЗНАЧЕНИЯ — то, что ввёл клиент или что лежит в заявке.

    Отличается от validate_address тем, что понимает каноническую склейку с
    тегом (`UQ…#memo`, `r…:12345`). Именно в таком виде адрес хранится у валют
    с тегом — и проверка голым валидатором отвечала на него «не прошёл
    контрольную сумму»:
      • клиент, вставивший адрес с memo одной строкой (форма это прямо
        разрешает и прячет отдельное поле), получал отказ на ПРАВИЛЬНОМ адресе;
      • страж перед авто-выплатой видел «адрес в БД невалиден» на заявке,
        которую сам же и записал, и уводил её человеку.
    Строгости это не убавляет: склейка принимается только разобранной — адрес
    обязан пройти контрольную сумму, тег — проверку вида.
    """
    c = normalize_currency(currency)
    v = value.strip() if isinstance(value, str) else ""
    if validate_address(c, v, network):
        return True
    if c not in TAGGED_CURRENCIES or not address_carries_tag(c, v):
        return False
    try:
        from core import address as _addr
    except Exception:
        try:
            import address as _addr
        except Exception:
            return False
    try:
        clean, tag = _addr.parse_destination(v, c)
    except Exception:
        return False
    return (clean is not None and validate_address(c, clean, network)
            and validate_tag(c, tag))


def validate_tag(currency, tag) -> bool:
    """Тег корректен для этой валюты. Валюта без тегов + непустой тег → False
    (фейл-клоуз: тег, который никуда не поедет, лучше отвергнуть на вводе).
    Тег 0 — ВАЛИДЕН и отличается от «тега нет»: часть бирж использует именно 0.
    """
    c = normalize_currency(currency)
    if c not in TAGGED_CURRENCIES:
        return tag is None
    try:
        from core import address as _addr
    except Exception:
        try:
            import address as _addr
        except Exception:
            return False
    try:
        return _addr.is_valid_tag(tag, c)
    except Exception:
        return False
