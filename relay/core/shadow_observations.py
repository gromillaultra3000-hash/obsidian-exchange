"""Frozen trigger catalog and deterministic plans for disabled E2 shadowing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from relay.core.shadow_producer import build_submission

CATALOG_VERSION = "shadow-trigger-catalog.v1"
PLAN_VERSION = "shadow-observation-plan.v1"
TRIGGERS = {
    "PERMISSION_DRIFT": {
        "subjectKind": "PERMISSION_POSTURE", "signalType": "PERMISSION_DRIFT",
        "sourceClass": "DETERMINISTIC", "bucketSeconds": 1,
        "factKeys": ("permission_valid", "withdrawal_enabled"),
        "factRules": {"permission_valid": ("BOOL",), "withdrawal_enabled": ("BOOL",)},
    },
    "CONNECTOR_DEGRADED": {
        "subjectKind": "CONNECTOR_HEALTH", "signalType": "CONNECTOR_DEGRADED",
        "sourceClass": "DETERMINISTIC", "bucketSeconds": 300,
        "factKeys": ("failure_count", "reachable"),
        "factRules": {"failure_count": ("INT_0_1000",), "reachable": ("BOOL",)},
    },
    "PROVIDER_RATE_LIMIT": {
        "subjectKind": "CONNECTOR_HEALTH", "signalType": "PROVIDER_RATE_LIMIT",
        "sourceClass": "PROVIDER", "bucketSeconds": 300,
        "factKeys": ("rate_limited", "retry_bucket"),
        "factRules": {"rate_limited": ("BOOL",),
                      "retry_bucket": ("LT_1M", "M1_5", "OVER_5M")},
    },
    "MARKET_DATA_STALE": {
        "subjectKind": "MARKET_WINDOW", "signalType": "MARKET_DATA_STALE",
        "sourceClass": "DETERMINISTIC", "bucketSeconds": 60,
        "factKeys": ("age_bucket", "source_count"),
        "factRules": {"age_bucket": ("S60_299", "S300_899", "S900_PLUS"),
                      "source_count": ("INT_0_1000",)},
    },
    "ADVISORY_UNAVAILABLE": {
        "subjectKind": "CONNECTOR_HEALTH", "signalType": "ADVISORY_UNAVAILABLE",
        "sourceClass": "ADVISORY", "bucketSeconds": 60,
        "factKeys": ("failure_class", "latency_bucket"),
        "factRules": {"failure_class": ("TIMEOUT", "ERROR", "MALFORMED", "UNKNOWN"),
                      "latency_bucket": ("LT_250MS", "MS250_999", "S1_3", "OVER_3S", "TIMEOUT")},
    },
}


def public_catalog() -> dict[str, Any]:
    return {
        "schemaVersion": CATALOG_VERSION,
        "triggers": [
            {"triggerId": trigger_id, **definition,
             "factKeys": list(definition["factKeys"]),
             "factRules": {key: list(values) for key, values in definition["factRules"].items()}}
            for trigger_id, definition in sorted(TRIGGERS.items())
        ],
    }


def plan_observation(
    *, trigger_id: str, observed_at: datetime, facts: dict[str, Any],
    hard_verdict: str, advisory_verdict: str, freshness: str,
) -> dict[str, Any]:
    definition = TRIGGERS.get(trigger_id)
    if definition is None:
        raise ValueError("shadow trigger is not catalogued")
    if set(facts) != set(definition["factKeys"]):
        raise ValueError("shadow trigger facts differ from frozen catalog")
    for key, value in facts.items():
        rules = definition["factRules"][key]
        valid = (rules == ("BOOL",) and isinstance(value, bool)) \
            or (rules == ("INT_0_1000",) and isinstance(value, int)
                and not isinstance(value, bool) and 0 <= value <= 1000) \
            or value in rules
        if not valid:
            raise ValueError("shadow trigger fact value is outside frozen buckets")
    if observed_at.tzinfo is None:
        raise ValueError("observation timestamp must be timezone-aware")
    observed = observed_at.astimezone(timezone.utc)
    bucket_seconds = definition["bucketSeconds"]
    bucket_epoch = int(observed.timestamp()) // bucket_seconds * bucket_seconds
    bucket = datetime.fromtimestamp(bucket_epoch, timezone.utc)
    submission = build_submission(
        observed_at=bucket, subject_kind=definition["subjectKind"],
        signal_type=definition["signalType"], source_class=definition["sourceClass"],
        freshness=freshness, facts=facts, hard_verdict=hard_verdict,
        advisory_verdict=advisory_verdict, decided_at=bucket,
    )
    identity = {
        "catalogVersion": CATALOG_VERSION, "triggerId": trigger_id,
        "bucketStart": bucket.isoformat(), "submission": submission,
    }
    observation_id = "obs_" + hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()).hexdigest()
    return {
        "schemaVersion": PLAN_VERSION, "catalogVersion": CATALOG_VERSION,
        "observationId": observation_id, "triggerId": trigger_id,
        "bucketStart": bucket.isoformat(), "bucketSeconds": bucket_seconds,
        "submission": submission,
    }
