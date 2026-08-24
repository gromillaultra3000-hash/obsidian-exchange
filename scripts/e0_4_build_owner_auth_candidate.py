#!/usr/bin/env python3
"""Build the bounded E0.4 owner/auth candidate from exact reviewed inputs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path


INPUTS = {
    "relay": {
        "base_sha256": "c1ef783e3005f4698540ddc5368ef9a4592612fcf666b403ecbb7c4a359bd7ff",
        "source_sha256": "16dc034f4213f2765bcca0fecd97d62fdeb40a8a0d70e0e94568dfb5e1d6dcfc",
        "functions": ["_session_dead", "_receipt_state", "api_order", "pay", "montera_webhook", "rspay_webhook"],
    },
    "bot": {
        "base_sha256": "a015b5b12870fa2f1eec7d0fb638cc2c94cb90235850d474ebb25455446372fb",
        "source_sha256": "cae69ae8d33b01c51b88cf36a78e5a4a69da0339408e86bae9f5b058edfaf800",
        "functions": ["skip_review_comment", "process_review_comment", "finalize_review", "inline_check_payment", "handle_webapp"],
    },
    "order_read_store": {
        "base_sha256": "2cc91c733a8388ac2f643016fe192f7687ef0c44b79305d23fed50dcfd2ca06d",
        "source_sha256": "5651f8400da4b0024b11bc77f03f9cb239ac284766f44586f0673788e1d54506",
        "functions": ["_order_authority"],
        "methods": {"SQLiteOrderReadStore":["authorized_snapshot"],
                    "PostgresOrderReadStore":["authorized_snapshot"]},
    },
    "payment_session_store": {
        "base_sha256": "eb41d099a06beac4251190d10221467bdca4b21db7bc97dba687dd8d40653b8e",
        "source_sha256": "5684f496570e285987c58bfce0e3c59ef195ac689591a7367028bd93351aaf11",
        "functions": ["_order_authority"],
        "methods": {
            "SQLitePaymentSessionStore":["get_by_token","latest_for_authorized_order","latest_active_for_authorized_order","latest_provider_invoice_for_authorized_order"],
            "PostgresPaymentSessionStore":["get_by_token","latest_for_authorized_order","latest_active_for_authorized_order","latest_provider_invoice_for_authorized_order"],
        },
    },
    "receipt_store": {
        "base_sha256": "252ada0ad673dfb60ad3f18913b11aa0a6bfa90d647978af71a97651cc54e123",
        "source_sha256": "2abf6710b247b1f8452795bbfb173e262a805195a81bb15f1b5a864ec9e0d193",
        "methods": {"SQLiteReceiptStore":["authorized_state"],
                    "PostgresReceiptStore":["authorized_state"]},
    },
    "engagement_store": {
        "base_sha256": "9c989eaba773416b1414a0e652130ffea529cff4fcd6158c4e58285da59464b0",
        "source_sha256": "12975d71a265fb7ee137c1e060abbca16c55adcc35d62a501fd5397201d2a8e4",
        "methods": {"SQLiteEngagementStore":["comment_review","finalize_review"],
                    "PostgresEngagementStore":["comment_review","finalize_review"]},
    },
    "order_access": {
        "source_sha256": "2736446380833c881460e997ebc07237c55e4c3d26bb2723a411ceed25a08dfb",
        "copy_whole": True,
    },
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _node_ranges(raw: bytes) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    text = raw.decode("utf-8")
    lines = raw.splitlines(keepends=True)
    tree = ast.parse(text)
    result, class_ends = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            result[node.name] = (sum(map(len, lines[:start])), sum(map(len, lines[:node.end_lineno])))
        elif isinstance(node, ast.ClassDef):
            class_ends[node.name] = sum(map(len, lines[:node.end_lineno]))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([child.lineno] + [d.lineno for d in child.decorator_list]) - 1
                    result[f"{node.name}.{child.name}"] = (
                        sum(map(len, lines[:start])), sum(map(len, lines[:child.end_lineno])))
    return result, class_ends


def _splice(base: bytes, source: bytes, functions: list[str], methods: dict[str, list[str]]) -> bytes:
    base_ranges, base_class_ends = _node_ranges(base)
    source_ranges, _ = _node_ranges(source)
    names = list(functions)
    for cls, method_names in methods.items():
        names.extend(f"{cls}.{name}" for name in method_names)
    missing_source = [name for name in names if name not in source_ranges]
    if missing_source:
        raise ValueError(f"missing reviewed source functions: {','.join(missing_source)}")
    replacements, additions = [], {}
    for name in names:
        s_start, s_end = source_ranges[name]
        replacement = source[s_start:s_end]
        if name in base_ranges:
            b_start, b_end = base_ranges[name]
            replacements.append((b_start, b_end, replacement))
        elif "." in name:
            cls = name.split(".", 1)[0]
            if cls not in base_class_ends:
                raise ValueError(f"missing reviewed base class: {cls}")
            additions.setdefault(base_class_ends[cls], []).append(replacement)
        else:
            tree = ast.parse(base.decode("utf-8"))
            first_class = next((node for node in tree.body if isinstance(node, ast.ClassDef)), None)
            if first_class is None:
                raise ValueError("base has no insertion class boundary")
            base_lines = base.splitlines(keepends=True)
            offset = sum(map(len, base_lines[:first_class.lineno - 1]))
            additions.setdefault(offset, []).append(replacement + b"\n\n")
    for offset, blocks in additions.items():
        replacements.append((offset, offset, b"\n" + b"\n\n".join(blocks)))
    candidate = base
    for start, end, replacement in sorted(replacements, reverse=True):
        candidate = candidate[:start] + replacement + candidate[end:]
    ast.parse(candidate.decode("utf-8"))
    return candidate


def prepare(base: Path, source: Path, component: str) -> tuple[bytes, dict]:
    spec = INPUTS[component]
    source_raw = source.read_bytes()
    if _sha256(source_raw) != spec["source_sha256"]:
        raise ValueError(f"{component} checkout source digest mismatch")
    if spec.get("copy_whole"):
        return source_raw, {"component":component,"baseSha256":None,
                            "sourceSha256":_sha256(source_raw),
                            "candidateSha256":_sha256(source_raw),
                            "selectedFunctions":["WHOLE_NEW_REVIEWED_MODULE"],"bytes":len(source_raw)}
    base_raw = base.read_bytes()
    if _sha256(base_raw) != spec["base_sha256"]:
        raise ValueError(f"{component} deployed base digest mismatch")
    candidate = _splice(base_raw, source_raw, spec.get("functions", []), spec.get("methods", {}))
    return candidate, {
        "component": component,
        "baseSha256": _sha256(base_raw),
        "sourceSha256": _sha256(source_raw),
        "candidateSha256": _sha256(candidate),
        "selectedFunctions": spec.get("functions", []) + [
            f"{cls}.{name}" for cls, names in spec.get("methods", {}).items() for name in names],
        "bytes": len(candidate),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay-base", type=Path, required=True)
    parser.add_argument("--relay-source", type=Path, required=True)
    parser.add_argument("--bot-base", type=Path, required=True)
    parser.add_argument("--bot-source", type=Path, required=True)
    parser.add_argument("--deployed-root", type=Path,
                        default=Path("/opt/obsidian-exchange"))
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root or args.relay_source.parent.parent
    prepared = [
        ("relay-fastapi/main.py",) + prepare(args.relay_base, args.relay_source, "relay"),
        ("bot/main_bot.py",) + prepare(args.bot_base, args.bot_source, "bot"),
        ("relay/core/order_access.py",) + prepare(Path("/dev/null"), source_root / "relay/core/order_access.py", "order_access"),
        ("relay/repositories/order_read_store.py",) + prepare(args.deployed_root / "relay/repositories/order_read_store.py", source_root / "relay/repositories/order_read_store.py", "order_read_store"),
        ("relay/repositories/payment_session_store.py",) + prepare(args.deployed_root / "relay/repositories/payment_session_store.py", source_root / "relay/repositories/payment_session_store.py", "payment_session_store"),
        ("relay/repositories/receipt_store.py",) + prepare(args.deployed_root / "relay/repositories/receipt_store.py", source_root / "relay/repositories/receipt_store.py", "receipt_store"),
        ("relay/repositories/engagement_store.py",) + prepare(args.deployed_root / "relay/repositories/engagement_store.py", source_root / "relay/repositories/engagement_store.py", "engagement_store"),
    ]
    args.output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    results = []
    for filename, candidate, evidence in prepared:
        output = args.output_dir / filename
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(candidate)
            handle.flush()
            os.fsync(handle.fileno())
        results.append(evidence)
    print(json.dumps({"schemaVersion":"e0-4-owner-auth-candidate-build.v1",
                      "productionMutation":False,"artifacts":results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
