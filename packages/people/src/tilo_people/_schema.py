"""Schema checks shared by the people modules, always through `tilo_policy.schemas.conforms`.

Checking one record takes a few milliseconds and `decide` checks several per request, so verdicts are memoised
under a SHA-256 digest of the record's canonical JSON (the cache holds no record text). A value that does not
survive a JSON round trip unchanged (tuples, non-string keys, NaN, non-JSON objects) is invalid.
"""

from __future__ import annotations

import functools
import hashlib
import json
from typing import Any

from tilo_policy.schemas import conforms

_CACHE_MAX = 4096
_cache: dict[tuple[str, bytes], bool] = {}


def valid(schema: str, value: Any) -> bool:
    """`value` conforms to contracts/`schema` (a file name, optionally `#/$defs/...`). Never raises."""
    try:
        raw = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
        if json.loads(raw) != value:
            return False
        key = (schema, hashlib.sha256(raw.encode("ascii")).digest())
        known = _cache.get(key)
        if known is None:
            known = conforms(schema, json.loads(raw))
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = known
        return known
    except Exception:
        return False


@functools.lru_cache(maxsize=2048)
def _string_valid(schema: str, value: str) -> bool:
    return conforms(schema, value)


def _string(schema: str, value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 128 and _string_valid(schema, value)


def is_user_id(value: Any) -> bool:
    return _string("common.schema.json#/$defs/user_id", value)


def is_agent_id(value: Any) -> bool:
    return _string("common.schema.json#/$defs/agent_id", value)


def is_timestamp(value: Any) -> bool:
    return _string("common.schema.json#/$defs/timestamp", value)
