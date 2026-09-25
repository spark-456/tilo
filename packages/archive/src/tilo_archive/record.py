"""Archive record shape and canonical hashing (FR-MEM-04, PRD 13.2, 15.1)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

VALID_KINDS = ("model_call", "tool_call", "channel_in", "channel_out")
ZERO_HASH = "0" * 64
SCHEMA_VERSION = "1.0"


def canonical_json(value: object) -> str:
    """json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    allow_nan=False) -- the exact canonical form the brief defines. Raises
    ValueError on NaN/Infinity and TypeError on a non-JSON-serialisable
    value; both are the archive writer's rejection signal."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def record_hash(record: dict) -> str:
    """SHA-256 hex of the canonical JSON of `record` without its "hash" field."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def format_ts(dt: datetime) -> str:
    """RFC 3339 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
