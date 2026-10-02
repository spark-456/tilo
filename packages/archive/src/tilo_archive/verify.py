"""CLI: `python -m tilo_archive.verify <path to a run's jsonl> [--head <seq>:<hash>]`
(FR-MEM-04).

Prints one JSON line `{"ok": bool, "records": N, "problems": [...]}` and
exits 0 when the chain is intact, 1 otherwise. `--head` is the run's last
known head (`RunArchive.head()`): with it a truncated or extended tail is
reported too, which the chain alone cannot see.
"""

from __future__ import annotations

import json
import re
import sys

from .archive import verify_chain
from .record import split_jsonl

USAGE = "usage: python -m tilo_archive.verify <path> [--head <seq>:<64 hex hash>]"
HEAD_RE = re.compile(r"([0-9]{1,9}):([0-9a-f]{64})")


def _fail(problem: str) -> int:
    print(json.dumps({"ok": False, "records": 0, "problems": [problem]}))
    return 1


def _parse_lines(lines: list[str]) -> tuple[list[dict], list[str]]:
    """Parses each line on its own so one unparseable/truncated record (e.g.
    a process that died mid-append) does not crash the whole CLI: it is
    reported as its own problem, keyed by line number (not seq) since a
    corrupted record's own "seq" cannot be read, and every other line still
    verifies."""
    records: list[dict] = []
    problems: list[str] = []
    for i, line in enumerate(lines, start=1):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            problems.append(f"line {i}: unparseable or truncated record")
    return records, problems


def main(argv: list[str]) -> int:
    expected_head: tuple[int, str] | None = None
    if len(argv) == 3 and argv[1] == "--head":
        match = HEAD_RE.fullmatch(argv[2])
        if match is None:
            return _fail("--head must be <seq>:<64 hex sha-256>")
        expected_head = (int(match.group(1)), match.group(2))
    elif len(argv) != 1:
        return _fail(USAGE)
    try:
        with open(argv[0], "rb") as handle:
            lines = split_jsonl(handle.read().decode("utf-8"))
    except UnicodeDecodeError as exc:
        return _fail(f"file is not valid UTF-8: {exc}")
    records, parse_problems = _parse_lines(lines)
    problems = parse_problems + verify_chain(records, expected_head)
    print(json.dumps({"ok": not problems, "records": len(records), "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
