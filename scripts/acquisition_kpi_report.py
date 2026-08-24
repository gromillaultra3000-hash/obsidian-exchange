#!/usr/bin/env python3
"""Print a privacy-safe KPI report from a SQLite database opened read-only."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from relay.services.acquisition_kpi import build_acquisition_kpi_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="/root/exchange.db")
    parser.add_argument("--minimum-cohort-users", type=int, default=10)
    args = parser.parse_args()
    database = Path(args.database).resolve()
    uri = f"file:{database}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        report = build_acquisition_kpi_report(
            connection,
            as_of=datetime.now(timezone.utc).isoformat(),
            minimum_cohort_users=args.minimum_cohort_users,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
