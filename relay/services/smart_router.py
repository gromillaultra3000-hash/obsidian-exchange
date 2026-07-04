"""
Intelligent payment provider router with health-based scoring and auto-failover.
Tracks success/failure per provider and routes to the healthiest available one.
"""
import sqlite3
import random
import logging
from typing import Optional, Dict
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/root/exchange.db")
logger = logging.getLogger(__name__)

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
    "LavaProvider": {
        "weight": 0.10,        # SBP + card via hosted payment page
        "min_amount": 100,
        "cooldown_seconds": 180,
        "max_consecutive_fails": 3,
    },
    "GreenPayProvider": {
        "weight": 0.05,        # legacy backup (frequently unavailable)
        "min_amount": 500,
        "cooldown_seconds": 300,
        "max_consecutive_fails": 2,
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


def record_outcome(provider: str, success: bool, response_time: float = 0.0):
    """Call after each payment attempt to update health metrics."""
    cfg = PROVIDER_CONFIG.get(provider, {})
    max_fails = cfg.get("max_consecutive_fails", 3)

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
                   SET avg_response_time=?, failed_count=?, last_checked=?, is_healthy=?
                   WHERE provider=?""",
                (new_avg, new_fails, now, healthy, provider)
            )
        else:
            healthy = 1 if success else 0
            conn.execute(
                """INSERT INTO provider_health
                   (provider, avg_response_time, failed_count, last_checked, is_healthy)
                   VALUES (?, ?, ?, ?, ?)""",
                (provider, round(response_time, 3), 0 if success else 1, now, healthy)
            )

        conn.commit()


def get_health_scores() -> Dict[str, dict]:
    """Return health score (0..1) and status for each provider."""
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
            scores[name] = {
                "is_healthy": is_healthy and not in_cooldown,
                "in_cooldown": in_cooldown,
                "failed_count": fails,
                "health_score": health_score,
                "avg_response_time": r["avg_response_time"] or 0,
                "last_checked": last,
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
        if amount < cfg.get("min_amount", 0):
            logger.debug("Provider %s skipped: amount %.0f < min %.0f",
                         name, amount, cfg.get("min_amount", 0))
            continue
        info = scores.get(name, {"is_healthy": True, "health_score": 0.5})
        if not info.get("is_healthy", True):
            logger.debug("Provider %s skipped: not healthy (fails=%d, cooldown=%s)",
                         name, info.get("failed_count", 0), info.get("in_cooldown"))
            continue
        weight = cfg["weight"] * max(info.get("health_score", 0.5), 0.1)
        candidates.append((name, weight))

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


def reset_provider(provider: str):
    """Manually re-enable a provider (e.g. after maintenance)."""
    with _db() as conn:
        conn.execute(
            "UPDATE provider_health SET failed_count=0, is_healthy=1 WHERE provider=?",
            (provider,)
        )
        conn.commit()
    logger.info("Provider %s manually reset to healthy", provider)
