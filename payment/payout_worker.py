#!/usr/bin/env python3
"""Dedicated consumer of durable payout intents (staged, disabled by default)."""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
RELAY = ROOT / "relay"
if str(RELAY) not in sys.path:
    sys.path.insert(0, str(RELAY))

from repositories import payout_store

logger = logging.getLogger("payout-worker")
DB_PATH = os.getenv("DB_PATH", str(ROOT / "exchange.db"))
POLL_SECONDS = max(1.0, float(os.getenv("PAYOUT_WORKER_POLL_SECONDS", "2") or 2))
_running = True


def _store():
    return payout_store.from_environment(sqlite_path=DB_PATH)


def run_once(signer: Callable[[dict], str] | None = None, store=None) -> dict:
    """Claim and execute at most one intent. Injectable signer keeps tests inert."""
    if signer is None:
        from services.payout_signer import sign as signer
    store = store or _store()
    intent = store.claim_next()
    if intent is None:
        return {"action": "idle"}
    is_referral = intent.get("intent_type") == "referral"
    ident = int(intent["id"] if is_referral else intent["order_id"])
    try:
        txid = signer(intent)
        if not store.succeed(intent, txid):
            raise RuntimeError("payout_intent_not_processing")
        return {"action": "succeeded", "intent_type": ("referral" if is_referral else "order"),
                "subject_id": ident, "txid": txid}
    except Exception as exc:
        # Any signer exception may have happened after broadcast. Never retry.
        try:
            store.review(intent, type(exc).__name__)
        except Exception:
            logger.critical("cannot persist review for intent %s", ident, exc_info=True)
        logger.error("intent %s requires review (%s)", ident, type(exc).__name__)
        return {"action": "review", "subject_id": ident,
                "intent_type": ("referral" if is_referral else "order"),
                "error_code": type(exc).__name__}


def _stop(_signum, _frame) -> None:
    global _running
    _running = False


def main() -> int:
    if os.getenv("PAYOUT_WORKER_ENABLED", "").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        logger.error("PAYOUT_WORKER_ENABLED is not set; refusing to start")
        return 78
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("payout worker started")
    while _running:
        result = run_once()
        if result["action"] == "idle":
            time.sleep(POLL_SECONDS)
    logger.info("payout worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
