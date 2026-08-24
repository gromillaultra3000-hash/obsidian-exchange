#!/usr/bin/env python3
"""Emit only environment variable names from explicitly allowlisted files."""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import stat
from datetime import datetime, timezone

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
MAX_FILE_BYTES = 1024 * 1024
MAX_LINE_CHARS = 16384
PRODUCTION_SOURCES = {
    "app-env":"/etc/obsidian-exchange/app.env", "runtime-env":"/etc/obsidian-exchange/runtime.env",
    "admin-env":"/etc/obsidian-exchange/admin.env", "support-env":"/etc/obsidian-exchange/support.env",
    "payout-env":"/etc/obsidian-exchange/payout-worker.env",
    "pg-app-active":"/etc/obsidian-exchange/postgres/app.active.env",
    "pg-notifier-active":"/etc/obsidian-exchange/postgres/notifier.active.env",
    "pg-monitor-active":"/etc/obsidian-exchange/postgres/monitor.active.env",
    "pg-support-active":"/etc/obsidian-exchange/postgres/support.active.env",
    "pg-admin-active":"/etc/obsidian-exchange/postgres/admin.active.env",
    "pg-payout-active":"/etc/obsidian-exchange/postgres/payout.active.env",
    "kairos-security":"/etc/kairos/security.env", "kairos-runtime":"/var/lib/kairos/runtime.env",
    "lumi-security":"/etc/lumi/security.env", "callback-env":"/etc/obsidian-exchange/callback-handler.env",
}
PATH_TO_SOURCE = {path: identifier for identifier, path in PRODUCTION_SOURCES.items()}
PATH_TO_SOURCE.update({"/root/bot/.env":"legacy-monitor-env",
                       "/root/kairos/.env":"legacy-kairos-env",
                       "/root/lumi/.env":"legacy-lumi-env"})
PRODUCTION_UNITS = ("relay-fastapi.service","exchange-bot.service","exchange-notifier.service",
                    "obsidian-monitor.service","admin-panel.service","support-bot.service",
                    "obsidian-payout-worker.service","relay-shadow.service","kairos.service",
                    "lumi.service","callback-handler.service")


def parse_names(text: str) -> tuple[list[str], int]:
    if "\x00" in text:
        raise ValueError("ENV_PARSE_NUL")
    names: list[str] = []
    seen: set[str] = set()
    rejected = 0
    for line in text.splitlines():
        if len(line) > MAX_LINE_CHARS or line.rstrip().endswith("\\"):
            rejected += 1
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            rejected += 1
            continue
        if "=" not in stripped:
            rejected += 1
            continue
        candidate = stripped.split("=", 1)[0].strip()
        if not NAME.fullmatch(candidate):
            rejected += 1
            continue
        if candidate in seen:
            rejected += 1
            continue
        seen.add(candidate)
        names.append(candidate)
    return sorted(names), rejected


def observe(identifier: str, path: str) -> dict:
    result = {"id": identifier, "status": "UNKNOWN", "members": [],
              "rejectedLineCount": 0}
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except FileNotFoundError:
        result["status"] = "MISSING"
        return result
    except OSError:
        result["status"] = "UNREADABLE_OR_UNSAFE"
        return result
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            result["status"] = "UNSAFE_NOT_REGULAR"
            return result
        if metadata.st_size > MAX_FILE_BYTES:
            result["status"] = "UNSAFE_OVERSIZE"
            return result
        before = (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
        raw = os.read(fd, MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            result["status"] = "UNSAFE_OVERSIZE"
            return result
        after_meta = os.fstat(fd)
        after = (after_meta.st_dev, after_meta.st_ino, after_meta.st_size,
                 after_meta.st_mtime_ns, after_meta.st_ctime_ns)
        if before != after or len(raw) != after_meta.st_size:
            result["status"] = "UNSTABLE_DURING_READ"
            return result
        expected_uid = 995 if identifier == "kairos-runtime" else 0
        if identifier in PRODUCTION_SOURCES and (after_meta.st_uid != expected_uid or stat.S_IMODE(after_meta.st_mode) != 0o600):
            result["status"] = "UNSAFE_METADATA"
            return result
        text_value = raw.decode("utf-8", errors="strict")
        names, rejected = parse_names(text_value)
        if rejected:
            result.update(status="MALFORMED", members=[], rejectedLineCount=rejected)
            return result
        result.update(status="OBSERVED_NAMES_ONLY", members=names,
                      rejectedLineCount=rejected,
                      mode=oct(stat.S_IMODE(metadata.st_mode)), uid=metadata.st_uid,
                      gid=metadata.st_gid)
        return result
    except (OSError, UnicodeError, ValueError):
        result["status"] = "UNREADABLE_OR_INVALID_ENCODING"
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _unit_files(unit: str) -> list[str]:
    base = f"/etc/systemd/system/{unit}"
    return [base] + sorted(glob.glob(base + ".d/*.conf"))


def _stable_text(path: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before_meta = os.fstat(fd)
        if not stat.S_ISREG(before_meta.st_mode) or before_meta.st_size > MAX_FILE_BYTES:
            raise ValueError("UNSAFE_UNIT_SOURCE")
        before = (before_meta.st_dev, before_meta.st_ino, before_meta.st_size,
                  before_meta.st_mtime_ns, before_meta.st_ctime_ns)
        raw = os.read(fd, MAX_FILE_BYTES + 1)
        after_meta = os.fstat(fd)
        after = (after_meta.st_dev, after_meta.st_ino, after_meta.st_size,
                 after_meta.st_mtime_ns, after_meta.st_ctime_ns)
        if len(raw) > MAX_FILE_BYTES or before != after or len(raw) != after_meta.st_size:
            raise ValueError("UNSTABLE_UNIT_SOURCE")
        return raw.decode("utf-8", errors="strict")
    finally:
        os.close(fd)


def observe_unit(unit: str) -> dict:
    files: list[str] = []
    eliminated: list[str] = []
    inline: set[str] = set()
    inline_empty: set[str] = set()
    unset: set[str] = set()
    status = "OBSERVED_NAMES_ONLY"
    unit_files_before = _unit_files(unit)
    for path in unit_files_before:
        try:
            text_value = _stable_text(path)
        except (OSError, UnicodeError, ValueError):
            status = "UNIT_SOURCE_UNREADABLE"
            continue
        in_service = False
        for raw_line in text_value.splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_service = line == "[Service]"
                continue
            if not in_service or not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                status = "UNSUPPORTED_UNIT_CONTINUATION"
                continue
            if line == "EnvironmentFile=":
                eliminated.extend(files)
                files = []
            elif line.startswith("EnvironmentFile="):
                ref = line.split("=", 1)[1].strip()
                optional = ref.startswith("-")
                ref = ref[1:] if optional else ref
                source_id = PATH_TO_SOURCE.get(ref)
                if source_id is None:
                    status = "UNKNOWN_ENVIRONMENT_FILE"
                else:
                    files.append(source_id)
            elif line == "Environment=":
                inline.clear(); inline_empty.clear()
            elif line.startswith("Environment="):
                assignment = line.split("=", 1)[1].strip().strip('"')
                if any(ch.isspace() for ch in assignment):
                    status = "UNSUPPORTED_MULTI_ASSIGNMENT"
                    continue
                name = assignment.split("=", 1)[0]
                if NAME.fullmatch(name):
                    inline.add(name)
                    if assignment == name + "=": inline_empty.add(name)
                else:
                    status = "UNSUPPORTED_INLINE_ENVIRONMENT"
            elif line.startswith("UnsetEnvironment="):
                token = line.split("=", 1)[1].strip()
                if not token:
                    unset.clear()
                elif any(ch.isspace() for ch in token):
                    status = "UNSUPPORTED_MULTI_UNSET"
                elif "=" in token:
                    status = "UNSUPPORTED_VALUE_SPECIFIC_UNSET"
                elif NAME.fullmatch(token):
                    unset.add(token)
            elif line.startswith("PassEnvironment=") and line != "PassEnvironment=":
                status = "UNSUPPORTED_PASS_ENVIRONMENT"
    if unit_files_before != _unit_files(unit):
        status = "UNSTABLE_UNIT_FILE_SET"
    inline -= unset
    inline_empty -= unset
    return {"id": unit, "status": status, "files": files,
            "eliminatedSourceIds": sorted(set(PATH_TO_SOURCE.get(p, p) for p in eliminated)),
            "inlineNames": sorted(inline), "inlineEmptyNames": sorted(inline_empty),
            "unsetNames": sorted(unset)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if not args.production:
        parser.error("closed production observation requires --production")
    observations = [observe(identifier, path) for identifier, path in PRODUCTION_SOURCES.items()]
    units = [observe_unit(unit) for unit in PRODUCTION_UNITS]
    required = set(PRODUCTION_SOURCES)
    failed = [item["id"] for item in observations if item["id"] in required and item["status"] != "OBSERVED_NAMES_ONLY"]
    source_status = {item["id"]: item["status"] for item in observations}
    for unit in units:
        missing = [source for source in unit["files"] if source_status.get(source) == "MISSING"]
        if missing:
            unit["status"] = "NO_GO_REQUIRED_SOURCE_MISSING"
        configured = set(unit["inlineNames"])
        for source in unit["files"]:
            configured.update(next((item["members"] for item in observations if item["id"] == source), []))
        configured -= set(unit["unsetNames"])
        unit["exactConfiguredEnvironmentNames"] = sorted(configured)
    failed += [item["id"] for item in units if item["status"] != "OBSERVED_NAMES_ONLY"]
    print(json.dumps({"schema": "obsidian.names-only-observation.v1",
                      "observedAt": datetime.now(timezone.utc).isoformat(),
                      "secretValuesPersistedOrEmitted": False,
                      "aggregateStatus": "MATCH" if not failed else "NO_GO",
                      "failedIds": sorted(failed), "observations": observations,
                      "units": units}, sort_keys=True))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
