"""Advisory-аналитика конверсии провайдеров (перенос идеи LUMI outcome-learning:
build_provider_strategy + порог доказательности). ТОЛЬКО НАБЛЮДЕНИЕ — на выбор
провайдера в smart_router НЕ влияет. Отвечает на вопрос «за какие реквизиты реально
платят», по фактическим исходам из БД.

Логика LUMI, адаптированная под платёжную конверсию:
- outcome-score провайдера = доля показов реквизитов, приведших к оплаченной заявке;
- нужен «потолок доказательности»: вывод по провайдеру делаем только при ≥ MIN_SAMPLES
  показов, иначе verdict='insufficient' (мало данных — не делаем вывод);
- честная пометка: это association (корреляция), не причинность.

Verdict:
    converts      — показов ≥ MIN и есть оплаты (кандидат в «recommended»)
    zero          — показов ≥ MIN и НОЛЬ оплат (кандидат в «avoid» = утечка конверсии)
    insufficient  — показов < MIN (данных мало, вывода нет)
"""
from __future__ import annotations
import os
from repositories.reporting_store import from_environment as _reporting_store

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
MIN_SAMPLES = 5          # порог доказательности (LUMI использует 3 для кодинга; для платежей берём 5)
PAID_STATUSES = ("paid", "sent")


def provider_conversion(days: int = 30, db_path: str = DB_PATH) -> dict:
    """Вернёт per-provider метрики конверсии + сводку. Advisory, роутинг не меняет."""
    try:
        rows = _reporting_store(sqlite_path=db_path).provider_conversion_rows(days)
    except Exception as e:
        return {"error": str(e), "providers": [], "summary": {}}

    providers = []
    for r in rows:
        shown = int(r["shown"] or 0)
        paid = int(r["paid"] or 0)
        score = round(paid / shown, 4) if shown else 0.0
        if shown < MIN_SAMPLES:
            verdict = "insufficient"
        elif paid > 0:
            verdict = "converts"
        else:
            verdict = "zero"
        providers.append({
            "provider": r["provider"],
            "shown": shown,
            "paid": paid,
            "conversion": score,
            "conversion_pct": round(score * 100, 1),
            "verdict": verdict,
            "sufficient_evidence": shown >= MIN_SAMPLES,
        })

    # сортировка: сначала конвертящие (по скору), потом мало данных, потом «утечки» по объёму показов
    order = {"converts": 0, "insufficient": 1, "zero": 2}
    providers.sort(key=lambda p: (order[p["verdict"]], -p["conversion"], -p["shown"]))

    total_shown = sum(p["shown"] for p in providers)
    total_paid = sum(p["paid"] for p in providers)
    converts = [p for p in providers if p["verdict"] == "converts"]
    leaks = [p for p in providers if p["verdict"] == "zero"]
    biggest_leak = max(leaks, key=lambda p: p["shown"], default=None)

    summary = {
        "days": days,
        "total_shown": total_shown,
        "total_paid": total_paid,
        "overall_conversion_pct": round(100 * total_paid / total_shown, 1) if total_shown else 0.0,
        "best_provider": converts[0]["provider"] if converts else None,
        "best_provider_pct": converts[0]["conversion_pct"] if converts else None,
        "biggest_leak": biggest_leak["provider"] if biggest_leak else None,
        "biggest_leak_shown": biggest_leak["shown"] if biggest_leak else 0,
        "note": "Advisory: association, не причинность. На маршрутизацию НЕ влияет.",
    }
    return {"providers": providers, "summary": summary}


if __name__ == "__main__":
    import json
    print(json.dumps(provider_conversion(), ensure_ascii=False, indent=2))
