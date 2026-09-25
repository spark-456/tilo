"""CLI: `python -m tilo_archive.verify <path to a run's jsonl>` (FR-MEM-04).

Prints one JSON line `{"ok": bool, "records": N, "problems": [...]}` and
exits 0 when the chain is intact, 1 otherwise.
"""

from __future__ import annotations

import json
import sys

from .archive import verify_chain
from .record import split_jsonl


def _parse_lines(lines: list[str]) -> tuple[list[dict], list[str]]:
    """Parses each line on its own so one unparseable/truncated record (e.g.
    a process that died mid-append) does not crash the whole CLI: it is
    reported as its own problem, keyed by line number since a corrupted
    record's own "seq" cannot be read, and every other line still verifies."""
    records: list[dict] = []
    problems: list[str] = []
    for i, line in enumerate(lines, start=1):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            problems.append(f"seq {i} (line {i}): unparseable or truncated record")
    return records, problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(json.dumps({"ok": False, "records": 0, "problems": ["usage: python -m tilo_archive.verify <path>"]}))
        return 1
    try:
        with open(argv[0], "rb") as handle:
            lines = split_jsonl(handle.read().decode("utf-8"))
    except UnicodeDecodeError as exc:
        print(json.dumps({"ok": False, "records": 0, "problems": [f"file is not valid UTF-8: {exc}"]}))
        return 1
    records, parse_problems = _parse_lines(lines)
    problems = parse_problems + verify_chain(records)
    print(json.dumps({"ok": not problems, "records": len(records), "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
