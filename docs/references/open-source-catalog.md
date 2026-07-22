# Каталог открытых наработок (референсы)

Курируемый список **открытых проектов** для изучения и адаптации при
разработке собственных продуктов. Цель — не копировать продукт целиком, а
брать паттерны, интерфейсы и отдельные куски-референсы, экономя время.

## Гигиена использования

- **Лицензия решает.** MIT / Apache-2.0 / BSD — можно брать код с сохранением
  копирайт-нотиса. **AGPL / GPL** — «вирусная» лицензия: производный продукт
  придётся открывать целиком, для закрытого прода не подходит (только идеи).
  Перед переносом кода — открыть `LICENSE` в репозитории и свериться.
- **Референс ≠ копипаст.** Берём архитектуру, алгоритм, контракт интерфейса —
  переписываем под себя. Копирование файлов целиком тянет за собой лицензию.
- Ссылки собраны через веб-поиск; статус/лицензию каждого репозитория
  перепроверять на момент использования (проекты меняются).

> **Про `chat.deepseek.com/share`:** проверено — поиск отдаёт только голые
> ссылки без содержимого, а сами страницы возвращают HTTP 403 (клиентский
> рендер + гейт). Как источник кода бесполезны: заглянуть внутрь нельзя.
> Реальная ценность — в репозиториях ниже.

---

## 1. Процессинг платежей / роутинг / антифрод

Ближе всего к нашему `smart_router` + `payment_service`.

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [juspay/hyperswitch](https://github.com/juspay/hyperswitch) | Rust / Apache-2.0 | **Эталон.** Smart routing, retry-логика, decision-engine выбора шлюза на транзакцию, 100+ коннекторов. Прямой аналог нашего роутинга, только зрелее. |
| [Janeferdinant/Payment](https://github.com/Janeferdinant/Payment) | Rust | Минималистичный payments switch — читается быстрее для идей. |
| [ianhalpern/python-payment-processor](https://github.com/ianhalpern/python-payment-processor) | Python / MIT | Единый контракт провайдера поверх разных API (у нас `providers/*`). |

## 2. Крипто-приём / платёжные процессоры

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [btcpayserver/btcpayserver](https://github.com/btcpayserver/btcpayserver) | C# / MIT | Самохост BTC + Lightning, вебхуки, подтверждение в блокчейне. |
| [Bitcart](https://bitcart.ai/) | Python | BTC/LTC/ETH/TRX/**USDT** non-custodial, Lightning одной командой. |
| [vsys-host/shkeeper.io](https://github.com/vsys-host/shkeeper.io) | Python | Крипто-гейт: BTC(+LN)/ETH/LTC/TRX/**USDT/USDC**, интеграция в свой код. |

## 3. Крипто-кошельки / ключи (ядра)

Релевантно нашему `wallet/` и горячему кошельку.

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [hdwallet-io/python-hdwallet](https://github.com/hdwallet-io/python-hdwallet) | Python | HD-кошелёк (BIP32/39/44) на 200+ монет. |
| [farukterzioglu/HDWallet](https://github.com/farukterzioglu/HDWallet) | C#/.NET | Secp256k1 + Ed25519, BTC/ETH/Tron/… — generic реализация кривых. |
| [mrtnetwork/onchain_wallet](https://github.com/mrtnetwork/onchain_wallet) | Dart | Полный некастодиальный кошелёк BTC/XRP/ETH/Tron/Monero/LTC. |

## 4. Биржевые ядра / matching engine

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [joaquinbejar/OrderBook-rs](https://github.com/joaquinbejar/OrderBook-rs) | Rust | Thread-safe limit order book, lock-free структуры. |
| [philipgreat/lighting-match-engine-core](https://github.com/philipgreat/lighting-match-engine-core) | Rust | 46 нс/ордер, минимум зависимостей — референс по производительности. |
| [amankrx/matching-engine-rs](https://github.com/amankrx/matching-engine-rs) | Rust | ITCH order book, 11.3M msg/s — парсинг+матчинг. |
| [jogeshwar01/exchange](https://github.com/jogeshwar01/exchange) | Rust | CEX целиком: in-memory book, WebSocket, Redis+Postgres. |

## 5. Парсеры / сбор данных (адаптивность к разметке)

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [servo/html5ever](https://github.com/servo/html5ever) | Rust | Браузерного класса HTML5-парсер, C-уровень скорости — ядро парсера. |
| [rust-scraper/scraper](https://github.com/rust-scraper/scraper) | Rust | CSS-селекторы поверх html5ever — удобный слой. |
| [chrisabruce/scrapling-rs](https://github.com/chrisabruce/scrapling-rs) | Rust | **«Адаптивно»:** находит элементы после редизайна сайта, имитирует браузер. |
| [Scrapy](https://github.com/topics/web-scraping) | Python | Зрелый фреймворк: очереди, middlewares, throttling. |

## 6. Анти-бот / stealth / прокси (dual-use — только легальный сбор)

> ⚠️ Инструменты обхода анти-бота законны для сбора **своих**/публичных данных
> и тестирования собственной защиты. Не для обхода чужих запретов.

| Проект | Что брать |
|---|---|
| [jo-inc/camofox-browser](https://github.com/jo-inc/camofox-browser) | Stealth-браузер, drop-in замена Puppeteer/Playwright. |
| [GitHub topic: anti-bot](https://github.com/topics/anti-bot?o=desc&s=stars) | Подборка: undetected-chromedriver, puppeteer-stealth и пр. |
| [GitHub topic: stealth-browser](https://github.com/topics/stealth-browser) | Fingerprint-спуфинг, ротация прокси, GeoIP. |

## 7. LLM-ядро / инференс / агенты

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [vllm-project/vllm](https://github.com/vllm-project/vllm) | Python/CUDA / Apache-2.0 | Эталон throughput: paged attention, continuous batching. |
| [EricLBuehler/mistral.rs](https://github.com/EricLBuehler/mistral.rs) | Rust | Быстрый инференс + квантизация, Python и Rust SDK. |
| [openinfer-project/openinfer](https://github.com/openinfer-project/openinfer) | Rust+CUDA / Apache-2.0 | Чистый Rust без PyTorch, OpenAI-совместимый. |
| [SGLang](https://en.wikipedia.org/wiki/SGLang) | Py/Rust/CUDA / Apache-2.0 | Структурированная генерация + рантайм. |
| [qdrant](https://github.com/topics/rag) | Rust | Векторный поиск для памяти агента / RAG. |
| [awesome-ai-agents-2026](https://github.com/ARUNAGIRINATHAN-K/awesome-ai-agents-2026) | — | 300+ агентов/фреймворков, сравнения и бенчмарки. |

## 8. Системы защиты / WAF / антифрод-движок

| Проект | Язык / Лиц. | Что брать |
|---|---|---|
| [jube-home/aml-fraud-transaction-monitoring](https://github.com/jube-home/aml-fraud-transaction-monitoring) | — | Rules-engine: пороги, **velocity-проверки**, агрегации, санкции. Под наши правила «частота/аномальная сумма». |
| [openprx/prx-waf](https://github.com/openprx/prx-waf) | Rust | WAF на Pingora: sliding-window rate-limit, bot detection, OWASP CRS, Rhai-скрипты правил. |
| [GitHub topic: signature-verification](https://github.com/topics/signature-verification) | — | Проверка подписей вебхуков (наш HMAC/SHA-256 у Brabus/XPay). |
| [GitHub topic: rate-limiting (rust)](https://github.com/topics/rate-limiting?l=rust&o=desc&s=updated) | Rust | Реализации rate-limit — под наш `/api/*`. |

---

_Собрано автономным агентом. Раунды поиска продолжаются — файл дополняется._
