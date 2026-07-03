# ObsidianExchange — CLAUDE.md

Контекст проекта для автономного агента. Читать в начале каждой сессии.

## Что такое проект

Production крипто-обменник RUB→BTC/LTC/USDT через СБП, non-KYC.
Сайт: obsidian-exchange.org
Бот: Telegram Mini App + aiogram бот

## Стек

- FastAPI: relay-fastapi/main.py (порт 5001, systemd: relay-fastapi)
- Бот: bot/main_bot.py (systemd: exchange-bot)
- БД: SQLite /root/exchange.db (общая для бота, сайта, админки)
- Шаблоны: relay-fastapi/templates/ (Jinja2, extends base.html)
- Mini App: relay/webapp.html (отдаётся через /webapp)
- Провайдеры: relay/providers/
- Smart router: relay/services/smart_router.py
- Деплой: git push → GitHub → сервер тянет каждые 15 мин (systemd timer)

## Провайдеры оплаты (актуально на 03.07.2026)

| Провайдер | Статус | Вес |
|-----------|--------|-----|
| MonteraProvider | ✅ PRIMARY | 70% |
| BrabusProvider | ✅ SECONDARY | 20% |
| GreenPayProvider | ⚠️ нестабилен | 10% |
| FallbackProvider | ✅ резерв | last resort |
| PlategaProvider | ❌ offline | не использовать |

Montera: SBP через payment_gateway=sbp_rub, карта через payment_detail_type=card.
Вебхук Montera: /montera/webhook (уже реализован в main.py).

## Правила коммитов

```bash
python3 -m py_compile relay-fastapi/main.py && echo OK || exit 1
git add <конкретные файлы>  # никогда git add -A
git commit -m "feat/fix/perf: описание"
git push origin master
```

Никогда не коммитить: .env, *.db, API ключи, *.pyc, __pycache__

## Что уже сделано — не переделывать

- Smart router (health-based weighted selection)
- Фоновые задачи: cleanup_expired_orders, health_check_task
- /admin/analytics — дашборд аналитики
- /api/system-status — статус системы
- /api/rates — с кешем 60 сек (_rates_cache)
- /api/history — возвращает session_token для pending-заявок
- webapp.html — кнопка "💳 Оплатить" для pending в истории
- 404.html / 500.html — кастомные страницы ошибок
- base.html — Open Graph + Twitter Card мета-теги
- web_users, web_sessions, support_tickets — таблицы мигрированы
- auth.py — сессии, CSRF, bcrypt
- dashboard/exchange — выбор СБП/Карта передаётся в PaymentService

## Приоритеты следующих задач

1. Проверить что Montera вебхук корректно обновляет статус заявок (end-to-end тест)
2. Добавить Montera в nginx rate-limit блок если отсутствует
3. Мониторинг: алерт в Telegram если все провайдеры упали одновременно
4. Реферальная аналитика в /dashboard/referral
5. CI/CD через GitHub Actions (py_compile + smoke test на каждый push)
6. Новый провайдер: изучить Lava / PayOK как дополнительный СБП канал

## Сессии

### Сессия 03.07.2026
Выполнено:
- Montera установлен PRIMARY (70%), Brabus 20%, GreenPay 10%
- MonteraProvider добавлен в _load_provider() и сброшен в healthy в БД
- /api/history: JOIN payment_sessions, возвращает session_token
- webapp.html: кнопка "💳 Оплатить" для pending-заявок
- Кастомные 404/500 страницы (тёмная тема #050507, акцент #7c3aed)
- SEO Open Graph + Twitter Card в base.html
- /api/rates: 60-секундный кеш на уровне FastAPI
- dashboard/exchange: поле выбора СБП/Карта → передаётся в PaymentService
