"""Archive record shape and canonical hashing (FR-MEM-04, PRD 13.2, 15.1)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

VALID_KINDS = ("model_call", "tool_call", "channel_in", "channel_out")
ZERO_HASH = "0" * 64


def canonical_json(value: object) -> str:
    """Canonical form; raises ValueError on NaN/Infinity and TypeError on a
    non-serialisable value -- both are the archive writer's rejection signal."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def split_jsonl(text: str) -> list[str]:
    """The non-blank lines of stored JSONL, split on "\\n" only. Never
    `str.splitlines()`: it also breaks on U+2028, U+2029, U+0085, \\x0b,
    \\x0c and \\x1c-\\x1e, which `canonical_json` (ensure_ascii=False) can
    leave raw inside a record, and would shred that record in two. A
    trailing "\\r" (CRLF) is dropped; only " \\t\\r" count as blank."""
    lines = []
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line.strip(" \t\r"):
            lines.append(line)
    return lines


def record_hash(record: dict) -> str:
    """SHA-256 hex of the canonical JSON of `record` without its "hash" field."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def format_ts(dt: datetime) -> str:
    """RFC 3339 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
