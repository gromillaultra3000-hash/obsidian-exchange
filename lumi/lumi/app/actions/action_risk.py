RISK_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def is_high_or_critical(risk_level: str) -> bool:
    return RISK_ORDER.get(risk_level, 0) >= RISK_ORDER["high"]
