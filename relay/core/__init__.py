"""ObsidianExchange — общее ЯДРО (core).

Единая точка входа для safety / intelligence / secrets, переиспользуемая всеми
поверхностями: обменник (relay-fastapi, bot), горячий кошелёк (relay/wallet),
позже сайт и Mini App. Первый кирпич «единой платформы» (docs/ARCHITECTURE_UNIFIED.md).

Сейчас это АДДИТИВНЫЙ фасад: канонический дом для secret-guard + единый импорт
существующих модулей из relay/services (ничего не перемещаем, старые импорты живы).
По мере миграции сами реализации переедут сюда, а services/* станут тонкими шимами.

Использование из нового кода:
    from core import contains_secret, redact
    from core import provider_conversion, evidence_summary, provider_failure_patterns
    from core.safety import verify_payment_settled, payout_circuit_status
"""
from __future__ import annotations

# --- secrets (канонический дом здесь) ---
from .secrets import contains_secret, secret_reason, redact  # noqa: F401

# --- intelligence (advisory, из relay/services) ---
try:
    from services.conversion_intel import provider_conversion  # noqa: F401
    from services.evidence import evidence_summary, assess as evidence_assess  # noqa: F401
    from services.failure_patterns import provider_failure_patterns  # noqa: F401
except Exception:  # pragma: no cover — core должен импортироваться даже вне контекста relay
    provider_conversion = evidence_summary = evidence_assess = provider_failure_patterns = None

__all__ = [
    "contains_secret", "secret_reason", "redact",
    "provider_conversion", "evidence_summary", "evidence_assess",
    "provider_failure_patterns",
]
