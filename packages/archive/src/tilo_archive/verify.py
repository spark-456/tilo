"""CLI: `python -m tilo_archive.verify <path to a run's jsonl>` (FR-MEM-04).

Prints one JSON line `{"ok": bool, "records": N, "problems": [...]}` and
exits 0 when the chain is intact, 1 otherwise.
"""

from __future__ import annotations

import json
import sys

from .archive import verify_chain


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(json.dumps({"ok": False, "records": 0, "problems": ["usage: python -m tilo_archive.verify <path>"]}))
        return 1
    with open(argv[0], encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle.read().splitlines() if line.strip()]
    problems = verify_chain(records)
    print(json.dumps({"ok": not problems, "records": len(records), "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
