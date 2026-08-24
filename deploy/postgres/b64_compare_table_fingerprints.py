#!/usr/bin/env python3
"""Compare root-only source JSON manifest with digest-only restore rows."""
import hashlib
import json
import re
import sys
from pathlib import Path


source_path, restored_path = map(Path, sys.argv[1:3])
source = json.loads(source_path.read_text(encoding="utf-8"))
restored = []
for line in restored_path.read_text(encoding="utf-8").splitlines():
    table, count, digest = line.split("|")
    restored.append([table, int(count), digest])
for manifest in (source, restored):
    if (not isinstance(manifest, list)
            or any(not isinstance(row, list) or len(row) != 3
                   or not isinstance(row[0], str) or not row[0]
                   or not isinstance(row[1], int) or row[1] < 0
                   or not isinstance(row[2], str)
                   or re.fullmatch(r"[0-9a-f]{64}", row[2]) is None
                   for row in manifest)
            or len({row[0] for row in manifest}) != len(manifest)
            or manifest != sorted(manifest, key=lambda row: row[0])):
        raise SystemExit(2)
different = sorted(
    {row[0] for row in source} ^ {row[0] for row in restored}
    | {left[0] for left, right in zip(source, restored) if left != right}
)
encoded = json.dumps(restored, separators=(",", ":")).encode()
print(json.dumps({
    "status": "MATCH" if source == restored else "MISMATCH",
    "tables": len(restored),
    "restoredSha256": hashlib.sha256(encoded).hexdigest(),
    "differentTables": different,
}, separators=(",", ":")))
raise SystemExit(0 if source == restored else 1)
