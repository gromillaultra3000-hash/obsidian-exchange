"""
Intelligent payment provider router with health-based scoring and auto-failover.
Tracks success/failure per provider and routes to the healthiest available one.

Provider intelligence (паттерн Lumi, 12.07.2026):
- структурированный статус (READY/NO_TRADERS/BLOCKED/AUTH_ERROR/NETWORK/DEGRADED)
  + человекочитаемая причина blocker в provider_health — здоровье (is_healthy)
  считается как раньше, классификация только для дашбордов/алертов;
- бюджет-лимиты: BUDGET_<SHORT>=N в env (напр. BUDGET_MONTERA=30) — максимум
  попыток create_invoice в час, при превышении провайдер выпадает из выбора;
- конфигурируемая цепочка эскалации: ESCALATION_CHAIN=stormtrade,fallback (default).
"""
import os
import sqlite3
import random
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("/root/exchange.db")
logger = logging.getLogger(__name__)

# короткое имя (env/БД payment_sessions) ↔ имя класса провайдера
SHORT_NAMES = {
    "MonteraProvider": "montera",
    "BrabusProvider": "brabus",
    "VertuProvider": "vertu",
    "XPayConnectProvider": "xpay",
    "LavaProvider": "lava",
    "GreenPayProvider": "greenpay",
    "StormTradeProvider": "stormtrade",
    "FallbackProvider": "fallback",
    "PlategaProvider": "platega",
}
CLASS_BY_SHORT = {v: k for k, v in SHORT_NAMES.items()}

# Порядок ВЫГОДЫ для нас (лучшее → худшее), задан оператором. Управляет и
# авто-выбором (profit_weight), и порядком эскалации (get_escalation_chain), и
# порядком кнопок в боте. Переопределяется env PROVIDER_PROFIT_ORDER (короткие имена).
PROVIDER_PROFIT_ORDER_DEFAULT = "vertu,xpay,montera,brabus,stormtrade,fallback,lava,greenpay,platega"

# Провайдеры, фактически выдающие РОССИЙСКИЕ реквизиты (проверено по живым
# payment_sessions 13-16.07: vertu → Сбербанк 2202…, montera → Сбер/Т-Банк/Альфа,
# stormtrade → СБП + QR НСПК). Остальные на рублёвом потоке отдают зарубежное:
# brabus/fallback → карты 9762… (Humo, Узбекистан), xpay → ссылки на «Душанбе сити».
#
# Зачем тир: порядок выгоды (PROVIDER_PROFIT_ORDER) ставит xpay вторым, brabus
# четвёртым — по марже это верно, но клиент-россиянин зарубежную карту просто не
# оплачивает. За 4 дня выдано 16 зарубежных реквизитов против 2 российских при
# нулевой конверсии. Страна важнее маржи: маржа с неоплаченной заявки = 0.
#
# Тир доминирует над выгодой, но ВНУТРИ тира порядок выгоды сохраняется.
# Зарубежные не выключены — они запасной вариант, когда РФ-маршрутов нет
# (решение оператора 16.07.2026). PREFER_RU_REQUISITES=0 — вернуть старое
# поведение; RU_PROVIDERS — переопределить состав тира.
RU_PROVIDERS_DEFAULT = "vertu,montera,stormtrade"


def get_ru_providers() -> set:
    raw = os.getenv("RU_PROVIDERS", RU_PROVIDERS_DEFAULT)
    return {p.strip().lower() for p in raw.split(",") if p.strip().lower() in CLASS_BY_SHORT}


def is_ru_provider(provider_class: str) -> bool:
    short = SHORT_NAMES.get(provider_class, provider_class).split(":")[0].lower()
    return short in get_ru_providers()


def prefer_ru_enabled() -> bool:
    return os.getenv("PREFER_RU_REQUISITES", "1") != "0"

# эскалация по умолчанию = порядок выгоды: при «нет трейдера» у выбранного
# каскадим к СЛЕДУЮЩЕМУ выгодному, а не сразу к худшему. Заканчивается fallback
# (гарантированные реквизиты). Переопределяется env ESCALATION_CHAIN.
ESCALATION_CHAIN_DEFAULT = PROVIDER_PROFIT_ORDER_DEFAULT


def get_profit_order() -> List[str]:
    """Список коротких имён провайдеров в порядке выгоды (индекс 0 = самый выгодный)."""
    raw = os.getenv("PROVIDER_PROFIT_ORDER", PROVIDER_PROFIT_ORDER_DEFAULT)
    order = []
    for p in raw.split(","):
        s = p.strip().lower()
        if s in CLASS_BY_SHORT and s not in order:
            order.append(s)
    return order or PROVIDER_PROFIT_ORDER_DEFAULT.split(",")


def profit_weight(provider_class: str) -> float:
    """Вес по выгоде: самый выгодный провайдер получает наибольший (квадратичная
    шкала — явный приоритет выгодных при сохранении шанса у остальных).
    Неизвестные/невыгодные — минимальный вес."""
    order = get_profit_order()
    short = SHORT_NAMES.get(provider_class, provider_class).split(":")[0].lower()
    n = len(order)
    rank = order.index(short) if short in order else n
    return float(max(1, (n - rank)) ** 2)

PROVIDER_CONFIG = {
    "MonteraProvider": {
        "weight": 0.60,        # primary provider (SBP phone + card requisites)
        "min_amount": 1000,
        "cooldown_seconds": 240,
        "max_consecutive_fails": 3,
    },
    "BrabusProvider": {
        "weight": 0.20,        # deeplinks: tbank / alfa / vietqr
        "min_amount": 1000,
        "cooldown_seconds": 180,
        "max_consecutive_fails": 3,
    },
    "VertuProvider": {
        "weight": 0.30,        # SBP phone + c2c requisites, статус по опросу (нет вебхуков)
        "min_amount": 1000,
        "cooldown_seconds": 180,
        "max_consecutive_fails": 3,
        "required_env": "VERTU_LOGIN",  # не выбирать, пока нет учётных данных
    },
    "XPayConnectProvider": {
        "weight": 0.40,        # карта/СБП РФ, вебхук + уникализация суммы (docs.xpayconnect.io)
        "min_amount": 1000,
        "cooldown_seconds": 180,
        "max_consecutive_fails": 3,
        "required_env": "XPAY_API_KEY",  # не выбирать, пока нет учётных данных
    },
    "LavaProvider": {
        "weight": 0.10,        # SBP + card via hosted payment page
        "min_amount": 100,
        "cooldown_seconds": 180,
        "max_consecutive_fails": 3,
        "required_env": "LAVA_SHOP_ID",  # не выбирать, пока нет учётных данных
    },
    "GreenPayProvider": {
        "weight": 0.05,        # legacy backup (frequently unavailable)
        "min_amount": 500,
        "cooldown_seconds": 300,
        "max_consecutive_fails": 2,
    },
    "StormTradeProvider": {
        "weight": 0.0,         # худшая ставка: только эскалация из PaymentService,
        "min_amount": 1000,    # когда остальные не выдали реквизиты, и эксклюзивные
        "cooldown_seconds": 120,  # методы (SBP_QR/TO_ACCOUNT/MOBILE_TOP_UP)
        "max_consecutive_fails": 4,
        "required_env": "STORMTRADE_API_KEY",
        "last_resort": True,   # исключён из weighted-выбора choose_provider
    },
    "FallbackProvider": {
        "weight": 0.05,        # last resort
        "min_amount": 1000,
        "cooldown_seconds": 60,
        "max_consecutive_fails": 5,
    },
}


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


_schema_ready = False

def _ensure_schema():
    """Однократная миграция: status/blocker в provider_health + журнал попыток
    для бюджет-лимитов. Идемпотентно, ошибки не валят платёжный путь."""
    global _schema_ready
    if _schema_ready:
        return
    try:
        with _db() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(provider_health)")}
            if "status" not in cols:
                conn.execute("ALTER TABLE provider_health ADD COLUMN status TEXT DEFAULT ''")
            if "blocker" not in cols:
                conn.execute("ALTER TABLE provider_health ADD COLUMN blocker TEXT DEFAULT ''")
            conn.execute("CREATE TABLE IF NOT EXISTS provider_attempts ("
                         "provider TEXT NOT NULL, ts TEXT NOT NULL)")
            acols = {r[1] for r in conn.execute("PRAGMA table_info(provider_attempts)")}
            if "success" not in acols:
                # исход попытки для скользящего success-rate (reliability-скоринг).
                # DEFAULT 1 — старые строки (только бюджет) не искажают статистику.
                conn.execute("ALTER TABLE provider_attempts ADD COLUMN success INTEGER DEFAULT 1")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_attempts "
                         "ON provider_attempts(provider, ts)")
            conn.commit()
        _schema_ready = True
    except Exception as e:
        logger.warning("smart_router schema migration failed: %s", e)


def classify_error(error: Optional[str]) -> Tuple[str, str]:
    """Классифицирует ошибку провайдера в структурированный статус + причину.
    Только метаданные для дашбордов/алертов — на подсчёт здоровья не влияет."""
    if not error:
        return "READY", ""
    low = str(error).lower()
    short = str(error)[:200]
    if "мерчант заблокирован" in low or ("merchant" in low and "block" in low):
        return "BLOCKED", "Мерчант заблокирован на стороне провайдера — писать в их поддержку"
    if any(m in low for m in ("unauthorized", "api key", "apikey", "auth", "подпис",
                              "401", "403", "invalid token", "credentials")):
        return "AUTH_ERROR", short
    if any(m in low for m in ("реквизит", "не удалось выдать сделку", "подходящие",
                              "no available", "not found for amount", "нет свободных",
                              "попробуйте другой способ", "нет трейдер", "нет доступн",
                              "не найден", "requisit", "no trader", "not available",
                              "нет подходящ", "сделку не")):
        return "NO_TRADERS", short
    if any(m in low for m in ("timeout", "timed out", "connection", "network",
                              "dns", "unreachable", "read time")):
        return "NETWORK", short
    return "DEGRADED", short


def is_no_trader_error(error: Optional[str]) -> bool:
    """True, если ошибка провайдера = «нет трейдера/реквизита под сумму в моменте»
    (API ответил штатно). Такое НЕ должно штрафовать здоровье провайдера — иначе
    провайдер с временно занятыми трейдерами (напр. Vertu на мелких суммах) копит
    failed_count и выпадает из выбора целиком, хотя на др. суммах реквизиты есть.
    Единый источник классификации для payment_service (основной путь + эскалация)."""
    return classify_error(error)[0] == "NO_TRADERS"


def _disabled_providers() -> set:
    """Явный kill-switch: DISABLED_PROVIDERS=xpay,platega (короткие имена) —
    провайдер полностью исключается из выбора, probation и эскалации. Надёжнее,
    чем ручной is_healthy=0: тот снимается первым же успешным create_invoice
    (для XPay-песочницы «успех» = фейковые реквизиты клиенту)."""
    raw = os.getenv("DISABLED_PROVIDERS", "")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def is_provider_disabled(provider: str) -> bool:
    short = SHORT_NAMES.get(provider, provider).split(":")[0].lower()
    return short in _disabled_providers()


def _budget_for(provider: str) -> Optional[int]:
    """Бюджет попыток в час из env BUDGET_<SHORT> (напр. BUDGET_MONTERA=30).
    Нет переменной / невалидна → без лимита."""
    short = SHORT_NAMES.get(provider, provider).split(":")[0]
    raw = os.getenv(f"BUDGET_{short.upper()}", "")
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def attempts_last_hour(provider: str) -> int:
    _ensure_schema()
    try:
        since = (datetime.now() - timedelta(hours=1)).isoformat()
        with _db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM provider_attempts WHERE provider=? AND ts>=?",
                (provider, since)).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def success_rate_last_hour(provider: str) -> Optional[float]:
    """Доля успешных попыток за последний час (скользящий success-rate).
    None, если попыток слишком мало (<3) — тогда провайдер не штрафуется за
    отсутствие данных (нейтральный вклад в reliability)."""
    _ensure_schema()
    try:
        since = (datetime.now() - timedelta(hours=1)).isoformat()
        with _db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(success),0) ok "
                "FROM provider_attempts WHERE provider=? AND ts>=?",
                (provider, since)).fetchone()
        n = int(row["n"] or 0)
        if n < 3:
            return None
        return max(0.0, min(1.0, float(row["ok"]) / n))
    except Exception:
        return None


def latency_factor(avg_seconds: float) -> float:
    """Латентность → множитель 0.15..1.0 (быстрее = выше). avg_response_time у нас
    в секундах (0.2..1.5 в норме). Плавно штрафует медленных, не обнуляя их."""
    try:
        return max(0.15, 1.0 - min(float(avg_seconds) / 8.0, 0.85))
    except (TypeError, ValueError):
        return 1.0


def reliability_score(health_score: float, sr_hour: Optional[float],
                      avg_seconds: float) -> float:
    """Композит надёжности (паттерн Lumi reliability_score, адаптирован):
    здоровье + скользящий success-rate + латентность. Провайдер без свежих
    данных (sr_hour=None) не наказывается — его success-компонент нейтрален."""
    sr = 1.0 if sr_hour is None else sr_hour
    lf = latency_factor(avg_seconds)
    value = 0.55 * health_score + 0.25 * sr + 0.20 * lf
    return round(max(0.0, min(1.0, value)), 4)


def get_escalation_chain() -> List[str]:
    """Цепочка эскалации (короткие имена), когда выбранный провайдер не выдал
    реквизиты. Конфигурируется через ESCALATION_CHAIN, неизвестные имена отбрасываются."""
    raw = os.getenv("ESCALATION_CHAIN", ESCALATION_CHAIN_DEFAULT)
    chain = []
    for part in raw.split(","):
        short = part.strip().lower()
        if short in CLASS_BY_SHORT and short not in chain:
            chain.append(short)
        elif short:
            logger.warning("ESCALATION_CHAIN: неизвестный провайдер '%s' пропущен", short)
    # РФ-маршруты пробуем раньше зарубежных; внутри каждой группы порядок
    # (= выгода) сохраняется. Зарубежные остаются в хвосте как запасной вариант.
    if prefer_ru_enabled():
        ru = get_ru_providers()
        chain = [c for c in chain if c in ru] + [c for c in chain if c not in ru]
    return chain or ["stormtrade", "fallback"]


def record_outcome(provider: str, success: bool, response_time: float = 0.0,
                   error: Optional[str] = None):
    """Call after each payment attempt to update health metrics.
    error — текст ошибки провайдера для классификации статуса (метаданные)."""
    cfg = PROVIDER_CONFIG.get(provider, {})
    max_fails = cfg.get("max_consecutive_fails", 3)
    _ensure_schema()
    status, blocker = ("READY", "") if success else classify_error(error)

    with _db() as conn:
        row = conn.execute(
            "SELECT avg_response_time, failed_count FROM provider_health WHERE provider=?",
            (provider,)
        ).fetchone()

        now = datetime.now().isoformat()

        if row:
            new_avg = round(row["avg_response_time"] * 0.8 + response_time * 0.2, 3)
            if success:
                new_fails = 0
                healthy = 1
            else:
                new_fails = (row["failed_count"] or 0) + 1
                healthy = 0 if new_fails >= max_fails else 1

            conn.execute(
                """UPDATE provider_health
                   SET avg_response_time=?, failed_count=?, last_checked=?, is_healthy=?,
                       status=?, blocker=?
                   WHERE provider=?""",
                (new_avg, new_fails, now, healthy, status, blocker, provider)
            )
        else:
            healthy = 1 if success else 0
            conn.execute(
                """INSERT INTO provider_health
                   (provider, avg_response_time, failed_count, last_checked, is_healthy,
                    status, blocker)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (provider, round(response_time, 3), 0 if success else 1, now, healthy,
                 status, blocker)
            )

        # журнал попыток для бюджет-лимитов + скользящего success-rate (+ чистка >2ч)
        try:
            conn.execute("INSERT INTO provider_attempts (provider, ts, success) VALUES (?, ?, ?)",
                         (provider, now, 1 if success else 0))
            conn.execute("DELETE FROM provider_attempts WHERE ts < ?",
                         ((datetime.now() - timedelta(hours=2)).isoformat(),))
        except Exception as e:
            logger.debug("provider_attempts write failed: %s", e)

        conn.commit()


def get_health_scores() -> Dict[str, dict]:
    """Return health score (0..1) and status for each provider."""
    _ensure_schema()
    scores = {}
    with _db() as conn:
        rows = conn.execute("SELECT * FROM provider_health").fetchall()
        for r in rows:
            name = r["provider"]
            cfg = PROVIDER_CONFIG.get(name, {})
            fails = r["failed_count"] or 0
            max_fails = cfg.get("max_consecutive_fails", 3)
            is_healthy = bool(r["is_healthy"]) and fails < max_fails

            cooldown_secs = cfg.get("cooldown_seconds", 300)
            last = r["last_checked"]
            in_cooldown = False
            if not is_healthy and last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    in_cooldown = (datetime.now() - last_dt).total_seconds() < cooldown_secs
                except Exception:
                    pass

            health_score = max(0.0, 1.0 - (fails / max(max_fails, 1))) if is_healthy else 0.0
            keys = r.keys()
            budget = _budget_for(name)
            attempts = attempts_last_hour(name)
            avg_rt = r["avg_response_time"] or 0
            sr_hour = success_rate_last_hour(name)
            reliability = reliability_score(health_score, sr_hour, avg_rt) if is_healthy else 0.0
            scores[name] = {
                "is_healthy": is_healthy and not in_cooldown,
                # cooldown истёк, но провайдер всё ещё unhealthy → кандидат на
                # пробный запрос (self-heal: иначе без успеха он unhealthy навсегда)
                "probation": (not is_healthy) and (not in_cooldown),
                "disabled": is_provider_disabled(name),
                "in_cooldown": in_cooldown,
                "failed_count": fails,
                "health_score": health_score,
                "reliability": reliability,
                "success_rate_1h": sr_hour,
                "latency_factor": round(latency_factor(avg_rt), 3),
                "avg_response_time": avg_rt,
                "last_checked": last,
                "status": (r["status"] if "status" in keys else "") or
                          ("READY" if is_healthy else "DEGRADED"),
                "blocker": (r["blocker"] if "blocker" in keys else "") or "",
                "attempts_last_hour": attempts,
                "budget_per_hour": budget,
                "budget_exceeded": bool(budget is not None and attempts >= budget),
            }
    return scores


def choose_provider(amount: float = 10000) -> Optional[str]:
    """
    Choose the best available provider for the given amount.
    Uses weighted random selection biased toward healthier providers.
    Returns provider class name or None if all unavailable.
    """
    scores = get_health_scores()
    candidates = []

    for name, cfg in PROVIDER_CONFIG.items():
        if cfg.get("last_resort"):
            # невыгодные провайдеры не участвуют в обычном выборе —
            # их подключает PaymentService, когда остальные не выдали реквизиты
            continue
        if amount < cfg.get("min_amount", 0):
            logger.debug("Provider %s skipped: amount %.0f < min %.0f",
                         name, amount, cfg.get("min_amount", 0))
            continue
        required_env = cfg.get("required_env")
        if required_env and not os.getenv(required_env, ""):
            logger.debug("Provider %s skipped: env %s not set", name, required_env)
            continue
        if is_provider_disabled(name):
            logger.debug("Provider %s skipped: DISABLED_PROVIDERS", name)
            continue
        info = scores.get(name, {"is_healthy": True, "health_score": 0.5})
        probation = False
        if not info.get("is_healthy", True):
            if not info.get("probation"):
                logger.debug("Provider %s skipped: not healthy (fails=%d, cooldown=%s)",
                             name, info.get("failed_count", 0), info.get("in_cooldown"))
                continue
            # cooldown истёк — даём редкий пробный запрос (вес ×0.05): успех
            # вернёт провайдера в ротацию, фейл — обратно в cooldown. Без этого
            # weighted-провайдер после max_fails оставался unhealthy навсегда
            # (self-heal deadlock, как у StormTrade до 348184c).
            probation = True
        budget = _budget_for(name)
        if budget is not None and attempts_last_hour(name) >= budget:
            logger.info("Provider %s skipped: часовой бюджет исчерпан (%d/%d попыток)",
                        name, attempts_last_hour(name), budget)
            continue
        # базовый вес = ВЫГОДА для нас (profit_weight): самый выгодный провайдер
        # получает наибольший приоритет в авто-выборе (порядок задан оператором
        # через PROVIDER_PROFIT_ORDER)
        base = profit_weight(name)
        if probation:
            weight = base * 0.03
            logger.info("Provider %s: probation-кандидат (cooldown истёк, вес ×0.03)", name)
        else:
            # reliability = здоровье + скользящий success-rate + латентность
            # (паттерн Lumi): среди выгодных предпочитаем быстрого и стабильно
            # выдающего; медленный/мигающий получает меньше даже при высокой выгоде.
            rel = info.get("reliability")
            if rel is None:
                rel = info.get("health_score", 0.5)
            weight = base * max(rel, 0.1)
        candidates.append((name, weight))

    # Тир РФ: если доступен хоть один провайдер с российскими реквизитами —
    # выбираем только среди них. Зарубежные подключатся эскалацией, когда РФ
    # не выдадут (клиент-россиянин зарубежную карту не оплачивает).
    if prefer_ru_enabled() and candidates:
        ru_candidates = [(n, w) for n, w in candidates if is_ru_provider(n)]
        if ru_candidates:
            candidates = ru_candidates
        else:
            logger.warning("Нет доступных РФ-провайдеров для amount=%.0f — выбираем "
                           "среди зарубежных (запасной вариант)", amount)

    if not candidates:
        logger.warning("No healthy providers available for amount=%.0f, using FallbackProvider", amount)
        return "FallbackProvider"

    total = sum(w for _, w in candidates)
    r = random.random() * total
    for name, w in candidates:
        r -= w
        if r <= 0:
            return name
    return candidates[0][0]


def get_trust_metrics() -> Dict[str, object]:
    """Публичный OPSEC-безопасный агрегат для «слоя доверия к оплате».
    БЕЗ имён провайдеров: только число живых независимых маршрутов, среднее
    время до реквизитов и производный показатель надёжности выдачи.

    Надёжность считается от избыточности маршрутов (эскалация гарантирует
    реквизиты, пока жив хотя бы один маршрут) и их reliability — это устойчиво
    при малом трафике, в отличие от шумной доли оплат по истории заявок."""
    scores = get_health_scores()
    live = []  # (name, reliability, avg_rt) — только штатные маршруты выбора
    for name, cfg in PROVIDER_CONFIG.items():
        if cfg.get("last_resort"):
            continue
        required_env = cfg.get("required_env")
        if required_env and not os.getenv(required_env, ""):
            continue
        if is_provider_disabled(name):
            continue
        info = scores.get(name, {})
        if info.get("is_healthy"):
            live.append((name, info.get("reliability") or info.get("health_score", 0.5),
                         info.get("avg_response_time") or 0))

    active_routes = len(live)
    rts = [rt for _, _, rt in live if rt and rt > 0]
    avg_seconds = round(sum(rts) / len(rts), 2) if rts else 0.0
    avg_rel = (sum(r for _, r, _ in live) / active_routes) if active_routes else 0.0

    # P(хотя бы один маршрут выдаст реквизиты) ≈ 1 - Π(1 - reliability_i).
    # Пол 0.90 при ≥1 живом маршруте — чтобы показатель не пугал шумом на малой
    # выборке; 0 маршрутов → деградация (0%).
    fail_all = 1.0
    for _, r, _ in live:
        fail_all *= (1.0 - max(0.0, min(1.0, r)))
    reliability_pct = 0 if active_routes == 0 else max(90, round((1.0 - fail_all) * 100))
    reliability_pct = min(reliability_pct, 99)

    if active_routes == 0:
        label = "ограничена"
    elif active_routes >= 3 and avg_rel >= 0.8:
        label = "стабильна"
    else:
        label = "работает"

    return {
        "active_routes": active_routes,
        "avg_requisite_seconds": avg_seconds,
        "reliability_pct": reliability_pct,
        "status_label": label,
    }


def reset_provider(provider: str):
    """Manually re-enable a provider (e.g. after maintenance)."""
    _ensure_schema()
    with _db() as conn:
        conn.execute(
            "UPDATE provider_health SET failed_count=0, is_healthy=1, "
            "status='READY', blocker='' WHERE provider=?",
            (provider,)
        )
        conn.commit()
    logger.info("Provider %s manually reset to healthy", provider)
